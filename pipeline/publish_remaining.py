#!/usr/bin/env python3
"""
Publish remaining videos after YouTube quota reset.

Videos 7-12 need scheduling/uploading. Run this after quota resets (~8am CEST).
"""

import json
import logging
import sys
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from pipeline.publish import (
    _get_credentials, _verify_channel, _upload_video, _set_thumbnail,
    _schedule_video, _reserve_slot, _next_publish_slot, _append_log,
    _next_longform_after, publish_shorts,
)

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger(__name__)
tz = ZoneInfo(config.PUBLISH_TIMEZONE)

# Videos 7,9,11 already scheduled — only 8,10,12 + all shorts remaining.
REMAINING = [
    {
        "job": "20260421_202119_why-your-best-senior-engineers-keep-quit",
        "video_id": "lMJgcYg-7oc",
        "needs_schedule": False,
        "scheduled_time": "2026-04-30T14:00:00+02:00",
        "needs_shorts": True,
    },
    {
        "job": "20260421_222641_6-types-of-tech-debt-that-will-silently-",
        "video_id": "ySvw--TLsFM",
        "needs_schedule": True,
        "needs_shorts": True,
    },
    {
        "job": "20260421_232612_what-your-product-manager-is-actually-th",
        "video_id": "NMONFm-7OU4",
        "needs_schedule": False,
        "scheduled_time": "2026-05-02T14:00:00+02:00",
        "needs_shorts": True,
    },
    {
        "job": "20260422_001028_the-cto-s-week-from-hell-that-nobody-tal",
        "video_id": "qx2m-tvflwY",
        "needs_schedule": True,
        "needs_shorts": True,
    },
    {
        "job": "20260422_002750_5-signs-your-startup-is-about-to-run-out",
        "video_id": "dgDo13yOksM",
        "needs_schedule": False,
        "scheduled_time": "2026-05-05T14:00:00+02:00",
        "needs_shorts": True,
    },
    {
        "job": "20260421_224141_why-every-code-review-turns-into-a-fight",
        "video_id": "ZrHCAoI4ZWA",
        "needs_schedule": True,
        "needs_shorts": True,
    },
]


def main():
    creds = _get_credentials()
    _verify_channel(creds)

    results = []

    for item in REMAINING:
        job_dir = config.JOBS_DIR / item["job"]
        script = json.loads((job_dir / "script.json").read_text())
        title = script["title"]
        video_id = item["video_id"]

        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"  Job: {item['job']}")
        print(f"{'='*60}")

        try:
            # Upload if needed
            if video_id is None:
                video_path = job_dir / "final_video.mp4"
                description = script.get("description", script.get("summary", title))
                description += "\n\n---\nNew videos every Tuesday, Thursday & Saturday — Dev Life with Uche.\n\n#softwareengineering #devlife #techcareer #startup"
                tags = script.get("tags", [])

                print(f"  Uploading {video_path.name}...")
                video_id = _upload_video(creds, video_path, title, description, tags)

                thumb = job_dir / "thumbnail.png"
                if thumb.exists():
                    try:
                        _set_thumbnail(creds, video_id, thumb)
                    except Exception as e:
                        print(f"  Thumbnail failed: {e}")

            # Schedule if needed
            if item["needs_schedule"]:
                slot = _next_publish_slot()
                _schedule_video(creds, video_id, slot)
                _reserve_slot(slot, job_dir.name, video_id)
                scheduled = slot.isoformat()

                entry = {
                    "job_id": job_dir.name,
                    "video_id": video_id,
                    "title": title,
                    "upload_time": datetime.now(tz).isoformat(),
                    "scheduled_time": scheduled,
                    "approval_status": "approved",
                }
                _append_log(entry)
                print(f"  Scheduled: {slot.strftime('%A %d %B %Y at %H:%M %Z')}")
                print(f"  Video ID: {video_id}")
                print(f"\n  \u26a0\ufe0f  Manual step: Add end screen elements in YouTube Studio")
                print(f"     https://studio.youtube.com/video/{video_id}/editor\n")

            # Shorts
            if item["needs_shorts"]:
                if item["needs_schedule"]:
                    lf_time = slot
                else:
                    lf_time = datetime.fromisoformat(item["scheduled_time"])
                next_lf = _next_longform_after(lf_time)
                short_results = publish_shorts(
                    job_dir, lf_time,
                    parent_video_id=video_id,
                    next_longform_publish=next_lf,
                )
                print(f"  Shorts: {len(short_results)} scheduled")

            results.append((title, video_id, "OK"))

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((title, video_id or "???", f"FAILED: {e}"))

        time.sleep(5)

    print(f"\n{'='*60}")
    print(f"  PUBLISH SUMMARY")
    print(f"{'='*60}")
    for title, vid, status in results:
        print(f"  [{status:6s}] {vid:15s} {title[:55]}")
    print()


if __name__ == "__main__":
    main()
