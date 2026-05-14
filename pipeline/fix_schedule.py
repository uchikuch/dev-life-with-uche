#!/usr/bin/env python3
"""
Fix the entire YouTube schedule:
1. Reschedule all 11 long-form videos to clean Tue/Thu/Sat 14:00 CEST cadence
2. Fix Video 8's title
3. Reschedule all existing shorts to drip between long-form pairs
4. Upload missing shorts and schedule them
5. Rebuild schedule.json from scratch
"""

import json
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from pipeline.publish import (
    _get_credentials, _verify_channel, _schedule_video, _set_thumbnail,
    _upload_short, _compute_shorts_slots, _avoid_dead_hours,
    SCOPES, SHORTS_DESCRIPTION_TEMPLATE, SLOT_BUFFER_HOURS,
    DEAD_HOUR_START, DEAD_HOUR_END,
)
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger(__name__)
tz = ZoneInfo(config.PUBLISH_TIMEZONE)

SCHEDULE_PATH = config.JOBS_DIR / "schedule.json"

# ============================================================
# GROUND TRUTH: Video ID → Job Dir mapping
# ============================================================

LONGFORM_SCHEDULE = [
    # (video_num, video_id, new_publish_time_cest, job_dir, correct_title)
    (2,  "MTPGC4smy3w", "2026-04-23T14:00:00+02:00", "20260420_125512_what-nobody-tells-you-about-being-a-tech", None),
    (3,  "ebtIDYEzxFE", "2026-04-25T14:00:00+02:00", "20260420_164302_5-career-mistakes-software-engineers-mak", None),
    (4,  "FIfqgGeKeWQ", "2026-04-28T14:00:00+02:00", "20260421_163656_5-things-nobody-tells-you-about-your-fir", None),
    (5,  "YOjibe3BeLQ", "2026-04-30T14:00:00+02:00", "20260421_184019_why-your-sprint-planning-meetings-are-a-", None),
    (6,  "7unwyookhfE", "2026-05-02T14:00:00+02:00", "20260421_193235_7-things-customers-say-that-mean-the-exa", None),
    (7,  "lMJgcYg-7oc", "2026-05-05T14:00:00+02:00", "20260421_202119_why-your-best-senior-engineers-keep-quit", None),
    (8,  "ySvw--TLsFM", "2026-05-07T14:00:00+02:00", "20260421_222641_6-types-of-tech-debt-that-will-silently-", "6 Types of Tech Debt That Will Silently Kill Your Startup"),
    (9,  "NMONFm-7OU4", "2026-05-09T14:00:00+02:00", "20260421_232612_what-your-product-manager-is-actually-th", None),
    (10, "qx2m-tvflwY", "2026-05-12T14:00:00+02:00", "20260422_001028_the-cto-s-week-from-hell-that-nobody-tal", None),
    (11, "dgDo13yOksM", "2026-05-14T14:00:00+02:00", "20260422_002750_5-signs-your-startup-is-about-to-run-out", None),
    (12, "ZrHCAoI4ZWA", "2026-05-16T14:00:00+02:00", "20260421_224141_why-every-code-review-turns-into-a-fight", None),
]

# Video 1 is already public
VIDEO_1 = ("KLdUoJ3HbvY", "20260420_153314_7-signs-your-agile-process-is-just-water")


def get_youtube_client(creds):
    return build("youtube", "v3", credentials=creds)


def fetch_all_channel_videos(youtube):
    """Fetch all videos from the channel."""
    videos = []
    channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    next_page = None
    while True:
        pl_resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page,
        ).execute()
        for item in pl_resp["items"]:
            videos.append(item["snippet"]["resourceId"]["videoId"])
        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    return videos


def get_video_details(youtube, video_ids):
    """Get video details in batches of 50."""
    all_details = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        resp = youtube.videos().list(
            part="snippet,status",
            id=",".join(batch),
        ).execute()
        all_details.extend(resp.get("items", []))
    return all_details


# ============================================================
# Step 1: Reschedule long-form videos
# ============================================================

def reschedule_longforms(youtube):
    print(f"\n{'='*60}")
    print("  STEP 1: Reschedule all long-form videos")
    print(f"{'='*60}\n")

    for vnum, vid, new_time, job_dir, title_fix in LONGFORM_SCHEDULE:
        dt = datetime.fromisoformat(new_time)
        print(f"  Video {vnum}: {vid} → {dt.strftime('%a %d %b %Y %H:%M %Z')}")

        youtube.videos().update(
            part="status",
            body={
                "id": vid,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": dt.isoformat(),
                    "selfDeclaredMadeForKids": False,
                },
            },
        ).execute()
        print(f"    ✓ Rescheduled")
        time.sleep(1)

    print(f"\n  All 11 long-form videos rescheduled.\n")


# ============================================================
# Step 2: Fix Video 8 title
# ============================================================

def fix_video8_title(youtube):
    print(f"\n{'='*60}")
    print("  STEP 2: Fix Video 8 title")
    print(f"{'='*60}\n")

    vid = "ySvw--TLsFM"
    job_dir = config.JOBS_DIR / "20260421_222641_6-types-of-tech-debt-that-will-silently-"
    script = json.loads((job_dir / "script.json").read_text())
    correct_title = script["title"]

    # Get current snippet to preserve description/tags
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    snippet = resp["items"][0]["snippet"]

    old_title = snippet["title"]
    print(f"  Old title: {old_title}")
    print(f"  New title: {correct_title}")

    snippet["title"] = correct_title
    # categoryId is required for snippet updates
    snippet["categoryId"] = snippet.get("categoryId", "28")

    youtube.videos().update(
        part="snippet",
        body={"id": vid, "snippet": snippet},
    ).execute()
    print(f"    ✓ Title fixed\n")


# ============================================================
# Step 3: Map existing shorts on YouTube to parent videos
# ============================================================

def map_shorts_to_parents(youtube, all_video_ids):
    """Map each short on YouTube to its parent long-form video.
    Returns parent_map (parent_vid -> {short_title: short_vid}) and short_details.
    """
    print(f"\n{'='*60}")
    print("  STEP 3: Map existing shorts to parent videos")
    print(f"{'='*60}\n")

    details = get_video_details(youtube, all_video_ids)

    # Build parent map: parent_video_id → {normalized_title: short_video_id}
    parent_map = {}
    short_details = {}

    for v in details:
        vid = v["id"]
        desc = v["snippet"].get("description", "")
        title = v["snippet"]["title"]

        is_short = "#Shorts" in title or "#shorts" in title
        if not is_short:
            continue

        parent_id = None
        if "youtube.com/watch?v=" in desc:
            idx = desc.index("youtube.com/watch?v=") + len("youtube.com/watch?v=")
            parent_id = desc[idx:idx+11]

        if parent_id:
            parent_map.setdefault(parent_id, {})
            # Normalize title for matching: strip suffix, lowercase
            norm = title.replace(" | Dev Life with Uche #Shorts", "").replace("... #Shorts", "").strip().lower()
            parent_map[parent_id][norm] = vid
            short_details[vid] = {
                "title": title,
                "parent_id": parent_id,
                "publish_at": v["status"].get("publishAt"),
            }

    # Report
    all_parents = set()
    for vnum, vid, _, job_dir, _ in LONGFORM_SCHEDULE:
        all_parents.add(vid)
    all_parents.add(VIDEO_1[0])

    for parent_id in sorted(all_parents):
        shorts = parent_map.get(parent_id, {})
        print(f"  {parent_id}: {len(shorts)} shorts on YouTube")

    return parent_map, short_details


# ============================================================
# Step 4: Reschedule existing shorts + upload missing ones
# ============================================================

def process_shorts(youtube, creds, parent_map):
    print(f"\n{'='*60}")
    print("  STEP 4: Reschedule & upload shorts")
    print(f"{'='*60}\n")

    # Build the ordered long-form schedule including Video 1
    # Video 1 is already public — we'll use April 22 14:00 CEST as its
    # "publish time" for shorts drip calculation (it went live Apr 21)
    ordered = [
        (1, VIDEO_1[0], datetime(2026, 4, 22, 14, 0, tzinfo=tz), VIDEO_1[1]),
    ]
    for vnum, vid, new_time, job_dir, _ in LONGFORM_SCHEDULE:
        ordered.append((vnum, vid, datetime.fromisoformat(new_time), job_dir))

    # Add a sentinel for the video after Video 12 (next Tue after May 17 = May 19)
    sentinel_time = datetime(2026, 5, 19, 14, 0, tzinfo=tz)

    schedule_entries = []
    upload_count = 0
    upload_errors = []

    for i, (vnum, parent_vid, lf_time, job_dir_name) in enumerate(ordered):
        if i + 1 < len(ordered):
            next_lf_time = ordered[i + 1][2]
        else:
            next_lf_time = sentinel_time

        job_dir = config.JOBS_DIR / job_dir_name
        shorts_dir = job_dir / "shorts"

        if not shorts_dir.is_dir():
            print(f"\n  Video {vnum} ({parent_vid}): No shorts directory, skipping")
            continue

        # Load script to get section labels for titles
        script = json.loads((job_dir / "script.json").read_text())
        sections = {s["id"]: s for s in script["sections"]}
        parent_title = script["title"]
        tags = script.get("tags", [])

        local_shorts = sorted(shorts_dir.glob("short_point_*.mp4"))
        existing_titles = parent_map.get(parent_vid, {})

        print(f"\n  Video {vnum} ({parent_vid}): {len(local_shorts)} local, {len(existing_titles)} on YouTube")
        print(f"    Drip window: {lf_time.strftime('%a %d %b %H:%M')} → {next_lf_time.strftime('%a %d %b %H:%M')}")

        # Compute drip schedule for ALL shorts (local count)
        slots = _compute_shorts_slots(lf_time, next_lf_time, len(local_shorts))

        # Match local shorts to YouTube by title
        needs_upload = []
        for j, sp in enumerate(local_shorts):
            point_id = sp.stem.replace("short_", "")
            sec = sections.get(point_id, {})
            label = sec.get("label", point_id)
            if label and label[0].isdigit():
                dot = label.find(".")
                if dot >= 0:
                    label = label[dot + 1:].strip()

            norm_label = label.strip().lower()
            slot = slots[j]

            # Check if this short already exists on YouTube
            short_vid = existing_titles.get(norm_label)
            if short_vid:
                print(f"    Reschedule {short_vid} → {slot.strftime('%a %d %b %H:%M')}")
                try:
                    youtube.videos().update(
                        part="status",
                        body={
                            "id": short_vid,
                            "status": {
                                "privacyStatus": "private",
                                "publishAt": slot.isoformat(),
                                "selfDeclaredMadeForKids": False,
                            },
                        },
                    ).execute()

                    schedule_entries.append({
                        "scheduled_time": slot.isoformat(),
                        "job_id": job_dir_name,
                        "video_id": short_vid,
                        "type": "short",
                    })
                except Exception as e:
                    print(f"    ✗ Reschedule failed: {e}")
                time.sleep(0.5)
            else:
                needs_upload.append((j, sp, slot, label))

        if needs_upload:
            print(f"    {len(needs_upload)} shorts need uploading")

        for j, sp, slot, label in needs_upload:
            short_title = f"{label} | Dev Life with Uche #Shorts"
            if len(short_title) > 100:
                short_title = f"{label[:85]}... #Shorts"

            print(f"    Upload {sp.name}: {short_title[:50]}...")

            try:
                video_id = _upload_short(creds, sp, short_title,
                                          parent_title, parent_vid, tags)
                upload_count += 1

                # Set thumbnail
                stem = sp.stem.replace("short_", "")
                thumb = shorts_dir / f"thumb_{stem}.jpg"
                if not thumb.exists():
                    thumb = shorts_dir / f"thumb_{stem}.png"
                if thumb.exists():
                    try:
                        _set_thumbnail(creds, video_id, thumb)
                    except Exception as e:
                        print(f"      Thumbnail failed: {e}")

                # Schedule
                youtube.videos().update(
                    part="status",
                    body={
                        "id": video_id,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": slot.isoformat(),
                            "selfDeclaredMadeForKids": False,
                        },
                    },
                ).execute()

                print(f"      ✓ {video_id} → {slot.strftime('%a %d %b %H:%M')}")

                schedule_entries.append({
                    "scheduled_time": slot.isoformat(),
                    "job_id": job_dir_name,
                    "video_id": video_id,
                    "type": "short",
                })
                time.sleep(2)

            except Exception as e:
                err_msg = str(e)
                print(f"      ✗ Upload failed: {err_msg}")
                upload_errors.append((sp.name, err_msg))
                if "quota" in err_msg.lower() or "uploadLimit" in err_msg or "403" in err_msg:
                    print(f"\n  ⚠️  Quota/upload limit hit after {upload_count} uploads.")
                    print(f"  Remaining shorts will need to be uploaded after quota reset.\n")
                    return schedule_entries, upload_count, upload_errors

    return schedule_entries, upload_count, upload_errors


# ============================================================
# Step 5: Rebuild schedule.json
# ============================================================

def rebuild_schedule(short_entries):
    print(f"\n{'='*60}")
    print("  STEP 5: Rebuild schedule.json")
    print(f"{'='*60}\n")

    schedule = []

    # Add Video 1 (already public, no schedule entry needed)

    # Add all long-form entries
    for vnum, vid, new_time, job_dir, _ in LONGFORM_SCHEDULE:
        schedule.append({
            "scheduled_time": new_time,
            "job_id": job_dir,
            "video_id": vid,
        })

    # Add all short entries
    schedule.extend(short_entries)

    # Sort by scheduled_time
    schedule.sort(key=lambda e: e["scheduled_time"])

    # Write
    SCHEDULE_PATH.write_text(json.dumps(schedule, indent=2))
    print(f"  Written {len(schedule)} entries to schedule.json")
    print(f"    Long-forms: {len(LONGFORM_SCHEDULE)}")
    print(f"    Shorts: {len(short_entries)}")


# ============================================================
# Main
# ============================================================

def main():
    print(f"\n{'='*60}")
    print("  DEV LIFE WITH UCHE — SCHEDULE FIX")
    print(f"  {datetime.now(tz).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'='*60}")

    creds = _get_credentials()
    _verify_channel(creds)
    youtube = get_youtube_client(creds)

    # Fetch all videos from channel
    print("\n  Fetching all channel videos...")
    all_video_ids = fetch_all_channel_videos(youtube)
    print(f"  Found {len(all_video_ids)} videos on channel")

    # Step 1: Reschedule long-forms
    reschedule_longforms(youtube)

    # Step 2: Fix Video 8 title
    fix_video8_title(youtube)

    # Step 3: Map existing shorts
    parent_map, short_details = map_shorts_to_parents(youtube, all_video_ids)

    # Step 4: Reschedule existing + upload missing shorts
    short_entries, upload_count, upload_errors = process_shorts(
        youtube, creds, parent_map
    )

    # Step 5: Rebuild schedule.json
    rebuild_schedule(short_entries)

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Long-forms rescheduled: 11")
    print(f"  Video 8 title fixed: ✓")
    print(f"  Shorts rescheduled: {len(short_entries) - upload_count}")
    print(f"  Shorts uploaded: {upload_count}")
    if upload_errors:
        print(f"  Upload errors: {len(upload_errors)}")
        for name, err in upload_errors:
            print(f"    {name}: {err[:80]}")
    print()

    # End screen reminders
    print(f"  ⚠️  Manual step: Add end screen elements for each video:")
    for vnum, vid, _, _, _ in LONGFORM_SCHEDULE:
        print(f"    Video {vnum}: https://studio.youtube.com/video/{vid}/editor")
    print()


if __name__ == "__main__":
    main()
