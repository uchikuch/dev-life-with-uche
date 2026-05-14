#!/usr/bin/env python3
"""
Batch runner for remaining videos from the content calendar.
Runs full pipeline + publish for each topic sequentially.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
VENV_PYTHON = str(ROOT / "venv" / "bin" / "python")
RUN_PY = str(ROOT / "run.py")

# Videos 5-7 handled separately. Start from Video 8.
TOPICS = [
    "6 types of tech debt that will silently kill your startup — the hidden code rot that compounds until it's too late to fix",
    "What your product manager is actually thinking in every meeting — the internal monologue of a PM dealing with engineers, stakeholders, and impossible deadlines",
    "The CTO's week from hell that nobody talks about — production incidents, board meetings, hiring crises, and the loneliness of technical leadership",
    "5 signs your startup is about to run out of money — the subtle indicators every founder misses until it's almost too late",
    "Why every code review turns into a fight — the ego, style wars, and communication failures that make pull requests toxic",
]

COOLDOWN_SECONDS = 90


def run_video(index: int, topic: str):
    """Run full pipeline for a single topic, then publish."""
    tz = ZoneInfo("Europe/Berlin")
    now = datetime.now(tz).strftime("%H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  VIDEO {index}: {topic[:70]}...")
    print(f"  Started at {now}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        [VENV_PYTHON, RUN_PY, "--topic", topic],
        cwd=str(ROOT),
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"\n  FAILED: Pipeline failed for video {index}")
        return False

    jobs_dir = ROOT / "jobs"
    job_dirs = sorted([d for d in jobs_dir.iterdir()
                       if d.is_dir() and d.name[:8].isdigit()],
                      key=lambda p: p.name)
    job_dir = job_dirs[-1]
    print(f"\n  Job: {job_dir.name}")

    result = subprocess.run(
        [VENV_PYTHON, RUN_PY, "--job", str(job_dir), "--stage", "publish",
         "--skip-approval"],
        cwd=str(ROOT),
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"\n  FAILED: Publish failed for video {index}")
        return False

    sys.path.insert(0, str(ROOT))
    from pipeline.publish import (
        _next_longform_after, publish_shorts, _load_schedule,
    )
    import logging
    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    schedule = _load_schedule()
    longform_entries = [e for e in schedule
                        if e.get("type") != "short"
                        and e.get("job_id") == job_dir.name
                        and e.get("scheduled_time")]
    if longform_entries:
        from datetime import datetime as dt
        lf_time = dt.fromisoformat(longform_entries[-1]["scheduled_time"])
        video_id = longform_entries[-1]["video_id"]
        next_lf = _next_longform_after(lf_time)

        results = publish_shorts(
            job_dir, lf_time,
            parent_video_id=video_id,
            next_longform_publish=next_lf,
        )
        print(f"\n  Shorts scheduled: {len(results)}")
        for r in results:
            sdt = dt.fromisoformat(r["scheduled_time"])
            print(f"    {r['title'][:50]:50s} {sdt.strftime('%a %d %b %H:%M')}")
    else:
        print("\n  WARNING: Could not find long-form in schedule for shorts")

    return True


def main():
    start = time.time()
    results = []
    start_num = 8

    for i, topic in enumerate(TOPICS, start_num):
        if i > start_num:
            print(f"\n  Cooling down {COOLDOWN_SECONDS}s before next video...")
            time.sleep(COOLDOWN_SECONDS)

        ok = run_video(i, topic)
        results.append((i, topic, ok))
        if not ok:
            print(f"\n  Continuing to next video despite failure...")

    elapsed = time.time() - start
    hours = int(elapsed // 3600)
    mins = int((elapsed % 3600) // 60)

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE — {hours}h {mins}m")
    print(f"{'='*60}")
    for i, topic, ok in results:
        status = "OK" if ok else "FAILED"
        print(f"  [{status:6s}] Video {i}: {topic[:60]}")
    print()


if __name__ == "__main__":
    main()
