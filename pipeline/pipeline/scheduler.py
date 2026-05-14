"""
Dev Life with Uche — Batch Scheduler

Runs the full pipeline (script → voice → images → assembly → thumbnail)
for the next N unprocessed topics from content_calendar.json.

Usage:
    python pipeline/scheduler.py --batch 3

State is persisted to pipeline/calendar_state.json after each stage so a
failed batch can be safely re-run — completed topics are skipped.
"""

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PIPELINE_DIR  = Path(__file__).parent
CALENDAR_PATH = PIPELINE_DIR / "content_calendar.json"
STATE_PATH    = PIPELINE_DIR / "calendar_state.json"
CET           = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_calendar() -> list[dict]:
    if not CALENDAR_PATH.exists():
        raise FileNotFoundError(f"content_calendar.json not found at {CALENDAR_PATH}")
    return json.loads(CALENDAR_PATH.read_text())


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _probe_video(path: Path) -> tuple[float, float]:
    """Return (file_size_mb, duration_s) via ffprobe."""
    size_mb = path.stat().st_size / (1024 * 1024)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0
    return size_mb, duration


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(batch_size: int):
    # Import pipeline modules here so import errors surface clearly
    import config
    from pipeline.script_gen   import run as run_script
    from pipeline.voice_gen    import run as run_voice
    from pipeline.image_gen    import run as run_images
    from pipeline.assemble     import run as run_assemble
    from pipeline.thumbnail    import generate_thumbnail

    calendar = _load_calendar()
    state    = _load_state()

    # Find unprocessed: not in state at all, or status != "complete"
    unprocessed = [
        (i, entry) for i, entry in enumerate(calendar)
        if state.get(str(i), {}).get("status") != "complete"
    ]

    if not unprocessed:
        print("\n  All topics in the content calendar have been processed.")
        return

    batch = unprocessed[:batch_size]

    print(f"\n{'=' * 62}")
    print(f"  Batch Scheduler — {len(batch)} topic(s) of "
          f"{len(unprocessed)} remaining")
    print(f"{'=' * 62}")

    summary_rows = []

    for idx, (cal_index, entry) in enumerate(batch):
        title   = entry["title"]
        topic   = entry["topic"]
        th_text = entry.get("thumbnail_text", "")
        th_sub  = entry.get("thumbnail_sub", "")
        th_img  = entry.get("thumbnail_image", "synthesis") + ".png"

        print(f"\n  [{idx + 1}/{len(batch)}] {title}")
        print(f"  {'─' * 58}")

        # Initialise / reset state for this entry
        key = str(cal_index)
        if key not in state:
            state[key] = {
                "index":        cal_index,
                "title":        title,
                "job_id":       None,
                "status":       "in_progress",
                "stages":       {},
                "error":        None,
                "file_size_mb": None,
                "duration_s":   None,
                "started_at":   datetime.now(CET).isoformat(),
            }
        else:
            state[key]["status"] = "in_progress"
            state[key]["error"]  = None
        _save_state(state)

        job_dir   = None
        failed    = False
        error_msg = None

        # ── 1. script_gen ────────────────────────────────────────────────
        try:
            print(f"  [1/5] script_gen ...", end=" ", flush=True)
            job_dir = run_script(topic)

            # Inject thumbnail metadata into script.json
            sp = job_dir / "script.json"
            sc = json.loads(sp.read_text())
            sc["thumbnail_title"]      = th_text
            sc["thumbnail_subtitle"]   = th_sub
            sc["thumbnail_background"] = th_img
            sp.write_text(json.dumps(sc, indent=2, ensure_ascii=False))

            state[key]["job_id"]             = job_dir.name
            state[key]["stages"]["script_gen"] = "complete"
            _save_state(state)
            print("OK")
        except Exception as e:
            error_msg = f"script_gen: {e}"
            print(f"FAIL\n  Error: {error_msg}")
            failed = True

        # ── 2. voice_gen ─────────────────────────────────────────────────
        if not failed:
            try:
                print(f"  [2/5] voice_gen ...", end=" ", flush=True)
                run_voice(job_dir)
                state[key]["stages"]["voice_gen"] = "complete"
                _save_state(state)
                print("OK")
            except Exception as e:
                error_msg = f"voice_gen: {e}"
                print(f"FAIL\n  Error: {error_msg}")
                failed = True

        # ── 3. image_gen ─────────────────────────────────────────────────
        if not failed:
            try:
                print(f"  [3/5] image_gen ...", end=" ", flush=True)
                run_images(job_dir)
                state[key]["stages"]["image_gen"] = "complete"
                _save_state(state)
                print("OK")
            except Exception as e:
                error_msg = f"image_gen: {e}"
                print(f"FAIL\n  Error: {error_msg}")
                failed = True

        # ── 4. assemble ──────────────────────────────────────────────────
        if not failed:
            try:
                print(f"  [4/5] assemble ...", end=" ", flush=True)
                run_assemble(job_dir)
                state[key]["stages"]["assemble"] = "complete"
                _save_state(state)
                print("OK")
            except Exception as e:
                error_msg = f"assemble: {e}"
                print(f"FAIL\n  Error: {error_msg}")
                failed = True

        # ── 5. thumbnail ─────────────────────────────────────────────────
        if not failed:
            try:
                print(f"  [5/5] thumbnail ...", end=" ", flush=True)
                generate_thumbnail(job_dir)
                state[key]["stages"]["thumbnail"] = "complete"
                _save_state(state)
                print("OK")
            except Exception as e:
                error_msg = f"thumbnail: {e}"
                print(f"FAIL\n  Error: {error_msg}")
                failed = True

        # ── Probe final video ────────────────────────────────────────────
        file_size_mb = None
        duration_s   = None

        if not failed and job_dir:
            final_video = job_dir / "final_video.mp4"
            if final_video.exists():
                file_size_mb, duration_s = _probe_video(final_video)
                state[key]["file_size_mb"] = round(file_size_mb, 1)
                state[key]["duration_s"]   = round(duration_s, 1)

        # ── Finalise state ───────────────────────────────────────────────
        if failed:
            state[key]["status"] = "failed"
            state[key]["error"]  = error_msg
        else:
            state[key]["status"]       = "complete"
            state[key]["completed_at"] = datetime.now(CET).isoformat()

        _save_state(state)

        summary_rows.append({
            "n":            idx + 1,
            "title":        title,
            "job_id":       state[key].get("job_id") or "—",
            "file_size_mb": file_size_mb,
            "duration_s":   duration_s,
            "status":       state[key]["status"],
            "error":        error_msg,
        })

    # ── Summary table ────────────────────────────────────────────────────────
    print(f"\n{'=' * 62}")
    print(f"  Summary — {len(summary_rows)} topic(s) processed")
    print(f"{'=' * 62}")
    print(f"  {'#':<3}  {'Title':<38}  {'Size':>7}  {'Dur':>6}  Status")
    print(f"  {'─'*3}  {'─'*38}  {'─'*7}  {'─'*6}  {'─'*8}")

    for row in summary_rows:
        size_str = f"{row['file_size_mb']:.1f}MB" if row["file_size_mb"] else "—"
        dur_s    = row["duration_s"]
        dur_str  = f"{int(dur_s//60)}m{int(dur_s%60):02d}s" if dur_s else "—"
        title_t  = row["title"][:38]
        status   = row["status"].upper()
        print(f"  {row['n']:<3}  {title_t:<38}  {size_str:>7}  {dur_str:>6}  {status}")
        if row["error"]:
            print(f"       ↳ {row['error']}")

    complete = sum(1 for r in summary_rows if r["status"] == "complete")
    failed_n = sum(1 for r in summary_rows if r["status"] == "failed")
    print(f"\n  {complete} complete  ·  {failed_n} failed")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Dev Life with Uche — Batch Scheduler"
    )
    parser.add_argument(
        "--batch", type=int, required=True,
        help="Number of unprocessed topics to run from content_calendar.json"
    )
    args = parser.parse_args()

    if args.batch < 1:
        print("ERROR: --batch must be >= 1", file=sys.stderr)
        sys.exit(1)

    try:
        run_batch(args.batch)
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
