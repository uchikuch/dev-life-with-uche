"""
Dev Life with Uche — End Screen Generator

Generates a 1920x1080 YouTube end screen image with:
  - Dark background with purple gradient accent
  - Channel name and tagline
  - Two YouTube end screen element placeholders
  - Schedule text at bottom
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDTH = 1920
HEIGHT = 1080

DARK_BG = (20, 20, 26, 255)             # #14141A
PURPLE = (123, 63, 228, 255)            # #7B3FE4
CYAN = (78, 205, 196, 255)              # #4ECDC4
WHITE = (255, 255, 255, 255)
PLACEHOLDER_FILL = (36, 36, 42, 255)    # #24242A
PLACEHOLDER_BORDER = (123, 63, 228, 255)

PLACEHOLDER_W = 380
PLACEHOLDER_H = 210
PLACEHOLDER_RADIUS = 12
PLACEHOLDER_GAP = 60

FONT_DIR = config.ASSETS_DIR / "logo" / "fonts"
OUTPUT_PATH = config.ASSETS_DIR / "endscreen.png"

NUM_PARTICLES = 35
PARTICLE_SEED = 42

FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    cinzel = FONT_DIR / "Cinzel-Bold.ttf"
    if cinzel.exists():
        return ImageFont.truetype(str(cinzel), size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Particle layer
# ---------------------------------------------------------------------------

def _draw_particles(draw: ImageDraw.Draw):
    rng = random.Random(PARTICLE_SEED)
    for _ in range(NUM_PARTICLES):
        x = rng.randint(0, WIDTH - 1)
        y = rng.randint(0, HEIGHT - 1)
        r = rng.choice([2, 3, 3, 4])
        alpha = rng.randint(20, 50)
        draw.ellipse([x - r, y - r, x + r, y + r],
                     fill=(255, 255, 255, alpha))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_endscreen() -> Path:
    img = Image.new("RGBA", (WIDTH, HEIGHT), DARK_BG)
    draw = ImageDraw.Draw(img)

    _draw_particles(draw)

    # Subtle purple gradient bar at top
    for y in range(4):
        alpha = int(180 * (1 - y / 4))
        draw.line([(0, y), (WIDTH, y)],
                  fill=(PURPLE[0], PURPLE[1], PURPLE[2], alpha))

    # Channel name
    title_font = _load_font(64)
    channel_name = "DEV LIFE WITH UCHE"
    bbox = title_font.getbbox(channel_name)
    tw = bbox[2] - bbox[0]
    title_x = (WIDTH - tw) // 2
    title_y = int(HEIGHT * 0.18)
    draw.text((title_x, title_y), channel_name, font=title_font, fill=WHITE)

    # Tagline
    tagline_font = _load_font(24)
    tagline = "The realities of dev life. No filter."
    tbbox = tagline_font.getbbox(tagline)
    ttw = tbbox[2] - tbbox[0]
    tagline_x = (WIDTH - ttw) // 2
    tagline_y = title_y + (bbox[3] - bbox[1]) + 20
    draw.text((tagline_x, tagline_y), tagline, font=tagline_font, fill=CYAN)

    # Accent line under tagline
    line_w = 200
    line_y = tagline_y + (tbbox[3] - tbbox[1]) + 20
    draw.line(
        [(WIDTH // 2 - line_w // 2, line_y), (WIDTH // 2 + line_w // 2, line_y)],
        fill=PURPLE, width=2,
    )

    # Two placeholders — WATCH NEXT and SUBSCRIBE
    placeholders_y = line_y + 50
    total_w = PLACEHOLDER_W * 2 + PLACEHOLDER_GAP
    left_x = (WIDTH - total_w) // 2
    right_x = left_x + PLACEHOLDER_W + PLACEHOLDER_GAP

    label_font = _load_font(18)

    for px, label in [(left_x, "WATCH NEXT"), (right_x, "SUBSCRIBE")]:
        draw.rounded_rectangle(
            [px, placeholders_y, px + PLACEHOLDER_W, placeholders_y + PLACEHOLDER_H],
            radius=PLACEHOLDER_RADIUS,
            fill=PLACEHOLDER_FILL,
            outline=PLACEHOLDER_BORDER,
            width=1,
        )
        lbl_spaced = "   ".join(label)
        lbbox = label_font.getbbox(lbl_spaced)
        lw = lbbox[2] - lbbox[0]
        lh = lbbox[3] - lbbox[1]
        lx = px + (PLACEHOLDER_W - lw) // 2
        ly = placeholders_y + (PLACEHOLDER_H - lh) // 2
        draw.text((lx, ly), lbl_spaced, font=label_font, fill=PURPLE)

    # Schedule text
    schedule_font = _load_font(16)
    schedule = "New videos every Monday, Wednesday & Friday"
    sbbox = schedule_font.getbbox(schedule)
    sw = sbbox[2] - sbbox[0]
    schedule_x = (WIDTH - sw) // 2
    schedule_y = placeholders_y + PLACEHOLDER_H + 35
    draw.text((schedule_x, schedule_y), schedule, font=schedule_font, fill=WHITE)

    # Save
    img.convert("RGB").save(OUTPUT_PATH, quality=95)
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"  Output: {OUTPUT_PATH}")
    print(f"  Size: {size_kb:.0f}KB")

    return OUTPUT_PATH


if __name__ == "__main__":
    generate_endscreen()
