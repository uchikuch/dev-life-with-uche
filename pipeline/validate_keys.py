#!/usr/bin/env python3
"""
Dev Life with Uche — API Key Validation Script

Tests each external dependency independently and reports pass/fail.
Run this before building any pipeline modules.

Usage:
    python validate_keys.py
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Load .env from project root
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Colour helpers (no dependency on rich for this simple script)
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

results: list[tuple[str, bool, str]] = []


def report(name: str, passed: bool, detail: str = ""):
    tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    detail_str = f"  ({detail})" if detail else ""
    print(f"  {name:<24} {tag}{detail_str}")
    results.append((name, passed, detail))


# ---------------------------------------------------------------------------
# 1. Claude API (Anthropic)
# ---------------------------------------------------------------------------

def test_claude():
    try:
        import anthropic

        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            report("Claude API", False, "ANTHROPIC_API_KEY not set in .env")
            return

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=30,
            messages=[{"role": "user", "content": "Say hello in exactly five words."}],
        )
        text = resp.content[0].text.strip()
        report("Claude API", True, f'response: "{text[:60]}"')
    except Exception as e:
        report("Claude API", False, str(e)[:120])


# ---------------------------------------------------------------------------
# 2. ElevenLabs API
# ---------------------------------------------------------------------------

def test_elevenlabs():
    try:
        from elevenlabs import ElevenLabs

        key = os.getenv("ELEVENLABS_API_KEY", "")
        if not key:
            report("ElevenLabs API", False, "ELEVENLABS_API_KEY not set in .env")
            return

        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
        client = ElevenLabs(api_key=key)

        audio_gen = client.text_to_speech.convert(
            voice_id=voice_id,
            text="Testing voice connection.",
            model_id="eleven_turbo_v2_5",
        )

        # audio_gen is a generator; consume it to confirm it works
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            for chunk in audio_gen:
                tmp.write(chunk)
            tmp.close()
            size = os.path.getsize(tmp.name)
            report("ElevenLabs API", size > 0, f"audio bytes: {size}")
        finally:
            os.unlink(tmp.name)

    except Exception as e:
        report("ElevenLabs API", False, str(e)[:120])


# ---------------------------------------------------------------------------
# 3. Gemini Image API
# ---------------------------------------------------------------------------

def test_gemini_image():
    try:
        from google import genai
        from google.genai import types

        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            report("Gemini Image API", False, "GOOGLE_API_KEY not set in .env")
            return

        client = genai.Client(api_key=key)

        response = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt="A cartoon developer sitting at a desk with multiple monitors, flat illustration style, purple and dark tones",
            config=types.GenerateImagesConfig(
                number_of_images=1,
            ),
        )

        if response.generated_images and len(response.generated_images) > 0:
            img_data = response.generated_images[0].image.image_bytes
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            try:
                tmp.write(img_data)
                tmp.close()
                size = os.path.getsize(tmp.name)
                report("Gemini Image API", size > 0, f"image bytes: {size}")
            finally:
                os.unlink(tmp.name)
        else:
            report("Gemini Image API", False, "No images returned")

    except Exception as e:
        report("Gemini Image API", False, str(e)[:120])


# ---------------------------------------------------------------------------
# 4. Pexels API
# ---------------------------------------------------------------------------

def test_pexels():
    try:
        import requests

        key = os.getenv("PEXELS_API_KEY", "")
        if not key:
            report("Pexels API (optional)", True, "skipped — no key set")
            return
            return

        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={"query": "candle", "per_page": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        total = data.get("total_results", 0)
        report("Pexels API", total > 0, f"results found: {total}")

    except Exception as e:
        report("Pexels API", False, str(e)[:120])


# ---------------------------------------------------------------------------
# 5. FFmpeg
# ---------------------------------------------------------------------------

def test_ffmpeg():
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.split("\n")[0]
            # Extract version like "ffmpeg version 7.1.1"
            version = first_line.split("version")[1].strip().split(" ")[0] if "version" in first_line else "unknown"
            report("FFmpeg", True, f"version {version}")
        else:
            report("FFmpeg", False, "ffmpeg returned non-zero exit code")
    except FileNotFoundError:
        report("FFmpeg", False, "not installed — run: brew install ffmpeg")
    except Exception as e:
        report("FFmpeg", False, str(e)[:120])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print(f"{BOLD}Dev Life with Uche — API Validation{RESET}")
    print(f"{'=' * 50}")
    print()

    test_claude()
    test_elevenlabs()
    test_gemini_image()
    test_pexels()
    test_ffmpeg()

    print()
    print(f"{'=' * 50}")

    passed = sum(1 for _, p, _ in results if p)
    total = len(results)

    if passed == total:
        print(f"{GREEN}{BOLD}All {total} checks passed. Proceed to pipeline build.{RESET}")
    else:
        failed = [name for name, p, _ in results if not p]
        print(f"{RED}{BOLD}{total - passed} of {total} checks failed: {', '.join(failed)}{RESET}")
        print(f"Fix the failing keys in .env and re-run this script.")
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
