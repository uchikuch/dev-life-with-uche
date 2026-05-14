"""
The Narrow Path — Logo Generator

Generates three logo PNGs using Pillow:
  - logo_dark.png       800x800, gold on #1A1A1A
  - logo_transparent.png 800x800, gold on transparent
  - logo_icon.png       400x400, archway + glow only, transparent
"""

import io
import math
import os
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOLD = (212, 175, 55, 255)          # #D4AF37
DARK_BG = (26, 26, 26, 255)        # #1A1A1A
GLOW_CENTER = (255, 248, 231)       # #FFF8E7
STROKE = 3

LOGO_SIZE = 800
ICON_SIZE = 400

SCRIPT_DIR = Path(__file__).parent
FONT_DIR = SCRIPT_DIR / "fonts"


# ---------------------------------------------------------------------------
# Font setup
# ---------------------------------------------------------------------------

def _get_cinzel_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Cinzel Bold, downloading from Google Fonts if needed."""
    font_path = FONT_DIR / "Cinzel-Bold.ttf"

    if not font_path.exists():
        print("  Downloading Cinzel Bold font...", end=" ", flush=True)
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        # Direct TTF from Google Fonts GitHub repo
        url = ("https://raw.githubusercontent.com/google/fonts/main/"
               "ofl/cinzel/Cinzel%5Bwght%5D.ttf")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=30)
            with open(font_path, "wb") as f:
                f.write(resp.read())
            print("OK")
        except Exception as e:
            print(f"FAIL ({e})")
            # Try static Bold variant
            url2 = ("https://raw.githubusercontent.com/google/fonts/main/"
                    "ofl/cinzel/static/Cinzel-Bold.ttf")
            try:
                req = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=30)
                with open(font_path, "wb") as f:
                    f.write(resp.read())
                print("  Fallback download OK")
            except Exception:
                pass

    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)

    # Fallback to system serif
    fallbacks = [
        "/System/Library/Fonts/Times.ttc",
        "/System/Library/Fonts/Palatino.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ]
    for p in fallbacks:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Archway drawing
# ---------------------------------------------------------------------------

def _draw_archway(draw: ImageDraw.Draw, cx: float, base_y: float,
                  pillar_w: float, pillar_h: float, arch_w: float,
                  stroke: int = STROKE, color: tuple = GOLD):
    """
    Draw a Roman archway: two pillars + semicircular arch.

    cx: horizontal centre
    base_y: bottom of pillars
    pillar_w: width of each pillar
    pillar_h: height of pillars (from base up)
    arch_w: inner width between pillars
    """
    # Pillar tops
    top_y = base_y - pillar_h

    # Pillar x positions (single vertical lines)
    lp_x = cx - arch_w / 2 - pillar_w / 2
    rp_x = cx + arch_w / 2 + pillar_w / 2

    # Left pillar — single vertical line
    draw.line([(lp_x, top_y), (lp_x, base_y)], fill=color, width=stroke)

    # Right pillar — single vertical line
    draw.line([(rp_x, top_y), (rp_x, base_y)], fill=color, width=stroke)

    # Semicircular arch connecting pillar tops
    arch_left = lp_x
    arch_right = rp_x
    arch_diameter = arch_right - arch_left
    arch_top = top_y - arch_diameter / 2

    # Draw arch as an arc (top half of ellipse)
    draw.arc(
        [arch_left, arch_top, arch_right, top_y + (top_y - arch_top)],
        start=180, end=360,
        fill=color, width=stroke,
    )


def _get_archway_params(size: int) -> dict:
    """Compute archway geometry for a given canvas size."""
    # Archway occupies the upper ~60% of the canvas
    pillar_w = size * 0.055
    arch_w = size * 0.30
    pillar_h = size * 0.32
    base_y = size * 0.62
    cx = size / 2

    return {
        "cx": cx, "base_y": base_y,
        "pillar_w": pillar_w, "pillar_h": pillar_h,
        "arch_w": arch_w,
    }


# ---------------------------------------------------------------------------
# Glow effect
# ---------------------------------------------------------------------------

def _draw_glow(img: Image.Image, params: dict, size: int):
    """
    Render a soft radial golden glow inside the archway opening.
    """
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    cx = params["cx"]
    base_y = params["base_y"]
    pillar_h = params["pillar_h"]
    arch_w = params["arch_w"]
    pillar_w = params["pillar_w"]

    top_y = base_y - pillar_h
    arch_full_w = arch_w + 2 * pillar_w
    arch_center_y = top_y - arch_full_w * 0.18  # slightly below arch peak

    # Glow centre: top third of the archway opening
    opening_top = arch_center_y
    opening_bottom = base_y
    opening_height = opening_bottom - opening_top
    glow_cx = cx
    glow_cy = opening_top + opening_height * 0.35  # 35% from top
    glow_rx = arch_w * 0.20  # small concentrated core
    glow_ry = opening_height * 0.22  # vertically tight

    # Draw radial gradient pixel by pixel on a smaller buffer for speed
    scale = 4
    sm_w = size // scale
    sm_h = size // scale
    sm_glow = Image.new("RGBA", (sm_w, sm_h), (0, 0, 0, 0))
    pixels = sm_glow.load()

    for y in range(sm_h):
        for x in range(sm_w):
            # Map back to full coords
            fx = x * scale
            fy = y * scale

            # Normalised distance from glow centre (elliptical)
            dx = (fx - glow_cx) / glow_rx
            dy = (fy - glow_cy) / glow_ry
            dist = math.sqrt(dx * dx + dy * dy)

            if dist < 2.5:
                # Concentrated bright core with extended soft falloff
                if dist < 1.0:
                    # Hot core: 0.75 peak
                    alpha = (1.0 - dist) ** 1.5 * 0.75
                else:
                    # Soft outer glow fading to transparent
                    t = (dist - 1.0) / 1.5
                    alpha = (1.0 - t) ** 3 * 0.18
                a = int(min(1.0, alpha) * 255)
                pixels[x, y] = (GLOW_CENTER[0], GLOW_CENTER[1], GLOW_CENTER[2], a)

    # Scale up with bilinear for smoothness
    sm_glow = sm_glow.resize((size, size), Image.BILINEAR)
    # Extra blur for softness
    sm_glow = sm_glow.filter(ImageFilter.GaussianBlur(radius=size * 0.02))

    img.paste(Image.alpha_composite(
        Image.new("RGBA", (size, size), (0, 0, 0, 0)), sm_glow
    ), (0, 0), sm_glow)


# ---------------------------------------------------------------------------
# Wordmark
# ---------------------------------------------------------------------------

def _draw_wordmark(draw: ImageDraw.Draw, cx: float, top_y: float,
                   size: int, color: tuple = GOLD):
    """Draw 'THE NARROW' / 'PATH' centred below the archway."""
    line1_size = int(size * 0.052)
    line2_size = int(size * 0.072)

    font1 = _get_cinzel_font(line1_size)
    font2 = _get_cinzel_font(line2_size)

    line1 = "T H E   N A R R O W"
    line2 = "P A T H"

    # Line 1
    bbox1 = font1.getbbox(line1)
    w1 = bbox1[2] - bbox1[0]
    x1 = cx - w1 / 2
    draw.text((x1, top_y), line1, font=font1, fill=color)

    # Line 2
    line_gap = size * 0.02
    y2 = top_y + (bbox1[3] - bbox1[1]) + line_gap
    bbox2 = font2.getbbox(line2)
    w2 = bbox2[2] - bbox2[0]
    x2 = cx - w2 / 2
    draw.text((x2, y2), line2, font=font2, fill=color)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_all():
    out_dir = SCRIPT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pre-load font
    _ = _get_cinzel_font(40)

    # ---- logo_dark.png (800x800, gold on dark) ----
    print("  Generating logo_dark.png...", end=" ", flush=True)
    img = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), DARK_BG)
    params = _get_archway_params(LOGO_SIZE)

    _draw_glow(img, params, LOGO_SIZE)

    draw = ImageDraw.Draw(img)
    _draw_archway(draw, **params)

    wordmark_y = params["base_y"] + LOGO_SIZE * 0.06
    _draw_wordmark(draw, LOGO_SIZE / 2, wordmark_y, LOGO_SIZE)

    img.save(out_dir / "logo_dark.png")
    print("OK")

    # ---- logo_transparent.png (800x800, gold on transparent) ----
    print("  Generating logo_transparent.png...", end=" ", flush=True)
    img_t = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    params = _get_archway_params(LOGO_SIZE)

    _draw_glow(img_t, params, LOGO_SIZE)

    draw_t = ImageDraw.Draw(img_t)
    _draw_archway(draw_t, **params)
    _draw_wordmark(draw_t, LOGO_SIZE / 2, wordmark_y, LOGO_SIZE)

    img_t.save(out_dir / "logo_transparent.png")
    print("OK")

    # ---- logo_icon.png (400x400, arch + glow only, transparent) ----
    print("  Generating logo_icon.png...", end=" ", flush=True)
    img_i = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    # Centre the archway vertically for icon (no wordmark)
    params_i = _get_archway_params(ICON_SIZE)
    # Shift down slightly so arch is centred
    params_i["base_y"] = ICON_SIZE * 0.72

    _draw_glow(img_i, params_i, ICON_SIZE)

    draw_i = ImageDraw.Draw(img_i)
    _draw_archway(draw_i, **params_i)

    img_i.save(out_dir / "logo_icon.png")
    print("OK")

    print(f"\n  Output directory: {out_dir}")
    for name in ["logo_dark.png", "logo_transparent.png", "logo_icon.png"]:
        p = out_dir / name
        sz = p.stat().st_size / 1024
        print(f"    {name}: {sz:.0f}KB")


if __name__ == "__main__":
    generate_all()
