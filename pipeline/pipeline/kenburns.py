"""
Ken Burns effect renderer using Pillow.

Pre-renders each frame by cropping a progressively changing window from
an oversized source image, then resizes to 1920x1080. Output is piped
directly to FFmpeg for encoding.

No FFmpeg filters involved — pure Python crop/resize for stability.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

WIDTH = 1920
HEIGHT = 1080
FPS = 30


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation from a to b at fraction t (0.0 to 1.0)."""
    return a + (b - a) * t


def render_kenburns(
    image_path: Path,
    output_path: Path,
    duration: float,
    motion: str = "zoom_in",
    zoom_amount: float = 0.08,
) -> Path:
    """
    Render Ken Burns effect to an mp4 file.

    Args:
        image_path: Source image (any resolution, will be scaled up if needed).
        output_path: Output .mp4 path.
        duration: Duration in seconds.
        motion: One of "zoom_in", "zoom_out", "pan_left_right",
                "zoom_out_in", "still".
        zoom_amount: Total zoom range (0.08 = 8%).

    Returns:
        output_path
    """
    num_frames = int(duration * FPS)
    src = Image.open(image_path).convert("RGB")

    # Scale source image so the largest crop window fits with room to spare.
    # We need the source to be large enough that even at zoom=1.0 (widest crop)
    # we have full coverage. Scale to at least 1.5x output size.
    scale_factor = 1.5
    src_w = int(WIDTH * scale_factor)
    src_h = int(HEIGHT * scale_factor)
    if src.width < src_w or src.height < src_h:
        src = src.resize((src_w, src_h), Image.LANCZOS)
    else:
        # Scale to exactly our working size for consistency
        src = src.resize((src_w, src_h), Image.LANCZOS)

    # Centre of the source image
    cx = src_w / 2.0
    cy = src_h / 2.0

    # Define crop window animation based on motion type.
    # crop_w/crop_h define the window extracted from source, then resized to 1920x1080.
    # A smaller crop window = more zoomed in.
    # A larger crop window = more zoomed out.

    # Base crop at zoom=1.0 (no zoom): extract exactly 1920x1080 from centre
    base_w = float(WIDTH)
    base_h = float(HEIGHT)

    # Start FFmpeg encoder reading raw RGB frames from pipe
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-v", "error",
        str(output_path),
    ]
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for i in range(num_frames):
            t = i / max(num_frames - 1, 1)  # 0.0 to 1.0

            if motion == "zoom_in":
                # Start wide, end tight (smaller crop = more zoomed)
                zoom = _lerp(1.0, 1.0 + zoom_amount, t)
                crop_w = base_w / zoom
                crop_h = base_h / zoom
                off_x = cx - crop_w / 2.0
                off_y = cy - crop_h / 2.0

            elif motion == "zoom_out":
                # Start tight, end wide
                zoom = _lerp(1.0 + zoom_amount, 1.0, t)
                crop_w = base_w / zoom
                crop_h = base_h / zoom
                off_x = cx - crop_w / 2.0
                off_y = cy - crop_h / 2.0

            elif motion == "pan_left_right":
                # Fixed zoom, pan horizontally
                zoom = 1.04  # slight zoom for headroom
                crop_w = base_w / zoom
                crop_h = base_h / zoom
                # Pan from left to right across available headroom
                max_off_x = src_w - crop_w
                off_x = _lerp(0, max_off_x, t)
                off_y = cy - crop_h / 2.0

            elif motion == "zoom_out_in":
                # Zoom out to midpoint, then back in
                if t < 0.5:
                    zoom = _lerp(1.0 + zoom_amount / 2, 1.0, t / 0.5)
                else:
                    zoom = _lerp(1.0, 1.0 + zoom_amount / 2, (t - 0.5) / 0.5)
                crop_w = base_w / zoom
                crop_h = base_h / zoom
                off_x = cx - crop_w / 2.0
                off_y = cy - crop_h / 2.0

            elif motion == "still":
                crop_w = base_w
                crop_h = base_h
                off_x = cx - crop_w / 2.0
                off_y = cy - crop_h / 2.0

            else:
                raise ValueError(f"Unknown motion type: {motion}")

            # Integer pixel coords for clean crop — no subpixel jitter
            x1 = int(round(off_x))
            y1 = int(round(off_y))
            x2 = x1 + int(round(crop_w))
            y2 = y1 + int(round(crop_h))

            # Clamp to source bounds
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(src_w, x2)
            y2 = min(src_h, y2)

            frame = src.crop((x1, y1, x2, y2))
            frame = frame.resize((WIDTH, HEIGHT), Image.LANCZOS)
            encoder.stdin.write(frame.tobytes())

    finally:
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"FFmpeg encode failed: {err[-300:]}")

    return output_path


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ken Burns renderer")
    parser.add_argument("--image", required=True, help="Source image path")
    parser.add_argument("--output", required=True, help="Output mp4 path")
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--motion", default="zoom_in",
                        choices=["zoom_in", "zoom_out", "pan_left_right", "zoom_out_in", "still"])
    parser.add_argument("--zoom", type=float, default=0.08)
    args = parser.parse_args()

    render_kenburns(
        Path(args.image), Path(args.output),
        args.duration, args.motion, args.zoom,
    )
    size = Path(args.output).stat().st_size / (1024 * 1024)
    print(f"Output: {args.output} ({size:.1f}MB)")
