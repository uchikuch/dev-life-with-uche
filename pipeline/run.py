#!/usr/bin/env python3
"""
Dev Life with Uche — Main CLI Entrypoint

Run the full pipeline for a single topic or execute individual stages.

Usage:
    python run.py --topic "why sprint planning is broken"
    python run.py --job JOB_ID --stage voice
    python run.py --job JOB_ID --stage assemble
    python run.py --job JOB_ID --stage shorts
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config

CALENDAR_PATH = config.ROOT_DIR / "pipeline" / "content_calendar.json"


def _inject_calendar_metadata(job_dir: Path, topic: str):
    """If the topic matches a content calendar entry, inject its thumbnail metadata."""
    if not CALENDAR_PATH.exists():
        return
    calendar = json.loads(CALENDAR_PATH.read_text())
    topic_lower = topic.lower()
    for entry in calendar:
        entry_topic = entry.get("topic", "").lower()
        entry_title = entry.get("title", "").lower()
        if (topic_lower in entry_topic or entry_topic in topic_lower
                or topic_lower in entry_title or entry_title in topic_lower):
            sp = job_dir / "script.json"
            sc = json.loads(sp.read_text())
            if entry.get("thumbnail_text"):
                sc["thumbnail_title"] = entry["thumbnail_text"]
            if entry.get("thumbnail_accent_words"):
                sc["thumbnail_accent_words"] = entry["thumbnail_accent_words"]
            if entry.get("thumbnail_sub"):
                sc["thumbnail_subtitle"] = entry["thumbnail_sub"]
            sp.write_text(json.dumps(sc, indent=2, ensure_ascii=False))
            print(f"  Thumbnail text from calendar: {entry.get('thumbnail_text')}")
            return


def main():
    parser = argparse.ArgumentParser(
        description="Dev Life with Uche — Pipeline CLI"
    )
    parser.add_argument("--topic", type=str,
                        help="Topic prompt for script generation")
    parser.add_argument("--job", type=str,
                        help="Existing job directory (name or path)")
    parser.add_argument(
        "--stage",
        choices=["script", "voice", "images", "assemble",
                 "thumbnail", "shorts", "publish"],
        help="Run a specific stage (default: full pipeline)",
    )
    parser.add_argument("--skip-approval", action="store_true",
                        help="Skip approval step during publish")
    parser.add_argument("--points", type=str, default=None,
                        help="Point numbers for shorts (e.g. 1,2)")
    args = parser.parse_args()

    if not args.topic and not args.job:
        parser.error("Provide --topic for a new run or --job to resume")

    job_dir = None

    if args.job:
        job_dir = Path(args.job)
        if not job_dir.is_absolute():
            job_dir = config.JOBS_DIR / args.job
        if not job_dir.is_dir():
            print(f"ERROR: Job directory not found: {job_dir}",
                  file=sys.stderr)
            sys.exit(1)

    if args.stage:
        stages = [args.stage]
    elif args.topic:
        stages = ["script", "voice", "images", "assemble",
                  "thumbnail", "shorts"]
    elif job_dir:
        if (job_dir / "final_video.mp4").exists():
            stages = ["shorts"]
        elif (job_dir / "timestamps.json").exists():
            stages = ["images", "assemble", "thumbnail", "shorts"]
        elif (job_dir / "script.json").exists():
            stages = ["voice", "images", "assemble", "thumbnail", "shorts"]
        else:
            print("ERROR: Cannot determine pipeline state. Use --stage.",
                  file=sys.stderr)
            sys.exit(1)
    else:
        parser.error("Provide --topic or --job")
        return

    try:
        for stage in stages:
            if stage == "script":
                from pipeline.script_gen import run as run_script
                print(f"\n  Running: script generation")
                job_dir = run_script(args.topic)
                _inject_calendar_metadata(job_dir, args.topic)

            elif stage == "voice":
                from pipeline.voice_gen import run as run_voice
                print(f"\n  Running: voice generation")
                run_voice(job_dir)

            elif stage == "images":
                from pipeline.image_gen import run as run_images
                print(f"\n  Running: image generation")
                run_images(job_dir)

            elif stage == "assemble":
                from pipeline.assemble import run as run_assemble
                print(f"\n  Running: video assembly")
                run_assemble(job_dir)

            elif stage == "thumbnail":
                from pipeline.thumbnail import generate_thumbnail
                print(f"\n  Running: thumbnail generation")
                generate_thumbnail(job_dir)

            elif stage == "shorts":
                from pipeline.shorts import run as run_shorts
                print(f"\n  Running: shorts extraction")
                pts = ([int(x) for x in args.points.split(",")]
                       if args.points else None)
                run_shorts(job_dir, points=pts)

            elif stage == "publish":
                from pipeline.publish import publish
                print(f"\n  Running: publish")
                result = publish(job_dir, skip_approval=args.skip_approval)
                print(f"\n  Result: {json.dumps(result, indent=2)}")

        print(f"\n  Pipeline complete. Job: {job_dir}")

    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
