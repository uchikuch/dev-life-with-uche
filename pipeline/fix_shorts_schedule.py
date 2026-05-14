#!/usr/bin/env python3
"""
Reschedule all existing shorts to drip between corrected long-form dates.
Upload missing shorts (will stop gracefully if upload limit is hit).
Rebuild schedule.json.
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
    _get_credentials, _verify_channel, _set_thumbnail,
    _upload_short, _compute_shorts_slots,
    SHORTS_DESCRIPTION_TEMPLATE,
)
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger(__name__)
tz = ZoneInfo(config.PUBLISH_TIMEZONE)
SCHEDULE_PATH = config.JOBS_DIR / "schedule.json"

# Corrected Tue/Thu/Sat schedule
ORDERED_VIDEOS = [
    # (num, vid, publish_time, job_dir)
    (1,  "KLdUoJ3HbvY", "2026-04-22T14:00:00+02:00", "20260420_153314_7-signs-your-agile-process-is-just-water"),
    (2,  "MTPGC4smy3w", "2026-04-23T14:00:00+02:00", "20260420_125512_what-nobody-tells-you-about-being-a-tech"),
    (3,  "ebtIDYEzxFE", "2026-04-25T14:00:00+02:00", "20260420_164302_5-career-mistakes-software-engineers-mak"),
    (4,  "FIfqgGeKeWQ", "2026-04-28T14:00:00+02:00", "20260421_163656_5-things-nobody-tells-you-about-your-fir"),
    (5,  "YOjibe3BeLQ", "2026-04-30T14:00:00+02:00", "20260421_184019_why-your-sprint-planning-meetings-are-a-"),
    (6,  "7unwyookhfE", "2026-05-02T14:00:00+02:00", "20260421_193235_7-things-customers-say-that-mean-the-exa"),
    (7,  "lMJgcYg-7oc", "2026-05-05T14:00:00+02:00", "20260421_202119_why-your-best-senior-engineers-keep-quit"),
    (8,  "ySvw--TLsFM", "2026-05-07T14:00:00+02:00", "20260421_222641_6-types-of-tech-debt-that-will-silently-"),
    (9,  "NMONFm-7OU4", "2026-05-09T14:00:00+02:00", "20260421_232612_what-your-product-manager-is-actually-th"),
    (10, "qx2m-tvflwY", "2026-05-12T14:00:00+02:00", "20260422_001028_the-cto-s-week-from-hell-that-nobody-tal"),
    (11, "dgDo13yOksM", "2026-05-14T14:00:00+02:00", "20260422_002750_5-signs-your-startup-is-about-to-run-out"),
    (12, "ZrHCAoI4ZWA", "2026-05-16T14:00:00+02:00", "20260421_224141_why-every-code-review-turns-into-a-fight"),
]

# Sentinel: next video after V12 (next Tue = May 19)
SENTINEL_TIME = datetime(2026, 5, 19, 14, 0, tzinfo=tz)


def get_short_label(sections, short_path):
    """Get the display label for a short from its script section."""
    point_id = short_path.stem.replace("short_", "")
    sec = sections.get(point_id, {})
    label = sec.get("label", point_id)
    if label and label[0].isdigit():
        dot = label.find(".")
        if dot >= 0:
            label = label[dot + 1:].strip()
    return label


def main():
    creds = _get_credentials()
    _verify_channel(creds)
    youtube = build("youtube", "v3", credentials=creds)

    # Step 1: Get all shorts from YouTube and map to parents
    print("\n  Fetching all channel videos...")
    channel_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_pl = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    all_ids = []
    next_page = None
    while True:
        pl_resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_pl, maxResults=50, pageToken=next_page
        ).execute()
        for item in pl_resp["items"]:
            all_ids.append(item["snippet"]["resourceId"]["videoId"])
        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    print(f"  Found {len(all_ids)} videos")

    # Get details for all videos
    all_details = []
    for i in range(0, len(all_ids), 50):
        batch = all_ids[i:i+50]
        resp = youtube.videos().list(part="snippet,status", id=",".join(batch)).execute()
        all_details.extend(resp.get("items", []))

    # Map shorts: parent_vid -> {normalized_label: (short_vid, status)}
    parent_shorts = {}
    for v in all_details:
        vid = v["id"]
        title = v["snippet"]["title"]
        desc = v["snippet"].get("description", "")
        status = v["status"]["privacyStatus"]

        if "#Shorts" not in title and "#shorts" not in title:
            continue

        parent_id = None
        if "youtube.com/watch?v=" in desc:
            idx = desc.index("youtube.com/watch?v=") + len("youtube.com/watch?v=")
            parent_id = desc[idx:idx+11]

        if parent_id:
            parent_shorts.setdefault(parent_id, {})
            # Normalize: strip the " | Dev Life with Uche #Shorts" suffix
            norm = title
            for suffix in [" | Dev Life with Uche #Shorts", "... #Shorts",
                           " #Shorts", "| Dev Life with Uche #Shorts"]:
                if norm.endswith(suffix):
                    norm = norm[:-len(suffix)].strip()
                    break
            parent_shorts[parent_id][norm.lower()] = (vid, status)

    print("\n  Shorts per parent:")
    for vnum, parent_vid, _, _ in ORDERED_VIDEOS:
        shorts = parent_shorts.get(parent_vid, {})
        print(f"    V{vnum} ({parent_vid}): {len(shorts)} shorts")

    # Step 2: Process each video's shorts
    schedule_entries = []
    upload_count = 0
    reschedule_count = 0
    skipped_public = 0
    failed_uploads = []
    hit_limit = False
    now = datetime.now(tz)

    for i, (vnum, parent_vid, lf_time_str, job_dir_name) in enumerate(ORDERED_VIDEOS):
        lf_time = datetime.fromisoformat(lf_time_str)

        if i + 1 < len(ORDERED_VIDEOS):
            next_lf_time = datetime.fromisoformat(ORDERED_VIDEOS[i + 1][2])
        else:
            next_lf_time = SENTINEL_TIME

        job_dir = config.JOBS_DIR / job_dir_name
        shorts_dir = job_dir / "shorts"
        if not shorts_dir.is_dir():
            continue

        script = json.loads((job_dir / "script.json").read_text())
        sections = {s["id"]: s for s in script["sections"]}
        parent_title = script["title"]
        tags = script.get("tags", [])

        local_shorts = sorted(shorts_dir.glob("short_point_*.mp4"))
        existing = parent_shorts.get(parent_vid, {})

        slots = _compute_shorts_slots(lf_time, next_lf_time, len(local_shorts))

        print(f"\n  Video {vnum}: {len(local_shorts)} local, {len(existing)} on YT")
        print(f"    Window: {lf_time.strftime('%a %d %b %H:%M')} → {next_lf_time.strftime('%a %d %b %H:%M')}")

        for j, sp in enumerate(local_shorts):
            label = get_short_label(sections, sp)
            norm_label = label.strip().lower()
            slot = slots[j]

            match = existing.get(norm_label)

            if match:
                short_vid, status = match

                if status == "public":
                    print(f"    {short_vid} ALREADY PUBLIC — skip")
                    skipped_public += 1
                    schedule_entries.append({
                        "scheduled_time": slot.isoformat(),
                        "job_id": job_dir_name,
                        "video_id": short_vid,
                        "type": "short",
                        "status": "public",
                    })
                    continue

                if slot <= now:
                    # Can't schedule in the past — set to public immediately
                    print(f"    {short_vid} slot in past — making PUBLIC now")
                    try:
                        youtube.videos().update(
                            part="status",
                            body={
                                "id": short_vid,
                                "status": {
                                    "privacyStatus": "public",
                                    "selfDeclaredMadeForKids": False,
                                },
                            },
                        ).execute()
                        reschedule_count += 1
                    except Exception as e:
                        print(f"      ✗ Failed: {e}")
                    schedule_entries.append({
                        "scheduled_time": slot.isoformat(),
                        "job_id": job_dir_name,
                        "video_id": short_vid,
                        "type": "short",
                        "status": "public",
                    })
                    time.sleep(0.5)
                    continue

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
                    reschedule_count += 1
                except Exception as e:
                    print(f"      ✗ Failed: {e}")
                schedule_entries.append({
                    "scheduled_time": slot.isoformat(),
                    "job_id": job_dir_name,
                    "video_id": short_vid,
                    "type": "short",
                })
                time.sleep(0.5)
            else:
                # Need to upload
                if hit_limit:
                    print(f"    SKIP upload {sp.name} (limit hit)")
                    continue

                short_title = f"{label} | Dev Life with Uche #Shorts"
                if len(short_title) > 100:
                    short_title = f"{label[:85]}... #Shorts"

                print(f"    Upload {sp.name}: {label[:45]}...")

                try:
                    video_id = _upload_short(creds, sp, short_title,
                                              parent_title, parent_vid, tags)
                    upload_count += 1

                    # Thumbnail
                    stem = sp.stem.replace("short_", "")
                    thumb = shorts_dir / f"thumb_{stem}.jpg"
                    if not thumb.exists():
                        thumb = shorts_dir / f"thumb_{stem}.png"
                    if thumb.exists():
                        try:
                            _set_thumbnail(creds, video_id, thumb)
                        except Exception as e:
                            print(f"      Thumb failed: {e}")

                    # Schedule
                    if slot > now:
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
                    else:
                        youtube.videos().update(
                            part="status",
                            body={
                                "id": video_id,
                                "status": {
                                    "privacyStatus": "public",
                                    "selfDeclaredMadeForKids": False,
                                },
                            },
                        ).execute()
                        print(f"      ✓ {video_id} → PUBLIC (slot in past)")

                    schedule_entries.append({
                        "scheduled_time": slot.isoformat(),
                        "job_id": job_dir_name,
                        "video_id": video_id,
                        "type": "short",
                    })
                    time.sleep(2)

                except Exception as e:
                    err = str(e)
                    print(f"      ✗ Upload failed: {err[:100]}")
                    failed_uploads.append((sp.name, label))
                    if "uploadLimit" in err or "quota" in err.lower() or "403" in err:
                        print(f"\n  ⚠️  Upload limit hit after {upload_count} uploads")
                        hit_limit = True

    # Step 3: Rebuild schedule.json
    schedule = []

    # Long-form entries
    for vnum, vid, time_str, job_dir_name in ORDERED_VIDEOS:
        if vnum == 1:
            continue  # Video 1 is already public
        schedule.append({
            "scheduled_time": time_str,
            "job_id": job_dir_name,
            "video_id": vid,
        })

    # Short entries
    schedule.extend(schedule_entries)
    schedule.sort(key=lambda e: e["scheduled_time"])

    SCHEDULE_PATH.write_text(json.dumps(schedule, indent=2))

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Shorts rescheduled: {reschedule_count}")
    print(f"  Shorts already public: {skipped_public}")
    print(f"  Shorts uploaded: {upload_count}")
    print(f"  Schedule entries: {len(schedule)}")
    if failed_uploads:
        print(f"  Failed uploads ({len(failed_uploads)}):")
        for name, label in failed_uploads:
            print(f"    {name}: {label[:60]}")
    print()


if __name__ == "__main__":
    main()
