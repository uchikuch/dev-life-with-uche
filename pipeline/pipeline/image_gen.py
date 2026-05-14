"""
Stage 3: Image Generation via Google Gemini

Generates cartoon illustrations for each script section using
Gemini's image generation with a character reference sheet
for consistent character identity.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types

import config

# ---------------------------------------------------------------------------
# Gemini settings
# ---------------------------------------------------------------------------

MODEL = config.IMAGEN_MODEL
MAX_CONCURRENT = config.MAX_CONCURRENT_IMAGE_REQUESTS

_client = genai.Client(api_key=config.GOOGLE_API_KEY)
_character_ref: bytes | None = None


def _get_character_ref() -> bytes:
    global _character_ref
    if _character_ref is None:
        ref_path = config.CHARACTER_REF_PATH
        if not ref_path.exists():
            raise FileNotFoundError(
                f"Character reference sheet not found: {ref_path}\n"
                "This file is required for consistent character identity."
            )
        _character_ref = ref_path.read_bytes()
    return _character_ref


# ---------------------------------------------------------------------------
# Single image generation
# ---------------------------------------------------------------------------

def generate_image(prompt: str, output_path: Path,
                   aspect_ratio: str = "16:9") -> Path:
    """Generate a single image via Gemini with character reference."""
    char_ref = _get_character_ref()

    response = _client.models.generate_content(
        model=MODEL,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_bytes(data=char_ref, mime_type="image/png"),
                    types.Part.from_text(text=prompt),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            output_path.write_bytes(part.inline_data.data)
            return output_path

    raise RuntimeError(f"No image returned for prompt: {prompt[:80]}...")


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run(job_dir: Path) -> Path:
    """
    Run Stage 3: generate images from visual_prompts.json.

    Generates images concurrently (up to MAX_CONCURRENT),
    saves to job_dir/images/.
    """
    vp_path = job_dir / "visual_prompts.json"
    if not vp_path.exists():
        raise FileNotFoundError(f"visual_prompts.json not found in {job_dir}")

    prompts = json.loads(vp_path.read_text())
    images_dir = job_dir / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"\n{'=' * 50}")
    print(f"Stage 3: Image Generation")
    print(f"{'=' * 50}\n")
    print(f"  Job: {job_dir.name}")
    print(f"  Images to generate: {len(prompts)}")
    print(f"  Model: {MODEL}")
    print(f"  Reference: {config.CHARACTER_REF_PATH.name}")
    print(f"  Concurrency: {MAX_CONCURRENT}\n")

    results: list[tuple[str, bool, str]] = []

    def _gen(item: dict) -> tuple[str, bool, str]:
        sid = item["section_id"]
        sub_idx = item.get("sub_index", 0)
        prompt = item["prompt"]
        out_path = images_dir / f"{sid}_{sub_idx}.png"
        try:
            generate_image(prompt, out_path)
            size_kb = out_path.stat().st_size / 1024
            return (sid, True, f"{size_kb:.0f}KB")
        except Exception as e:
            return (sid, False, str(e)[:120])

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
        futures = {pool.submit(_gen, item): item["section_id"] for item in prompts}
        for future in as_completed(futures):
            sid, ok, detail = future.result()
            tag = "OK" if ok else "FAIL"
            print(f"  [{tag}] {sid:<16} {detail}")
            results.append((sid, ok, detail))

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    print(f"\n  Generated: {passed}/{len(prompts)} images")

    if failed > 0:
        failed_ids = [sid for sid, ok, _ in results if not ok]
        print(f"  Failed: {', '.join(failed_ids)}")
        print(f"  Re-run with --stage images to retry failed images.")

    saved = sorted(images_dir.glob("*.png"))
    total_size = sum(f.stat().st_size for f in saved)
    print(f"  Total size: {total_size / (1024 * 1024):.1f}MB")
    print(f"\n  Stage 3 complete.\n")

    return job_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Image Generation (Stage 3)")
    parser.add_argument("--job", required=True, help="Path to job directory containing visual_prompts.json")
    args = parser.parse_args()

    job_dir = Path(args.job)
    if not job_dir.is_dir():
        print(f"ERROR: {job_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    try:
        run(job_dir)
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        sys.exit(1)
