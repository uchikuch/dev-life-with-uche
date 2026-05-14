"""
Dev Life with Uche — YouTube Publisher (Stage 5)

Uploads final video to YouTube as PRIVATE, waits for local file-based
approval, then schedules the video to go public on the next available
Tue/Thu/Sat 14:00 CEST slot.

Also handles YouTube Shorts drip-scheduling: each long-form video's
shorts are spread across the gap between that video's publish date and
the next long-form drop.

OAuth scopes required:
  - https://www.googleapis.com/auth/youtube.upload
  - https://www.googleapis.com/auth/youtube
"""
from __future__ import annotations

import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CREDENTIALS_PATH = Path.home() / ".dev-life-credentials.json"
SCHEDULE_PATH = config.JOBS_DIR / "schedule.json"
PUBLISH_LOG_PATH = config.JOBS_DIR / "publish_log.json"

DESCRIPTION_FOOTER = (
    "\n\n---\n"
    "New videos every Tuesday, Thursday & Saturday — Dev Life with Uche.\n"
    "The realities of dev life. No filter.\n\n"
    "#softwareengineering #devlife #startup #techcareer"
)

SHORTS_DESCRIPTION_TEMPLATE = (
    "From: {parent_title}\n"
    "Watch the full video: https://youtube.com/watch?v={parent_video_id}\n"
    "\n\n---\n"
    "Full breakdown on the channel!\n"
    "New videos every Tuesday, Thursday & Saturday — Dev Life with Uche.\n\n"
    "#Shorts #softwareengineering #devlife #techcareer"
)

APPROVAL_POLL_SECONDS = 60
SLOT_BUFFER_HOURS = 2
DEAD_HOUR_START = 1   # avoid 01:00–06:00 local time
DEAD_HOUR_END = 6

log = logging.getLogger("publish")

# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    """Load or create OAuth credentials. Prompts browser on first run."""
    creds = None

    if CREDENTIALS_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(CREDENTIALS_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        CREDENTIALS_PATH.write_text(creds.to_json())
    elif not creds or not creds.valid:
        client_secret = Path(config.YOUTUBE_CLIENT_SECRET_PATH)
        if not client_secret.exists():
            raise FileNotFoundError(
                f"OAuth client secret not found: {client_secret}\n"
                "Download it from Google Cloud Console -> APIs & Services -> Credentials"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=0)
        CREDENTIALS_PATH.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------

def _load_schedule() -> list[dict]:
    if SCHEDULE_PATH.exists():
        return json.loads(SCHEDULE_PATH.read_text())
    return []


def _save_schedule(schedule: list[dict]):
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_PATH.write_text(json.dumps(schedule, indent=2))


def _next_publish_slot(now: datetime | None = None) -> datetime:
    """Find the next Mon/Wed/Fri at PUBLISH_HOUR in PUBLISH_TIMEZONE."""
    tz = ZoneInfo(config.PUBLISH_TIMEZONE)
    if now is None:
        now = datetime.now(tz)
    else:
        now = now.astimezone(tz)

    day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
                "Friday": 4, "Saturday": 5, "Sunday": 6}
    publish_weekdays = sorted(day_map[d] for d in config.PUBLISH_DAYS)

    schedule = _load_schedule()
    taken = {entry["scheduled_time"] for entry in schedule}

    candidate = now.replace(hour=config.PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    for offset in range(60):
        dt = candidate + timedelta(days=offset)
        if dt.weekday() not in publish_weekdays:
            continue
        if dt <= now + timedelta(hours=SLOT_BUFFER_HOURS):
            continue
        iso = dt.isoformat()
        if iso in taken:
            continue
        return dt

    raise RuntimeError("Could not find an available publish slot in the next 60 days")


def _reserve_slot(slot: datetime, job_id: str, video_id: str):
    schedule = _load_schedule()
    schedule.append({
        "scheduled_time": slot.isoformat(),
        "job_id": job_id,
        "video_id": video_id,
    })
    _save_schedule(schedule)


# ---------------------------------------------------------------------------
# Channel verification
# ---------------------------------------------------------------------------

def _verify_channel(creds: Credentials):
    """Verify credentials are authorised against the Dev Life with Uche channel."""
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()

    items = resp.get("items", [])
    if not items:
        raise RuntimeError(
            "No YouTube channel found for these credentials.\n"
            f"Delete {CREDENTIALS_PATH} and re-run to re-authorise."
        )

    channel = items[0]
    channel_name = channel["snippet"]["title"]
    channel_id = channel["id"]
    log.info("Authorised channel: %s (%s)", channel_name, channel_id)

    if "Dev Life" not in channel_name:
        raise RuntimeError(
            f"Wrong channel authorised — expected Dev Life with Uche channel, "
            f"got '{channel_name}'.\n"
            f"Delete {CREDENTIALS_PATH} and re-run to re-authorise."
        )


# ---------------------------------------------------------------------------
# YouTube upload
# ---------------------------------------------------------------------------

def _upload_video(creds: Credentials, video_path: Path, title: str,
                  description: str, tags: list[str]) -> str:
    """Upload video as PRIVATE. Returns video ID."""
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "28",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=50 * 1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    log.info("Uploading %s (%dMB)...", video_path.name,
             video_path.stat().st_size // (1024 * 1024))

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("  Upload progress: %d%%", int(status.progress() * 100))

    video_id = response["id"]
    log.info("Upload complete. Video ID: %s", video_id)
    return video_id


def _set_thumbnail(creds: Credentials, video_id: str, thumbnail_path: Path):
    """Upload custom thumbnail for a video."""
    youtube = build("youtube", "v3", credentials=creds)
    mime = "image/jpeg" if thumbnail_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    media = MediaFileUpload(str(thumbnail_path), mimetype=mime)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    log.info("Thumbnail uploaded for %s", video_id)


def _schedule_video(creds: Credentials, video_id: str, publish_at: datetime):
    """Schedule a private video to go public at a specific time."""
    youtube = build("youtube", "v3", credentials=creds)
    youtube.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at.isoformat(),
                "selfDeclaredMadeForKids": False,
            },
        },
    ).execute()
    log.info("Scheduled %s to publish at %s", video_id, publish_at.isoformat())


# ---------------------------------------------------------------------------
# Local file-based approval
# ---------------------------------------------------------------------------

def _wait_for_approval(job_dir: Path, video_id: str, title: str,
                       publish_slot: datetime,
                       timeout_hours: int) -> tuple[str, str]:
    video_url = f"https://youtube.com/watch?v={video_id}"
    publish_str = publish_slot.strftime("%A %d %B %Y at %H:%M %Z")

    approval_info = (
        f"Title: {title}\n"
        f"Video URL: {video_url}\n"
        f"Scheduled publish: {publish_str}\n"
        f"\n"
        f"To approve: create approved.txt in this directory\n"
        f"To reject:  create rejected.txt (optional reason inside)\n"
    )

    awaiting_path = job_dir / "awaiting_approval.txt"
    approved_path = job_dir / "approved.txt"
    rejected_path = job_dir / "rejected.txt"

    awaiting_path.write_text(approval_info)

    print()
    print(f"  AWAITING APPROVAL")
    print(f"  Title: {title}")
    print(f"  URL:   {video_url}")
    print(f"  Slot:  {publish_str}")
    print(f"  To approve:  touch {approved_path}")
    print(f"  To reject:   create {rejected_path}")
    print(f"  Auto-approve in {timeout_hours}h if no response.")
    print()

    deadline = time.time() + timeout_hours * 3600
    log.info("Polling every 60s for approval files...")

    while time.time() < deadline:
        if approved_path.exists():
            log.info("Found approved.txt — approved")
            return "approved", ""

        if rejected_path.exists():
            reason = rejected_path.read_text().strip()
            log.info("Found rejected.txt — rejected: %s", reason or "(no reason)")
            return "rejected", reason

        time.sleep(APPROVAL_POLL_SECONDS)

    log.info("No response within %dh — auto-approving", timeout_hours)
    return "auto-approved", ""


# ---------------------------------------------------------------------------
# Publish log
# ---------------------------------------------------------------------------

def _append_log(entry: dict):
    log_data = []
    if PUBLISH_LOG_PATH.exists():
        log_data = json.loads(PUBLISH_LOG_PATH.read_text())
    log_data.append(entry)
    PUBLISH_LOG_PATH.write_text(json.dumps(log_data, indent=2))


# ---------------------------------------------------------------------------
# Shorts scheduling
# ---------------------------------------------------------------------------

def _next_longform_after(publish_dt: datetime) -> datetime:
    """Compute the next long-form publish slot after a given datetime."""
    tz = ZoneInfo(config.PUBLISH_TIMEZONE)
    dt = publish_dt.astimezone(tz)
    day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
               "Friday": 4, "Saturday": 5, "Sunday": 6}
    publish_weekdays = sorted(day_map[d] for d in config.PUBLISH_DAYS)

    candidate = dt + timedelta(days=1)
    candidate = candidate.replace(hour=config.PUBLISH_HOUR, minute=0,
                                  second=0, microsecond=0)
    for offset in range(8):
        check = candidate + timedelta(days=offset)
        if check.weekday() in publish_weekdays:
            return check

    return dt + timedelta(days=2, hours=0)


def _avoid_dead_hours(dt: datetime, tz: ZoneInfo) -> datetime:
    """Push a slot out of dead hours (01:00–06:00) to 06:00."""
    local = dt.astimezone(tz)
    if DEAD_HOUR_START <= local.hour < DEAD_HOUR_END:
        local = local.replace(hour=DEAD_HOUR_END, minute=0, second=0,
                              microsecond=0)
        return local
    return dt


def _compute_shorts_slots(
    longform_publish: datetime,
    next_longform_publish: datetime,
    count: int,
) -> list[datetime]:
    """
    Evenly space `count` shorts between two long-form publish times.

    Applies a 2-hour buffer at each end and pushes slots out of dead hours.
    """
    tz = ZoneInfo(config.PUBLISH_TIMEZONE)
    window_start = longform_publish + timedelta(hours=SLOT_BUFFER_HOURS)
    window_end = next_longform_publish - timedelta(hours=SLOT_BUFFER_HOURS)

    total_seconds = (window_end - window_start).total_seconds()
    if count <= 1:
        slots = [window_start]
    else:
        interval = total_seconds / (count - 1)
        slots = [window_start + timedelta(seconds=interval * i)
                 for i in range(count)]

    slots = [_avoid_dead_hours(s, tz) for s in slots]

    # Round to nearest minute
    rounded = []
    for s in slots:
        s = s.replace(second=0, microsecond=0)
        rounded.append(s)

    return rounded


def _upload_short(
    creds: Credentials,
    short_path: Path,
    title: str,
    parent_title: str,
    parent_video_id: str,
    tags: list[str],
) -> str:
    """Upload a YouTube Short as PRIVATE. Returns video ID."""
    youtube = build("youtube", "v3", credentials=creds)

    description = SHORTS_DESCRIPTION_TEMPLATE.format(
        parent_title=parent_title,
        parent_video_id=parent_video_id,
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags + ["shorts"],
            "categoryId": "28",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(short_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=25 * 1024 * 1024,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()

    return response["id"]


def publish_shorts(
    job_dir: Path,
    longform_publish: datetime,
    parent_video_id: str = "",
    next_longform_publish: datetime | None = None,
    skip_upload: bool = False,
) -> list[dict]:
    """
    Upload and schedule all shorts for a job.

    Args:
        job_dir:                Job directory with shorts/ subdirectory.
        longform_publish:       When the parent long-form video publishes.
        parent_video_id:        YouTube video ID of the parent long-form video.
        next_longform_publish:  When the next long-form video publishes.
                                If None, auto-computed from the schedule.
        skip_upload:            If True, only compute schedule without uploading.

    Returns:
        List of dicts with short_path, title, scheduled_time, video_id.
    """
    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    shorts_dir = job_dir / "shorts"
    if not shorts_dir.is_dir():
        raise FileNotFoundError(f"No shorts directory in {job_dir}")

    script = json.loads((job_dir / "script.json").read_text())
    sections = {s["id"]: s for s in script["sections"]}
    parent_title = script["title"]
    tags = script.get("tags", [])

    short_files = sorted(shorts_dir.glob("short_point_*.mp4"))
    if not short_files:
        raise FileNotFoundError("No short_point_*.mp4 files found")

    if next_longform_publish is None:
        next_longform_publish = _next_longform_after(longform_publish)

    # Build (path, title) pairs
    entries = []
    for sp in short_files:
        point_id = sp.stem.replace("short_", "")
        sec = sections.get(point_id, {})
        label = sec.get("label", point_id)
        if label and label[0].isdigit():
            dot = label.find(".")
            if dot >= 0:
                label = label[dot + 1:].strip()
        entries.append((sp, label))

    slots = _compute_shorts_slots(longform_publish, next_longform_publish,
                                  len(entries))

    results = []
    tz = ZoneInfo(config.PUBLISH_TIMEZONE)

    if not skip_upload:
        log.info("Authenticating with Google APIs...")
        creds = _get_credentials()
        _verify_channel(creds)

    for i, ((short_path, title), slot) in enumerate(zip(entries, slots)):
        short_title = f"{title} | Dev Life with Uche #Shorts"
        if len(short_title) > 100:
            short_title = f"{title[:85]}... #Shorts"

        result = {
            "short_path": str(short_path),
            "title": title,
            "short_title": short_title,
            "scheduled_time": slot.isoformat(),
            "video_id": None,
        }

        if not skip_upload:
            log.info("[%d/%d] Uploading %s...", i + 1, len(entries),
                     short_path.name)
            video_id = _upload_short(creds, short_path, short_title,
                                     parent_title, parent_video_id, tags)
            result["video_id"] = video_id

            stem = short_path.stem.replace("short_", "")
            thumb = shorts_dir / f"thumb_{stem}.jpg"
            if not thumb.exists():
                thumb = shorts_dir / f"thumb_{stem}.png"
            if thumb.exists():
                try:
                    _set_thumbnail(creds, video_id, thumb)
                except Exception as e:
                    log.warning("  Short thumbnail failed: %s", e)

            _schedule_video(creds, video_id, slot)
            _reserve_slot(slot, job_dir.name, video_id)
            log.info("  Scheduled: %s", slot.strftime("%A %d %B %H:%M %Z"))

        results.append(result)

    if not skip_upload:
        for r in results:
            _append_log({
                "job_id": job_dir.name,
                "video_id": r["video_id"],
                "title": r["short_title"],
                "upload_time": datetime.now(tz).isoformat(),
                "scheduled_time": r["scheduled_time"],
                "approval_status": "approved",
                "type": "short",
            })

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def publish(job_dir: Path, skip_approval: bool = False) -> dict:
    """Full publish pipeline."""
    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    script_path = job_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"script.json not found in {job_dir}")
    script = json.loads(script_path.read_text())

    title = script["title"]
    description = script.get("description", "")
    if not description:
        description = script.get("summary", title)
    description += DESCRIPTION_FOOTER
    tags = script.get("tags", [])

    video_path = job_dir / "final_video.mp4"
    if not video_path.exists():
        raise FileNotFoundError(f"final_video.mp4 not found in {job_dir}")

    log.info("Authenticating with Google APIs...")
    creds = _get_credentials()
    _verify_channel(creds)

    video_id = _upload_video(creds, video_path, title, description, tags)

    thumbnail_path = job_dir / "thumbnail.png"
    if thumbnail_path.exists():
        try:
            _set_thumbnail(creds, video_id, thumbnail_path)
        except Exception as e:
            log.warning("Thumbnail upload failed (channel may need verification): %s", e)

    slot = _next_publish_slot()
    log.info("Next available slot: %s", slot.strftime("%A %d %B %Y at %H:%M %Z"))

    if skip_approval:
        status, reason = "approved", ""
        log.info("Skipping approval (--skip-approval)")
    else:
        status, reason = _wait_for_approval(
            job_dir, video_id, title, slot, config.APPROVAL_WINDOW_HOURS,
        )

    scheduled_time = None
    if status in ("approved", "auto-approved"):
        _schedule_video(creds, video_id, slot)
        _reserve_slot(slot, job_dir.name, video_id)
        scheduled_time = slot.isoformat()
        log.info("Video scheduled to publish at %s", scheduled_time)
    else:
        log.info("Video rejected — remaining PRIVATE. Reason: %s", reason or "none")

    for f in ["awaiting_approval.txt", "approved.txt", "rejected.txt"]:
        p = job_dir / f
        if p.exists():
            p.unlink()

    tz = ZoneInfo(config.PUBLISH_TIMEZONE)
    entry = {
        "job_id": job_dir.name,
        "video_id": video_id,
        "title": title,
        "upload_time": datetime.now(tz).isoformat(),
        "scheduled_time": scheduled_time,
        "approval_status": status,
        "rejection_reason": reason if status == "rejected" else None,
    }
    _append_log(entry)

    log.info("Publish log updated.")
    print(f"\n  \u26a0\ufe0f  Manual step: Add end screen elements in YouTube Studio")
    print(f"     https://studio.youtube.com/video/{video_id}/editor\n")
    return entry


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — YouTube Publisher")
    parser.add_argument("--job-id", required=True, help="Job directory name under jobs/")
    parser.add_argument("--upload-thumbnail-only", action="store_true")
    parser.add_argument("--video-id", default=None)
    parser.add_argument("--skip-approval", action="store_true",
                        help="Skip file-based approval and schedule immediately")
    args = parser.parse_args()

    job = config.JOBS_DIR / args.job_id

    if not job.exists():
        print(f"Job directory not found: {job}")
        raise SystemExit(1)

    if args.upload_thumbnail_only:
        if not args.video_id:
            print("--video-id is required with --upload-thumbnail-only")
            raise SystemExit(1)

        logging.basicConfig(level=logging.INFO, format="  %(message)s")
        log.info("Authenticating...")
        creds = _get_credentials()
        _verify_channel(creds)

        thumb = job / "thumbnail.png"
        if not thumb.exists():
            print(f"thumbnail.png not found in {job}")
            raise SystemExit(1)

        _set_thumbnail(creds, args.video_id, thumb)
        print(f"\n  Thumbnail uploaded for {args.video_id}")
    else:
        result = publish(job, skip_approval=args.skip_approval)
        print(f"\n  Result: {json.dumps(result, indent=2)}")
