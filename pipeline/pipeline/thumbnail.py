"""
Dev Life with Uche — Thumbnail Generator

Generates a 1280x720 YouTube thumbnail with:
  - Dedicated Gemini-generated close-up of the main character (right side)
  - Bold uppercase text with dark purple stroke (left side)
  - One accent word highlighted in golden yellow
"""
from __future__ import annotations

import json
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
import io

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDTH = 1280
HEIGHT = 720

TEXT_FILL = (254, 254, 254, 255)           # #FEFEFE white
ACCENT_FILL = (254, 219, 44, 255)         # #FEDB2C golden yellow
STROKE_FILL = (26, 10, 62, 255)           # #1a0a3e dark purple stroke
STROKE_WIDTH = 8
SHADOW_FILL = (13, 2, 33, 230)            # #0D0221 very dark purple extrusion
GLOW_COLOR = (123, 63, 228, 102)          # #7B3FE4 at 40% opacity
DARK_BG = (20, 20, 26)

MAIN_FONT_SIZE = 216
TEXT_X_MARGIN = 40
TEXT_Y_RATIO = 0.25
CHAR_SIDE_RATIO = 0.48

FONT_PATHS = [
    str(config.ASSETS_DIR / "fonts" / "BebasNeue-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

THUMBNAIL_PROMPT_SCENE = (
    "Generate an image based on the character in the first reference image, "
    "using the style and mood from the second reference image. "
    "Detailed cel-shaded cartoon illustration with realistic lighting, 16:9 cinematic composition. "
    "Semi-realistic art style with clean outlines, volumetric shading, ambient occlusion in creases and folds, "
    "soft rim lighting on character edges, subtle highlights on skin, fabric texture visible on clothing. "
    "Rich, detailed background with warm ambient lighting and subtle purple neon glow on character edges. "
    "Cinematic composition with depth of field. High-end animation quality, NOT flat illustration. "
    "Style reference: high-end animation like Boondocks or Into the Spider-Verse. "
    "NOT flat vector art, NOT clip art, NOT corporate illustration. "
    "Of the main character, a male character with masculine jawline, visible goatee and mustache, "
    "wearing a plain neon purple hoodie with no text, no logo, no graphics on clothing, "
    "matte black cap. {scene} "
    "The scene should show ACTION or CONFLICT, not a character standing still or posing. "
    "The character should be engaged in the scene, not looking at the camera. "
    "Keep the top 20-25% of the frame relatively simple (sky, ceiling, empty wall, open space) "
    "so text can overlay cleanly without obscuring the scene."
)

THUMBNAIL_PROMPT_FALLBACK = (
    "Generate an image based on the character in the first reference image, "
    "using the style and mood from the second reference image. "
    "Detailed cel-shaded cartoon illustration with realistic lighting, 16:9 cinematic composition. "
    "Semi-realistic art style with clean outlines, volumetric shading, ambient occlusion in creases and folds, "
    "soft rim lighting on character edges, subtle highlights on skin, fabric texture visible on clothing. "
    "Rich, detailed background with warm ambient lighting and subtle purple neon glow on character edges. "
    "Cinematic composition with depth of field. High-end animation quality, NOT flat illustration. "
    "Style reference: high-end animation like Boondocks or Into the Spider-Verse. "
    "NOT flat vector art, NOT clip art, NOT corporate illustration. "
    "Of the main character, a male character with masculine jawline, visible goatee and mustache, "
    "wearing a plain neon purple hoodie with no text, no logo, no graphics on clothing, "
    "matte black cap. {expression}. "
    "{background} "
    "Background has depth of field with soft blur on distant elements, less saturated than the character. "
    "{framing} Character positioned on the right third of frame. "
    "Character is the sharpest, most vivid and saturated element in the frame. "
    "Large empty space on the left side of the frame for text overlay."
)

EXPRESSION_MAP = {
    "raised_eyebrow": "One eyebrow raised, slight head tilt, arms crossed",
    "deadpan_stare": "Deadpan stare directly ahead, arms crossed",
    "slight_smirk": "Slight knowing smirk, one hand on chin",
    "mild_frustration": "Mild frustration, slight eye roll, hands raised in exasperation",
    "tired_amused": "Tired but amused, slight bags under eyes, head resting on one hand",
    "neutral": "Neutral confident expression, arms crossed",
    "thinking": "Thoughtful expression, one hand on chin, looking slightly upward",
    "facepalm": "Head in one hand, eyes closed, tired expression",
    "pointing": "Confident expression, pointing directly at camera with one finger",
    "shrug": "Exaggerated shrug, both palms up, slight smirk",
    "leaning_back": "Leaning back in chair, hands behind head, knowing look",
}

BACKGROUND_MAP = {
    "default": (
        "Rich detailed tech office background slightly out of focus: "
        "desk with laptop and monitors showing lines of code, colorful sticky notes on wall, "
        "coffee mug on desk, city skyline visible through window at night with glowing lights, "
        "warm ambient purple-blue neon-tinted lighting, bookshelf with tech books, "
        "small potted plant, whiteboard with diagrams in far background."
    ),
    "late_night": (
        "Dark moody office at night, multiple monitors glowing with code, "
        "energy drink cans on desk, city lights through window, "
        "dim purple-blue ambient lighting, messy sticky notes on monitor bezels."
    ),
    "whiteboard": (
        "Office with large whiteboard covered in diagrams, crossed-out items, and arrows, "
        "standing desk with laptop nearby, warm overhead lighting, "
        "coffee cup on desk, printed documents scattered."
    ),
    "conference": (
        "Modern glass-walled conference room, projector screen with charts, "
        "long table with laptops, city view through windows, "
        "warm neutral lighting, whiteboard with sprint notes."
    ),
    "casual": (
        "Warm coffee shop or lounge setting, laptop on table, "
        "plants and exposed brick wall in background, warm golden lighting, "
        "bookshelf with tech books, cozy ambient atmosphere."
    ),
}

FRAMING_MAP = {
    "close_up": "Medium close-up shot from chest up.",
    "waist_up": "Medium shot from waist up, showing hands and gestures.",
    "full_body": "Full body shot showing white sneakers, character standing.",
    "three_quarter": "Three-quarter shot from thighs up, dynamic angle.",
}

PILLAR_STYLE = {
    "career_navigation": {"expression": "thinking", "background": "casual", "framing": "waist_up"},
    "agile_dysfunction": {"expression": "mild_frustration", "background": "whiteboard", "framing": "close_up"},
    "tech_debt": {"expression": "facepalm", "background": "late_night", "framing": "close_up"},
    "engineering_culture": {"expression": "raised_eyebrow", "background": "conference", "framing": "waist_up"},
    "leadership": {"expression": "pointing", "background": "default", "framing": "three_quarter"},
    "developer_productivity": {"expression": "leaning_back", "background": "default", "framing": "waist_up"},
    "startup_life": {"expression": "tired_amused", "background": "late_night", "framing": "close_up"},
}

_client = genai.Client(api_key=config.GOOGLE_API_KEY)


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        path = Path(p)
        if path.exists():
            if p.endswith(".ttc"):
                return ImageFont.truetype(p, size, index=4)
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# Thumbnail image generation via Gemini
# ---------------------------------------------------------------------------

def _generate_thumbnail_image(
    job_dir: Path,
    expression: str = "raised_eyebrow",
    background: str = "default",
    framing: str = "close_up",
    thumbnail_scene: str = None,
) -> Path:
    """Generate a dedicated thumbnail image via Gemini with character reference."""
    if thumbnail_scene:
        prompt = THUMBNAIL_PROMPT_SCENE.format(scene=thumbnail_scene)
        print(f"  Generating thumbnail image via Gemini...")
        print(f"  Scene: {thumbnail_scene[:80]}...")
    else:
        expr_text = EXPRESSION_MAP.get(expression, EXPRESSION_MAP["raised_eyebrow"])
        bg_text = BACKGROUND_MAP.get(background, BACKGROUND_MAP["default"])
        frame_text = FRAMING_MAP.get(framing, FRAMING_MAP["close_up"])
        prompt = THUMBNAIL_PROMPT_FALLBACK.format(expression=expr_text, background=bg_text, framing=frame_text)
        print(f"  Generating thumbnail image via Gemini...")
        print(f"  Expression: {expression} (fallback, no thumbnail_scene)")

    char_ref = config.CHARACTER_REF_PATH.read_bytes()

    parts = [
        types.Part.from_bytes(data=char_ref, mime_type="image/png"),
    ]
    style_ref_path = config.CHANNEL_ASSETS_DIR / "poster.png"
    if style_ref_path.exists():
        parts.append(types.Part.from_bytes(data=style_ref_path.read_bytes(), mime_type="image/png"))
        print(f"  Style reference: {style_ref_path.name}")
    parts.append(types.Part.from_text(text=prompt))

    response = _client.models.generate_content(
        model=config.IMAGEN_MODEL,
        contents=[types.Content(parts=parts)],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            out_path = job_dir / "images" / "thumbnail_bg.png"
            out_path.write_bytes(part.inline_data.data)
            print(f"  Thumbnail image saved: {out_path.name} ({len(part.inline_data.data) // 1024}KB)")
            return out_path

    raise RuntimeError("No thumbnail image returned from Gemini")


# ---------------------------------------------------------------------------
# Text rendering with stroke
# ---------------------------------------------------------------------------

def _draw_title(img: Image.Image, words: list[str], accent_words: list[str],
                font: ImageFont.FreeTypeFont, x: int, y: int) -> Image.Image:
    """Render title with layered effects: glow, shadow extrusion, stroke, fill."""
    accent_upper = {w.upper() for w in accent_words}

    word_widths = []
    for word in words:
        bbox = font.getbbox(word + " ")
        word_widths.append((word, bbox[2] - bbox[0]))

    # Layer 1: Neon glow (blurred purple behind everything)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    cx = x
    for word, ww in word_widths:
        glow_draw.text((cx, y), word + " ", font=font, fill=GLOW_COLOR)
        cx += ww
    glow = glow.filter(ImageFilter.GaussianBlur(radius=15))
    img = Image.alpha_composite(img, glow)

    # Layer 2: Shadow/extrusion (5 offsets for 3D depth)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    for step in range(1, 6):
        cx = x + step
        cy = y + step * 2
        for word, ww in word_widths:
            shadow_draw.text((cx, cy), word + " ", font=font, fill=SHADOW_FILL)
            cx += ww
    img = Image.alpha_composite(img, shadow)

    # Layer 3: Main text with thick stroke and fill
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = x
    for word, ww in word_widths:
        fill = ACCENT_FILL if word.upper() in accent_upper else TEXT_FILL
        draw.text(
            (cx, y), word + " ", font=font,
            fill=fill,
            stroke_width=STROKE_WIDTH,
            stroke_fill=STROKE_FILL,
        )
        cx += ww

    return Image.alpha_composite(img, overlay)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_thumbnail(job_dir: Path, title: str = None,
                       accent_words: list[str] = None) -> Path:
    """Generate thumbnail.png for a job."""
    script_path = job_dir / "script.json"
    script = json.loads(script_path.read_text())

    if title is None:
        if "thumbnail_title" not in script:
            raise ValueError(
                "script.json is missing 'thumbnail_title'. "
                "Set a short, punchy title (4-6 words)."
            )
        title = script["thumbnail_title"].upper()
    else:
        title = title.upper()

    if accent_words is None:
        accent_words = script.get("thumbnail_accent_words", [])
        if not accent_words:
            accent_words = [title.split()[-1]]

    content_pillar = script.get("content_pillar", "").lower().replace(" ", "_")
    pillar_defaults = PILLAR_STYLE.get(content_pillar, {})

    expression = script.get("thumbnail_expression", pillar_defaults.get("expression", "raised_eyebrow"))
    background = pillar_defaults.get("background", "default")
    framing = pillar_defaults.get("framing", "close_up")
    thumbnail_scene = script.get("thumbnail_scene")

    # -- Generate dedicated thumbnail image --
    bg_path = job_dir / "images" / "thumbnail_bg.png"
    if not bg_path.exists():
        bg_path = _generate_thumbnail_image(job_dir, expression, background, framing, thumbnail_scene=thumbnail_scene)
    else:
        print(f"  Using existing thumbnail image: {bg_path.name}")

    bg = Image.open(bg_path).convert("RGB")
    bg = ImageOps.fit(bg, (WIDTH, HEIGHT), Image.LANCZOS)

    # -- Slight darken for text contrast --
    img = bg.convert("RGBA")
    dark = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 80))
    img = Image.alpha_composite(img, dark)

    # -- Title text in top 25% of frame --
    title_words = title.split()
    text_max_w = WIDTH - TEXT_X_MARGIN * 2

    effective_size = MAIN_FONT_SIZE
    main_font = _load_font(effective_size)
    while effective_size > 40:
        main_font = _load_font(effective_size)
        total_w = sum(main_font.getbbox(w + " ")[2] for w in title_words)
        if total_w <= text_max_w:
            break
        effective_size -= 2

    line_height = main_font.getbbox("Ag")[3] - main_font.getbbox("Ag")[1]
    text_y = int(HEIGHT * 0.04)
    img = _draw_title(
        img, title_words, accent_words, main_font,
        TEXT_X_MARGIN, text_y,
    )

    # -- Save --
    output = job_dir / "thumbnail.png"
    img.convert("RGB").save(output, quality=95)
    size_kb = output.stat().st_size / 1024
    print(f"  Output: {output}")
    print(f"  Size: {size_kb:.0f}KB")

    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Thumbnail Generator")
    parser.add_argument("--job", required=True, help="Path to job directory")
    parser.add_argument("--title", default=None, help="Override main title text")
    parser.add_argument("--accent", nargs="*", default=None, help="Accent words for yellow highlight")
    parser.add_argument("--regen", action="store_true", help="Force regenerate thumbnail image")
    args = parser.parse_args()

    job = Path(args.job)
    if not job.is_absolute():
        job = config.ROOT_DIR / job

    if args.regen:
        bg_path = job / "images" / "thumbnail_bg.png"
        bg_path.unlink(missing_ok=True)

    generate_thumbnail(job, title=args.title, accent_words=args.accent)
