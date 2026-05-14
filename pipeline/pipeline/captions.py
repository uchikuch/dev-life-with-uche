"""
Caption renderer using Pillow.

Generates word-highlight karaoke captions by piping video frames through
Pillow for text overlay, avoiding disk I/O for individual frames.

Usage:
    python -m pipeline.captions --job <job_dir> [--sample <seconds>]
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

# ---------------------------------------------------------------------------
# Caption style
# ---------------------------------------------------------------------------

FONT_SIZE = 58
LINE_MAX_CHARS = 38
DEFAULT_COLOUR = (255, 255, 255, 255)       # white
HIGHLIGHT_COLOUR = (254, 219, 44, 255)      # golden yellow #FEDB2C
STROKE_COLOUR = (39, 3, 99, 255)            # dark purple #270363
STROKE_WIDTH = 4
BAR_PADDING_X = 40
BAR_PADDING_Y = 16
CAPTION_Y = 1080 - 120                      # lower third
WIDTH = 1920
HEIGHT = 1080
FPS = 30

# Font — Futura Condensed ExtraBold preferred
FONT_PATHS = [
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 4),
    ("/System/Library/Fonts/Supplemental/Impact.ttf", None),
    ("/Library/Fonts/Impact.ttf", None),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", None),
]


def _load_font() -> ImageFont.FreeTypeFont:
    for p, idx in FONT_PATHS:
        if Path(p).exists():
            if idx is not None:
                return ImageFont.truetype(p, FONT_SIZE, index=idx)
            return ImageFont.truetype(p, FONT_SIZE)
    return ImageFont.load_default(size=FONT_SIZE)


# ---------------------------------------------------------------------------
# Build caption lines from word timestamps
# ---------------------------------------------------------------------------

def _build_lines(words: list[dict]) -> list[dict]:
    """
    Group words into display lines of max LINE_MAX_CHARS characters.

    Returns list of:
        {"words": [word_dicts], "start": float, "end": float, "text": str}
    """
    lines = []
    current_words = []
    current_len = 0

    for w in words:
        word_len = len(w["word"]) + 1
        if current_len + word_len > LINE_MAX_CHARS and current_words:
            lines.append({
                "words": current_words,
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": " ".join(wd["word"] for wd in current_words),
            })
            current_words = [w]
            current_len = word_len
        else:
            current_words.append(w)
            current_len += word_len

    if current_words:
        lines.append({
            "words": current_words,
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "text": " ".join(wd["word"] for wd in current_words),
        })

    return lines


def _find_active_line(lines: list[dict], t: float) -> dict | None:
    """Find the caption line active at time t."""
    for line in lines:
        if line["start"] <= t <= line["end"] + 0.1:
            return line
    return None


def _find_highlighted_word_index(line: dict, t: float) -> int:
    """Find which word in the line is currently being spoken."""
    for i, w in enumerate(line["words"]):
        if w["start"] <= t <= w["end"]:
            return i
        if t < w["start"]:
            # Between words — highlight the upcoming word
            return i
    return len(line["words"]) - 1


# ---------------------------------------------------------------------------
# Render a single caption overlay
# ---------------------------------------------------------------------------

def render_caption_overlay(
    font: ImageFont.FreeTypeFont,
    line: dict | None,
    t: float,
) -> Image.Image:
    """Render a transparent RGBA overlay with the caption text."""
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    if line is None:
        return overlay

    draw = ImageDraw.Draw(overlay)
    words = line["words"]
    highlight_idx = _find_highlighted_word_index(line, t)

    # Measure full line width to centre it
    full_text = " ".join(w["word"] for w in words)
    bbox = font.getbbox(full_text)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Draw words one by one, tracking x position
    x = (WIDTH - text_width) // 2
    y = CAPTION_Y - text_height

    for i, w in enumerate(words):
        word_text = w["word"]
        if i < len(words) - 1:
            word_text += " "

        colour = HIGHLIGHT_COLOUR if i == highlight_idx else DEFAULT_COLOUR

        draw.text(
            (x, y), word_text, font=font, fill=colour,
            stroke_width=STROKE_WIDTH, stroke_fill=STROKE_COLOUR,
        )

        word_bbox = font.getbbox(word_text)
        x += word_bbox[2] - word_bbox[0]

    return overlay


# ---------------------------------------------------------------------------
# Generate sample frame
# ---------------------------------------------------------------------------

def generate_sample_frame(job_dir: Path, sample_time: float = 30.0) -> Path:
    """
    Extract one frame from final_video.mp4, overlay captions, save as PNG.
    """
    ts = json.loads((job_dir / "timestamps.json").read_text())
    lines = _build_lines(ts["words"])
    font = _load_font()

    video_path = job_dir / "final_video.mp4"

    # Extract one frame with FFmpeg
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(sample_time),
        "-i", str(video_path),
        "-frames:v", "1",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr[-200:]}")

    frame = Image.frombytes("RGB", (WIDTH, HEIGHT), result.stdout)

    # Render caption overlay
    line = _find_active_line(lines, sample_time)
    caption = render_caption_overlay(font, line, sample_time)

    # Composite
    frame = frame.convert("RGBA")
    composited = Image.alpha_composite(frame, caption)

    out_path = job_dir / "caption_test.png"
    composited.convert("RGB").save(out_path, quality=95)
    print(f"  Sample frame saved: {out_path}")
    print(f"  Time: {sample_time:.1f}s")
    if line:
        idx = _find_highlighted_word_index(line, sample_time)
        print(f"  Line: \"{line['text']}\"")
        print(f"  Highlighted: \"{line['words'][idx]['word']}\"")
    else:
        print(f"  (no caption active at this time)")

    return out_path


# ---------------------------------------------------------------------------
# Full render: pipe frames through Pillow
# ---------------------------------------------------------------------------

def render_captioned_video(job_dir: Path) -> Path:
    """
    Read final_video.mp4 frame by frame via FFmpeg pipe, overlay captions
    with Pillow, pipe back to FFmpeg for encoding.
    """
    ts = json.loads((job_dir / "timestamps.json").read_text())
    lines = _build_lines(ts["words"])
    font = _load_font()

    video_path = job_dir / "final_video.mp4"
    narration_path = job_dir / "narration.mp3"
    output_path = job_dir / "final_video_captioned.mp4"
    total_duration = ts["total_duration"]

    frame_size = WIDTH * HEIGHT * 3  # RGB24

    # Probe actual video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    video_duration = float(probe_result.stdout.strip())
    total_frames = int(video_duration * FPS)

    print(f"\n  Rendering captioned video...")
    print(f"  Frames: {total_frames}")
    print(f"  Duration: {video_duration:.1f}s")

    # Decoder: video → raw RGB frames
    decode_cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-v", "error",
        "pipe:1",
    ]

    # Encoder: raw RGB frames + audio → final mp4
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-i", str(narration_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", "8M",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-v", "error",
        str(output_path),
    ]

    decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    frame_num = 0
    last_pct = -1

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            t = frame_num / FPS
            line = _find_active_line(lines, t)

            if line is not None:
                frame = Image.frombytes("RGB", (WIDTH, HEIGHT), raw)
                caption = render_caption_overlay(font, line, t)
                frame = frame.convert("RGBA")
                composited = Image.alpha_composite(frame, caption)
                raw = composited.convert("RGB").tobytes()

            encoder.stdin.write(raw)
            frame_num += 1

            pct = int(frame_num / total_frames * 100)
            if pct != last_pct and pct % 5 == 0:
                print(f"  {pct}%...", end=" ", flush=True)
                last_pct = pct

    finally:
        decoder.stdout.close()
        decoder.wait()
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"Encoder failed: {err[-300:]}")

    file_size = output_path.stat().st_size
    print(f"\n\n  Output: {output_path.name}")
    print(f"  Size: {file_size / (1024 * 1024):.1f}MB")
    print(f"  Frames rendered: {frame_num}")

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Pillow Caption Renderer")
    parser.add_argument("--job", required=True, help="Path to job directory")
    parser.add_argument("--sample", type=float, default=None, help="Generate sample frame at this time (seconds)")
    parser.add_argument("--render", action="store_true", help="Render full captioned video")
    args = parser.parse_args()

    job_dir = Path(args.job)

    if args.sample is not None:
        generate_sample_frame(job_dir, args.sample)
    elif args.render:
        render_captioned_video(job_dir)
    else:
        print("Specify --sample <seconds> or --render")
        sys.exit(1)
