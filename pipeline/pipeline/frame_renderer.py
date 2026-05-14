"""
Unified frame renderer: Ken Burns + Particles + Captions in Pillow.

Renders each frame as a composite of three layers:
  1. Ken Burns cropped/scaled image
  2. Particle overlay (deterministic, direction-aware)
  3. Karaoke caption overlay (word-highlight)

Output is piped directly to FFmpeg for encoding.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys
from pathlib import Path

from noise import pnoise2

from PIL import Image, ImageDraw, ImageFont

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDTH = 1920
HEIGHT = 1080
FPS = 30

# Caption style
FONT_SIZE = 58
LINE_MAX_CHARS = 38
DEFAULT_COLOUR = (255, 255, 255, 255)
HIGHLIGHT_COLOUR = (254, 219, 44, 255)      # golden yellow #FEDB2C
STROKE_COLOUR = (39, 3, 99, 255)            # dark purple #270363
STROKE_WIDTH = 4
BAR_PADDING_X = 40
BAR_PADDING_Y = 16
CAPTION_Y = HEIGHT - 120

# Particle config
PARTICLE_SEED = 42
PARTICLE_FADE_IN = 45        # frames to fade in at birth
PARTICLE_FADE_OUT = 60       # frames to fade out before death
PARTICLE_LIFETIME_MIN = 180  # 6 s at 30 fps
PARTICLE_LIFETIME_MAX = 540  # 18 s at 30 fps
PARTICLE_DEAD_MIN = 30       # min frames invisible before respawn
PARTICLE_DEAD_MAX = 150      # max frames invisible before respawn

PARTICLE_LAYERS = [
    {"count": 15, "radius": 2,  "opacity_min": 0.10, "opacity_max": 0.18},
    {"count": 10, "radius": 5,  "opacity_min": 0.15, "opacity_max": 0.25},
    {"count": 6,  "radius": 9,  "opacity_min": 0.08, "opacity_max": 0.14},
    {"count": 3,  "radius": 14, "opacity_min": 0.05, "opacity_max": 0.09},
]

NOISE_TIME_SCALE = 0.008   # frame -> noise coordinate
NOISE_VX_MIN = 0.2         # px/frame, always positive (left-to-right)
NOISE_VX_MAX = 1.4
NOISE_VY_MIN = -1.2        # px/frame, free vertical
NOISE_VY_MAX = 1.2

# Noise-driven variation offsets and scales
NOISE_SIZE_OFFSET = 200     # seed offset for size noise field
NOISE_SIZE_SCALE = 0.005    # frame -> noise coord (slow)
NOISE_SIZE_Y = 0.7          # index spacing in noise space
NOISE_SIZE_MIN = 0.6        # multiplier range on base radius
NOISE_SIZE_MAX = 1.4

NOISE_OPACITY_OFFSET = 400
NOISE_OPACITY_SCALE = 0.003  # very slow (~3-4s min-to-max)
NOISE_OPACITY_Y = 0.9

NOISE_COLOUR_OFFSET = 600
NOISE_COLOUR_SCALE = 0.004
NOISE_COLOUR_Y = 1.1

# Colour endpoints: cool white -> neutral -> warm gold
COLOUR_COOL = (240, 244, 255)    # #F0F4FF
COLOUR_NEUTRAL = (255, 255, 255) # #FFFFFF
COLOUR_WARM = (255, 248, 231)    # #FFF8E7

# Font — Futura Condensed ExtraBold preferred, fallback to system bold fonts
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


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Particle system
# ---------------------------------------------------------------------------

class ParticleSystem:
    """4-layer Perlin-noise-driven particle system. Left-to-right dominant."""

    def _gen_props(self, pid: int, gen: int) -> tuple[int, int, float, float]:
        """Deterministic per-generation properties (lifetime, respawn_delay, spawn_x, spawn_y)."""
        base = self.seed + pid * 13337 + gen * 1000003
        lifetime = random.Random(base + 1).randint(PARTICLE_LIFETIME_MIN, PARTICLE_LIFETIME_MAX)
        respawn_delay = random.Random(base + 2).randint(PARTICLE_DEAD_MIN, PARTICLE_DEAD_MAX)
        spawn_x = random.Random(base + 3).uniform(0, WIDTH)
        spawn_y = random.Random(base + 4).uniform(0, HEIGHT)
        return lifetime, respawn_delay, spawn_x, spawn_y

    def __init__(self, seed: int = PARTICLE_SEED):
        self.seed = seed
        rng = random.Random(seed)
        self.particles = []
        pid = 0
        for layer_cfg in PARTICLE_LAYERS:
            for _ in range(layer_cfg["count"]):
                # Unique noise seed per particle (large prime spacing to avoid correlation)
                noise_seed = seed + pid * 5471
                # Stagger initial life stage: each particle starts at a random point
                # within its gen-0 lifetime so they don't all die at the same time.
                lifetime_0, _, _, _ = self._gen_props(pid, 0)
                birth_offset = random.Random(seed + pid * 7331 + 88888).randint(0, lifetime_0 - 1)
                self.particles.append({
                    "pid": pid,
                    "radius": layer_cfg["radius"],
                    "opacity_min": layer_cfg["opacity_min"],
                    "opacity_max": layer_cfg["opacity_max"],
                    "noise_seed": noise_seed,
                    "noise_y_coord": pid * 0.5,  # unique y-axis slice in noise space
                    "initial_x": rng.uniform(0, WIDTH),
                    "initial_y": rng.uniform(0, HEIGHT),
                    "sine_phase": rng.uniform(0, 2 * math.pi),
                    "birth_offset": birth_offset,
                })
                pid += 1

    def _sample_velocity(self, p: dict, frame: int) -> tuple[float, float]:
        """Sample Perlin noise to get (vx, vy) for this particle at this frame."""
        t = frame * NOISE_TIME_SCALE
        ny = p["noise_y_coord"]
        ns = p["noise_seed"]

        # pnoise2 returns roughly -1..1; clamp to be safe
        nx_raw = max(-1.0, min(1.0, pnoise2(ns + t, ny, octaves=3)))
        ny_raw = max(-1.0, min(1.0, pnoise2(ns + t + 100, ny, octaves=3)))

        # Map to velocity ranges
        vx = _lerp(NOISE_VX_MIN, NOISE_VX_MAX, (nx_raw + 1) / 2)
        vy = _lerp(NOISE_VY_MIN, NOISE_VY_MAX, (ny_raw + 1) / 2)
        return vx, vy

    def render(self, frame_num: int, direction: str = "falling") -> Image.Image:
        """Render particle overlay. Direction param kept for API compat."""
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        for p in self.particles:
            step = 4
            pid = p["pid"]
            birth_offset = p["birth_offset"]

            # Simulate from the birth of gen 0 (world frame -birth_offset) to frame_num.
            # During dead periods position is frozen; respawn jumps to a new random location.
            gen = 0
            gen_lifetime, gen_respawn_delay, _, _ = self._gen_props(pid, gen)
            cum_x = p["initial_x"]
            cum_y = p["initial_y"]
            life_age = 0    # frames alive in current generation
            dead_age = 0    # frames spent dead waiting for respawn
            is_dead = False

            f = -birth_offset
            while f <= frame_num:
                end = min(f + step, frame_num + 1)
                chunk = end - f

                if is_dead:
                    dead_age += chunk
                    if dead_age >= gen_respawn_delay:
                        gen += 1
                        gen_lifetime, gen_respawn_delay, new_x, new_y = self._gen_props(pid, gen)
                        cum_x = new_x
                        cum_y = new_y
                        life_age = 0
                        dead_age = 0
                        is_dead = False
                else:
                    vx, vy = self._sample_velocity(p, f)
                    cum_x += vx * chunk
                    cum_y += vy * chunk
                    life_age += chunk
                    if life_age >= gen_lifetime:
                        is_dead = True
                        dead_age = 0

                f = end

            # Dead particles are invisible — skip rendering
            if is_dead:
                continue

            x = cum_x % WIDTH
            y = cum_y % HEIGHT

            ns = p["noise_seed"]

            # --- Size noise: slow variation 0.6x-1.4x of base radius ---
            size_raw = pnoise2(ns + NOISE_SIZE_OFFSET + frame_num * NOISE_SIZE_SCALE,
                               pid * NOISE_SIZE_Y, octaves=2)
            size_raw = max(-1.0, min(1.0, size_raw))
            size_mult = _lerp(NOISE_SIZE_MIN, NOISE_SIZE_MAX, (size_raw + 1) / 2)
            r = max(1, round(p["radius"] * size_mult))

            # --- Opacity noise: very slow drift within layer range ---
            op_raw = pnoise2(ns + NOISE_OPACITY_OFFSET + frame_num * NOISE_OPACITY_SCALE,
                             pid * NOISE_OPACITY_Y, octaves=2)
            op_raw = max(-1.0, min(1.0, op_raw))
            opacity = _lerp(p["opacity_min"], p["opacity_max"], (op_raw + 1) / 2)

            # Lifetime fade multiplier — multiplied on top of noise-driven opacity.
            # Fade in over first PARTICLE_FADE_IN frames, fade out over last PARTICLE_FADE_OUT.
            if life_age < PARTICLE_FADE_IN:
                lifetime_mult = life_age / PARTICLE_FADE_IN
            elif gen_lifetime - life_age < PARTICLE_FADE_OUT:
                lifetime_mult = max(0.0, (gen_lifetime - life_age) / PARTICLE_FADE_OUT)
            else:
                lifetime_mult = 1.0
            opacity *= lifetime_mult

            alpha = int(255 * max(0.0, min(1.0, opacity)))
            if alpha <= 0:
                continue

            # --- Colour noise: subtle cool-white / neutral / warm-gold shift ---
            col_raw = pnoise2(ns + NOISE_COLOUR_OFFSET + frame_num * NOISE_COLOUR_SCALE,
                              pid * NOISE_COLOUR_Y, octaves=2)
            col_raw = max(-1.0, min(1.0, col_raw))
            col_t = (col_raw + 1) / 2  # 0..1
            if col_t < 0.5:
                # cool -> neutral
                t2 = col_t * 2
                cr = int(_lerp(COLOUR_COOL[0], COLOUR_NEUTRAL[0], t2))
                cg = int(_lerp(COLOUR_COOL[1], COLOUR_NEUTRAL[1], t2))
                cb = int(_lerp(COLOUR_COOL[2], COLOUR_NEUTRAL[2], t2))
            else:
                # neutral -> warm
                t2 = (col_t - 0.5) * 2
                cr = int(_lerp(COLOUR_NEUTRAL[0], COLOUR_WARM[0], t2))
                cg = int(_lerp(COLOUR_NEUTRAL[1], COLOUR_WARM[1], t2))
                cb = int(_lerp(COLOUR_NEUTRAL[2], COLOUR_WARM[2], t2))

            ix, iy = int(x), int(y)
            draw.ellipse([ix - r, iy - r, ix + r, iy + r], fill=(cr, cg, cb, alpha))

        return overlay


# ---------------------------------------------------------------------------
# Caption system
# ---------------------------------------------------------------------------

class CaptionRenderer:
    """Word-highlight karaoke captions from timestamps."""

    def __init__(self, words: list[dict], font: ImageFont.FreeTypeFont):
        self.font = font
        self.lines = self._build_lines(words)

    def _build_lines(self, words: list[dict]) -> list[dict]:
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
            })

        return lines

    def _find_active_line(self, t: float) -> dict | None:
        for line in self.lines:
            if line["start"] <= t <= line["end"] + 0.1:
                return line
        return None

    def _find_highlighted_index(self, line: dict, t: float) -> int:
        for i, w in enumerate(line["words"]):
            if w["start"] <= t <= w["end"]:
                return i
            if t < w["start"]:
                return i
        return len(line["words"]) - 1

    def render(self, t: float) -> Image.Image:
        """Render caption overlay at time t."""
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        line = self._find_active_line(t)

        if line is None:
            return overlay

        draw = ImageDraw.Draw(overlay)
        words = line["words"]
        highlight_idx = self._find_highlighted_index(line, t)

        # Measure full line to centre
        full_text = " ".join(w["word"] for w in words)
        bbox = self.font.getbbox(full_text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Draw words
        x = (WIDTH - text_width) // 2
        y = CAPTION_Y - text_height

        for i, w in enumerate(words):
            word_text = w["word"]
            if i < len(words) - 1:
                word_text += " "

            colour = HIGHLIGHT_COLOUR if i == highlight_idx else DEFAULT_COLOUR

            draw.text(
                (x, y), word_text, font=self.font, fill=colour,
                stroke_width=STROKE_WIDTH, stroke_fill=STROKE_COLOUR,
            )

            word_bbox = self.font.getbbox(word_text)
            x += word_bbox[2] - word_bbox[0]

        return overlay


# ---------------------------------------------------------------------------
# Ken Burns crop logic (from kenburns.py)
# ---------------------------------------------------------------------------

def _prepare_source(image_path: Path) -> tuple[Image.Image, int, int]:
    """Load and scale source image to 1.12x output size for subtle Ken Burns."""
    src = Image.open(image_path).convert("RGB")
    src_w = int(WIDTH * 1.12)
    src_h = int(HEIGHT * 1.12)
    src = src.resize((src_w, src_h), Image.LANCZOS)
    return src, src_w, src_h


def _crop_frame(
    src: Image.Image, src_w: int, src_h: int,
    frame_idx: int, num_frames: int,
    motion: str, zoom_amount: float,
) -> Image.Image:
    """Compute and extract the Ken Burns crop for one frame."""
    t = frame_idx / max(num_frames - 1, 1)
    cx = src_w / 2.0
    cy = src_h / 2.0
    base_w = float(WIDTH)
    base_h = float(HEIGHT)

    if motion == "zoom_in":
        zoom = _lerp(1.0, 1.0 + zoom_amount, t)
        crop_w = base_w / zoom
        crop_h = base_h / zoom
        off_x = cx - crop_w / 2.0
        off_y = cy - crop_h / 2.0
    elif motion == "zoom_out":
        zoom = _lerp(1.0 + zoom_amount, 1.0, t)
        crop_w = base_w / zoom
        crop_h = base_h / zoom
        off_x = cx - crop_w / 2.0
        off_y = cy - crop_h / 2.0
    elif motion == "pan_left_right":
        zoom = 1.02
        crop_w = base_w / zoom
        crop_h = base_h / zoom
        max_off_x = src_w - crop_w
        off_x = _lerp(0, max_off_x, t)
        off_y = cy - crop_h / 2.0
    elif motion == "zoom_out_in":
        if t < 0.5:
            zoom = _lerp(1.0 + zoom_amount / 2, 1.0, t / 0.5)
        else:
            zoom = _lerp(1.0, 1.0 + zoom_amount / 2, (t - 0.5) / 0.5)
        crop_w = base_w / zoom
        crop_h = base_h / zoom
        off_x = cx - crop_w / 2.0
        off_y = cy - crop_h / 2.0
    else:  # still
        crop_w = base_w
        crop_h = base_h
        off_x = cx - crop_w / 2.0
        off_y = cy - crop_h / 2.0

    # 5% safe zone: crop window stays within inner 90% of source
    margin_x = int(src_w * 0.05)
    margin_y = int(src_h * 0.05)

    x1 = max(margin_x, int(round(off_x)))
    y1 = max(margin_y, int(round(off_y)))
    x2 = min(src_w - margin_x, x1 + int(round(crop_w)))
    y2 = min(src_h - margin_y, y1 + int(round(crop_h)))

    frame = src.crop((x1, y1, x2, y2))
    return frame.resize((WIDTH, HEIGHT), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Unified renderer
# ---------------------------------------------------------------------------

def render_section(
    image_path: Path,
    output_path: Path,
    duration: float,
    motion: str = "zoom_in",
    zoom_amount: float = 0.08,
    particle_direction: str = "falling",
    words: list[dict] | None = None,
    time_offset: float = 0.0,
    narration_path: Path | None = None,
    fade_to_black: float = 0.0,
) -> Path:
    """
    Render a single section clip with Ken Burns + particles + captions.

    Args:
        image_path: Source image.
        output_path: Output mp4 path.
        duration: Section duration in seconds.
        motion: Ken Burns motion type.
        zoom_amount: Zoom range.
        particle_direction: "falling", "rising", or "suspended".
        words: Word timestamp dicts for captions (absolute times).
        time_offset: Start time of this section in the full video timeline.
        narration_path: Full narration mp3. If provided, the section's audio
                        is trimmed and muxed into the output.
        fade_to_black: Duration in seconds to fade to black at the end (0 = no fade).
    """
    num_frames = int(duration * FPS)
    src, src_w, src_h = _prepare_source(image_path)

    particles = ParticleSystem()
    font = _load_font()
    captions = CaptionRenderer(words or [], font) if words else None

    # If audio requested, render video to a temp file first, then mux
    if narration_path:
        video_tmp = output_path.with_suffix(".tmp.mp4")
    else:
        video_tmp = output_path

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
        str(video_tmp),
    ]
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for i in range(num_frames):
            # Absolute time in the full video
            abs_t = time_offset + (i / FPS)

            # Layer 1: Ken Burns
            frame = _crop_frame(src, src_w, src_h, i, num_frames, motion, zoom_amount)
            frame = frame.convert("RGBA")

            # Layer 2: Particles
            p_overlay = particles.render(i, particle_direction)
            frame = Image.alpha_composite(frame, p_overlay)

            # Layer 3: Captions
            if captions:
                c_overlay = captions.render(abs_t)
                frame = Image.alpha_composite(frame, c_overlay)

            # Layer 4: Fade to black
            if fade_to_black > 0:
                local_t = i / FPS
                fade_start = duration - fade_to_black
                if local_t >= fade_start:
                    alpha = 1.0 - ((local_t - fade_start) / fade_to_black)
                    alpha = max(0.0, min(1.0, alpha))
                    black = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
                    frame = Image.blend(black, frame, alpha)

            encoder.stdin.write(frame.convert("RGB").tobytes())

    finally:
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"FFmpeg encode failed: {err[-300:]}")

    # Mux audio if narration provided
    if narration_path:
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", str(video_tmp),
            "-ss", str(time_offset),
            "-t", str(duration),
            "-i", str(narration_path),
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-v", "error",
            str(output_path),
        ]
        result = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=60)
        video_tmp.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio mux failed: {result.stderr[-300:]}")

    return output_path


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Section Frame Renderer")
    parser.add_argument("--job", required=True, help="Job directory path")
    parser.add_argument("--section", default="hook", help="Section ID to render")
    parser.add_argument("--output", default=None, help="Output filename (default: {section}_test.mp4)")
    args = parser.parse_args()

    job_dir = Path(args.job)
    ts = json.loads((job_dir / "timestamps.json").read_text())

    # Find section timing
    sec_info = None
    for s in ts["sections"]:
        if s["id"] == args.section:
            sec_info = s
            break
    if sec_info is None:
        print(f"Section '{args.section}' not found", file=sys.stderr)
        sys.exit(1)

    duration = sec_info["end"] - sec_info["start"]
    time_offset = sec_info["start"]

    # Get words within this section's time range
    section_words = [
        w for w in ts["words"]
        if w["start"] >= sec_info["start"] - 0.5 and w["end"] <= sec_info["end"] + 0.5
    ]

    # Motion and particle direction per section
    SECTION_MOTION = {
        "hook": ("zoom_in", "falling"),
        "problem_frame": ("pan_left_right", "falling"),
        "scripture": ("still", "suspended"),
        "saint": ("zoom_out", "suspended"),
        "synthesis": ("zoom_out_in", "rising"),
        "closing": ("still", "rising"),
    }

    motion, p_dir = SECTION_MOTION.get(args.section, ("still", "suspended"))
    image_path = job_dir / "images" / f"{args.section}.png"
    output_name = args.output or f"{args.section}_test.mp4"
    output_path = job_dir / output_name

    print(f"Rendering {args.section}: {duration:.1f}s, motion={motion}, particles={p_dir}")
    print(f"  Words in range: {len(section_words)}")
    print(f"  Time offset: {time_offset:.1f}s")

    narration_path = job_dir / "narration.mp3"
    if not narration_path.exists():
        narration_path = None

    render_section(
        image_path=image_path,
        output_path=output_path,
        duration=duration,
        motion=motion,
        zoom_amount=0.08,
        particle_direction=p_dir,
        words=section_words,
        time_offset=time_offset,
        narration_path=narration_path,
    )

    size = output_path.stat().st_size / (1024 * 1024)
    print(f"  Output: {output_path} ({size:.1f}MB)")
