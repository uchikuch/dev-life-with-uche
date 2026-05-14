"""
Stage 2: Voiceover Generation via ElevenLabs API

Generates narration audio from script.json and extracts word-level timestamps
for karaoke caption sync and image timing.

Calls ElevenLabs convert_with_timestamps per section, concatenates audio,
and builds a unified timestamps.json with both section and word boundaries.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

from elevenlabs import ElevenLabs
from elevenlabs.types import VoiceSettings

import config

# ---------------------------------------------------------------------------
# ElevenLabs settings from spec
# ---------------------------------------------------------------------------

VOICE_ID = config.ELEVENLABS_VOICE_ID
MODEL_ID = "eleven_turbo_v2_5"
OUTPUT_FORMAT = "mp3_44100_128"
VOICE_SETTINGS = VoiceSettings(
    stability=0.65,
    similarity_boost=0.80,
    style=0.20,
    use_speaker_boost=True,
)

PAUSE_TRAIL = " . . . "
SPEED = 1.2


def _speed_up_audio(audio_bytes: bytes, speed: float, tmp_dir: Path) -> bytes:
    """Speed up audio using FFmpeg atempo filter (preserves pitch)."""
    in_path = tmp_dir / "_speed_in.mp3"
    out_path = tmp_dir / "_speed_out.mp3"
    in_path.write_bytes(audio_bytes)
    cmd = [
        "ffmpeg", "-y", "-i", str(in_path),
        "-filter:a", f"atempo={speed}",
        "-b:a", "128k", "-v", "error",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    result = out_path.read_bytes()
    in_path.unlink(missing_ok=True)
    out_path.unlink(missing_ok=True)
    return result


def _get_audio_duration(audio_bytes: bytes, tmp_path: Path) -> float:
    """Get actual duration of MP3 audio via ffprobe."""
    tmp_path.write_bytes(audio_bytes)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(tmp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# Character-to-word aggregation
# ---------------------------------------------------------------------------

def _chars_to_words(
    characters: list[str],
    start_times: list[float],
    end_times: list[float],
) -> list[dict]:
    """Aggregate character-level timestamps into word-level timestamps."""
    words = []
    current_word_chars = []
    word_start = None

    for i, char in enumerate(characters):
        if char.strip() == "" or char == "\n":
            # Whitespace or newline: flush current word
            if current_word_chars:
                word_text = "".join(current_word_chars).strip()
                if word_text:
                    words.append({
                        "word": word_text,
                        "start": round(word_start, 3),
                        "end": round(end_times[i - 1], 3),
                    })
                current_word_chars = []
                word_start = None
        else:
            if word_start is None:
                word_start = start_times[i]
            current_word_chars.append(char)

    # Flush last word
    if current_word_chars:
        word_text = "".join(current_word_chars).strip()
        if word_text:
            words.append({
                "word": word_text,
                "start": round(word_start, 3),
                "end": round(end_times[len(characters) - 1], 3),
            })

    return words


# ---------------------------------------------------------------------------
# Fallback: estimate timestamps at 140 WPM
# ---------------------------------------------------------------------------

def _estimate_word_timestamps(text: str, offset: float) -> list[dict]:
    """Fallback: estimate word timestamps at 140 words per minute."""
    raw_words = text.split()
    seconds_per_word = 60.0 / 140.0
    words = []
    t = offset
    for w in raw_words:
        words.append({
            "word": w,
            "start": round(t, 3),
            "end": round(t + seconds_per_word, 3),
        })
        t += seconds_per_word
    return words


# ---------------------------------------------------------------------------
# Section generation
# ---------------------------------------------------------------------------

def generate_section_audio(
    client: ElevenLabs,
    text: str,
    previous_text: str | None = None,
    next_text: str | None = None,
) -> tuple[bytes, list[dict]]:
    """
    Generate audio for one script section.

    Returns:
        (mp3_bytes, word_timestamps) where timestamps are relative to this section.
    """
    resp = client.text_to_speech.convert_with_timestamps(
        voice_id=VOICE_ID,
        text=text,
        model_id=MODEL_ID,
        output_format=OUTPUT_FORMAT,
        voice_settings=VOICE_SETTINGS,
        previous_text=previous_text,
        next_text=next_text,
    )

    audio_bytes = base64.b64decode(resp.audio_base_64)

    # Extract word timestamps from character alignment
    alignment = resp.alignment
    if alignment and alignment.characters:
        words = _chars_to_words(
            alignment.characters,
            alignment.character_start_times_seconds,
            alignment.character_end_times_seconds,
        )
    else:
        print("    (using estimated timestamps — alignment unavailable)")
        words = _estimate_word_timestamps(text, 0.0)

    return audio_bytes, words


# ---------------------------------------------------------------------------
# Full pipeline: generate all sections, concatenate, build timestamps
# ---------------------------------------------------------------------------

def run(job_dir: Path) -> Path:
    """
    Run Stage 2: generate voiceover from script.json.

    Generates audio per section, concatenates into narration.mp3,
    and writes timestamps.json with section and word-level timing.

    Returns:
        Path to the job directory.
    """
    script_path = job_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"script.json not found in {job_dir}")

    script = json.loads(script_path.read_text())
    sections = script["sections"]

    print(f"\n{'=' * 50}")
    print(f"Stage 2: Voiceover Generation")
    print(f"{'=' * 50}\n")
    print(f"  Job: {job_dir.name}")
    print(f"  Sections: {len(sections)}")
    speed_note = f" | Speed: {SPEED}x" if SPEED != 1.0 else ""
    print(f"  Voice: {VOICE_ID} | Model: {MODEL_ID}{speed_note}\n")

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    all_audio_chunks: list[bytes] = []
    all_words: list[dict] = []
    section_boundaries: list[dict] = []
    cumulative_offset = 0.0
    probe_tmp = job_dir / "_probe_tmp.mp3"

    for i, section in enumerate(sections):
        sid = section["id"]
        text = section["text"]
        word_count = len(text.split())

        # Trailing pause text for natural breaks between sections
        has_pause = i < len(sections) - 1
        if has_pause:
            text = text.rstrip() + PAUSE_TRAIL

        # Context for voice continuity
        prev_text = sections[i - 1]["text"][-200:] if i > 0 else None
        next_text = sections[i + 1]["text"][:200] if i < len(sections) - 1 else None

        print(f"  [{i + 1}/{len(sections)}] {sid} ({word_count} words)...", end=" ", flush=True)

        audio_bytes, words = generate_section_audio(
            client, text,
            previous_text=prev_text,
            next_text=next_text,
        )

        # Filter punctuation-only words from trailing pause
        words = [w for w in words if w["word"].replace('.', '').strip()]

        # Speed up audio and scale timestamps
        if SPEED != 1.0:
            audio_bytes = _speed_up_audio(audio_bytes, SPEED, job_dir)
            for w in words:
                w["start"] = round(w["start"] / SPEED, 3)
                w["end"] = round(w["end"] / SPEED, 3)

        # Use actual audio duration to account for trailing pause
        section_duration = _get_audio_duration(audio_bytes, probe_tmp)

        # Record section boundary
        section_boundaries.append({
            "id": sid,
            "start": round(cumulative_offset, 3),
            "end": round(cumulative_offset + section_duration, 3),
        })

        # Offset words to absolute timeline
        for w in words:
            all_words.append({
                "word": w["word"],
                "start": round(w["start"] + cumulative_offset, 3),
                "end": round(w["end"] + cumulative_offset, 3),
            })

        all_audio_chunks.append(audio_bytes)
        cumulative_offset += section_duration

        size_kb = len(audio_bytes) / 1024
        pause_note = " (+pause)" if has_pause else ""
        print(f"{section_duration:.1f}s, {size_kb:.0f}KB{pause_note}")

    probe_tmp.unlink(missing_ok=True)

    # Concatenate audio via FFmpeg for clean MP3 stream
    narration_path = job_dir / "narration.mp3"
    concat_dir = job_dir / "_concat_tmp"
    concat_dir.mkdir(exist_ok=True)
    concat_list = concat_dir / "list.txt"
    for idx, chunk in enumerate(all_audio_chunks):
        chunk_path = concat_dir / f"{idx:03d}.mp3"
        chunk_path.write_bytes(chunk)
    concat_list.write_text(
        "\n".join(f"file '{idx:03d}.mp3'" for idx in range(len(all_audio_chunks)))
    )
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-v", "error",
        str(narration_path),
    ]
    subprocess.run(concat_cmd, capture_output=True, check=True, timeout=120)
    shutil.rmtree(concat_dir)

    total_duration = cumulative_offset
    file_size = narration_path.stat().st_size

    # Write timestamps
    timestamps = {
        "sections": section_boundaries,
        "words": all_words,
        "total_duration": round(total_duration, 3),
    }
    ts_path = job_dir / "timestamps.json"
    ts_path.write_text(json.dumps(timestamps, indent=2, ensure_ascii=False))

    print(f"\n  Saved: {narration_path.name} ({file_size / (1024 * 1024):.1f}MB)")
    print(f"  Saved: {ts_path.name}")
    print(f"  Total duration: {total_duration:.1f}s ({total_duration / 60:.1f}min)")
    print(f"  Word timestamps: {len(all_words)}")
    print(f"  Section boundaries: {len(section_boundaries)}")
    print(f"\n  Stage 2 complete.\n")

    return job_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Voiceover Generation (Stage 2)")
    parser.add_argument("--job", required=True, help="Path to job directory containing script.json")
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
