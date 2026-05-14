#!/usr/bin/env python3
"""
Upload missing short thumbnails for V1 (Agile), V2 (Co-Founder), V3 (Career Mistakes).
These early shorts had PNG thumbnails over YouTube's 2MB limit.
JPEGs have been generated — this script uploads them.

Run after YouTube's thumbnail rate limit resets.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from pipeline.publish import _get_credentials, _verify_channel, _set_thumbnail

JOBS = [
    ("V1 Agile",      "20260420_153314_7-signs-your-agile-process-is-just-water"),
    ("V2 Co-Founder", "20260420_125512_what-nobody-tells-you-about-being-a-tech"),
    ("V3 Career",     "20260420_164302_5-career-mistakes-software-engineers-mak"),
]


def main():
    creds = _get_credentials()
    _verify_channel(creds)

    log_data = json.loads((config.JOBS_DIR / "publish_log.json").read_text())

    job_shorts = {}
    for e in log_data:
        if e.get("type") == "short":
            job_shorts.setdefault(e["job_id"], [])
            job_shorts[e["job_id"]].append(e["video_id"])

    ok = 0
    fail = 0

    for label, job_id in JOBS:
        shorts_dir = config.JOBS_DIR / job_id / "shorts"
        vids = job_shorts.get(job_id, [])
        local_shorts = sorted(shorts_dir.glob("short_point_*.mp4"))

        print(f"\n{label} ({len(vids)} shorts):")

        for i, vid in enumerate(vids):
            point_id = local_shorts[i].stem.replace("short_", "") if i < len(local_shorts) else f"point_{i+1}"
            thumb = shorts_dir / f"thumb_{point_id}.jpg"
            if not thumb.exists():
                print(f"  {vid}: no .jpg, skip")
                continue

            print(f"  {vid} ← {thumb.name}...", end=" ")
            try:
                _set_thumbnail(creds, vid, thumb)
                print("OK")
                ok += 1
            except Exception as e:
                err = str(e)
                print(f"FAILED")
                if "rateLimitExceeded" in err or "429" in err:
                    print(f"\n  Rate limit hit after {ok} uploads. Try again later.")
                    print(f"  Remaining: {len(vids) - i - 1 + sum(len(job_shorts.get(j, [])) for _, j in JOBS[JOBS.index((label, job_id))+1:])}")
                    return
                fail += 1
            time.sleep(2)

    print(f"\nDone. OK: {ok}, Failed: {fail}")


if __name__ == "__main__":
    main()
