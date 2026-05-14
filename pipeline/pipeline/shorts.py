"""
Dev Life with Uche — YouTube Shorts Extractor

Extracts individual listicle points from a completed long-form job and
renders standalone YouTube Shorts (9:16, 1080x1920).

Each short contains:
  - Persistent title bar (top 13%): semi-transparent dark purple with title
  - Content scenes: 2-3 portrait images with Ken Burns, karaoke captions,
    and smooth crossfades between images
  - CTA end frame (3s): channel branding

Input:  completed job dir with script.json, narration.mp3, timestamps.json
Output: shorts/short_point_N.mp4 + shorts/thumb_point_N.png per point
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

from google import genai
from google.genai import types

import config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDTH = 1080
HEIGHT = 1920
FPS = 30

CTA_DURATION = 3.0
XFADE_DURATION = 0.5
KB_ZOOM = 0.03

# Brand colours
DARK_BG = (20, 20, 26)
PURPLE = (123, 63, 228)
PURPLE_STROKE = (39, 3, 99)
HIGHLIGHT = (254, 219, 44)
CYAN = (78, 205, 196)
AMBER = (255, 184, 48)
SHADOW_FILL = (13, 2, 33, 230)

CAPTION_FONT_SIZE = 54
CTA_FONT_SIZE = 52
CAPTION_STROKE_WIDTH = 4

# Persistent title bar
TITLE_BAR_Y_OFFSET = 100               # push below iPhone Dynamic Island / notch
TITLE_BAR_HEIGHT = int(HEIGHT * 0.16)   # ~307px, top 16%
TITLE_BAR_BG = (26, 10, 62, 178)       # #1a0a3e at 70% opacity
TITLE_FONT_MAX = 42
TITLE_FONT_MIN = 24
SUPERTITLE_RATIO = 0.65                 # supertitle font ~65% of main title
TITLE_PAD = 30
TITLE_H_PAD = 10                        # horizontal safe-zone padding

FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

CAPTION_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Futura Condensed ExtraBold.otf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

# Gemini (lazy init)
_gemini: genai.Client | None = None
_char_ref: bytes | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_font(size: int, paths: list[str] | None = None) -> ImageFont.FreeTypeFont:
    for p in (paths or FONT_PATHS):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont,
               max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    current_w = 0
    for word in words:
        ww = font.getbbox(word + " ")[2] - font.getbbox(word + " ")[0]
        if current_w + ww > max_w and current:
            lines.append(" ".join(current))
            current = [word]
            current_w = ww
        else:
            current.append(word)
            current_w += ww
    if current:
        lines.append(" ".join(current))
    return lines


# ---------------------------------------------------------------------------
# Portrait image preparation
# ---------------------------------------------------------------------------

def _prepare_portrait(img_path: Path) -> Image.Image:
    """Load any-aspect image and crop/scale to 1080×1920 portrait."""
    img = Image.open(img_path).convert("RGB")
    return ImageOps.fit(img, (WIDTH, HEIGHT), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Portrait image generation via Gemini
# ---------------------------------------------------------------------------

def _get_client() -> genai.Client:
    global _gemini
    if _gemini is None:
        _gemini = genai.Client(api_key=config.GOOGLE_API_KEY)
    return _gemini


def _get_char_ref() -> bytes:
    global _char_ref
    if _char_ref is None:
        _char_ref = config.CHARACTER_REF_PATH.read_bytes()
    return _char_ref


_PORTRAIT_DIRECTIVES = (
    "9:16 vertical portrait composition with the character as the dominant "
    "focal point. The main character must be prominently visible, occupying "
    "50-60% of the vertical frame. Character positioned in the center of "
    "the frame, face and upper body clearly visible. Close-up chest-up shot, "
    "tighter vertical framing."
)


def _adapt_prompt_for_portrait(prompt: str) -> str:
    """Recompose a 16:9 prompt for 9:16 vertical portrait."""
    prompt = prompt.replace(
        "16:9 cinematic composition",
        _PORTRAIT_DIRECTIVES,
    )
    prompt = prompt.replace(
        "Of the main character",
        "Of the main character centered in the frame, face clearly visible,",
    )
    return prompt


def _validate_character_visible(img_path: Path) -> bool:
    """Check that the purple hoodie is prominently visible and centered."""
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    pixels = list(img.getdata())
    total = len(pixels)

    purple_count = 0
    purple_x_sum = 0
    for idx, (r, g, b) in enumerate(pixels):
        if 80 <= r <= 180 and g <= 120 and b >= 150:
            purple_count += 1
            px_x = idx % w
            purple_x_sum += px_x

    purple_pct = purple_count / total
    if purple_pct < 0.02:
        return False

    avg_x = purple_x_sum / purple_count if purple_count else w // 2
    x_ratio = avg_x / w
    if x_ratio < 0.10 or x_ratio > 0.90:
        return False

    return True


def _generate_portrait_images(
    point_id: str,
    visual_prompts: list[dict],
    output_dir: Path,
    count: int = 2,
) -> list[Path]:
    """Generate portrait images for one point via Gemini."""
    output_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(output_dir.glob("*.png"))
    if len(existing) >= count:
        return existing[:count]

    point_prompts = [p for p in visual_prompts if p["section_id"] == point_id]
    if not point_prompts:
        return []

    client = _get_client()
    char_ref = _get_char_ref()
    generated: list[Path] = []

    for i, item in enumerate(point_prompts[:count]):
        out_path = output_dir / f"{i}.png"
        if out_path.exists() and _validate_character_visible(out_path):
            generated.append(out_path)
            print(f"      image {i}: cached (validated)")
            continue
        elif out_path.exists():
            out_path.unlink()
            print(f"      image {i}: cached but failed validation, regenerating")

        prompt = _adapt_prompt_for_portrait(item["prompt"])
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                gen_prompt = prompt
                if attempt > 0:
                    gen_prompt = (
                        prompt + " IMPORTANT: The character in the purple "
                        "hoodie MUST be large and centered in the frame, "
                        "filling the middle of the image. Do NOT place "
                        "the character at the edge."
                    )

                response = client.models.generate_content(
                    model=config.IMAGEN_MODEL,
                    contents=[types.Content(parts=[
                        types.Part.from_bytes(
                            data=char_ref, mime_type="image/png"
                        ),
                        types.Part.from_text(text=gen_prompt),
                    ])],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )
                for part in response.candidates[0].content.parts:
                    if (part.inline_data
                            and part.inline_data.mime_type.startswith(
                                "image/")):
                        out_path.write_bytes(part.inline_data.data)
                        break
                else:
                    print(f"      image {i}: no image in response")
                    continue

                if _validate_character_visible(out_path):
                    size_kb = out_path.stat().st_size / 1024
                    print(f"      image {i}: {size_kb:.0f}KB")
                    generated.append(out_path)
                    break
                else:
                    tag = "retrying" if attempt < max_attempts - 1 else "using anyway"
                    print(f"      image {i}: character off-center, {tag}")
                    if attempt == max_attempts - 1:
                        generated.append(out_path)
            except Exception as e:
                print(f"      image {i}: FAILED ({str(e)[:80]})")
                break

    return generated


def _fallback_crop_existing(
    point_id: str, images_dir: Path, count: int = 2
) -> list[Path]:
    """Fallback: use existing 16:9 sub-scene images."""
    return sorted(images_dir.glob(f"{point_id}_*.png"))[:count]


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def _extract_audio(
    narration_path: Path, start: float, end: float, output_path: Path
):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(narration_path),
        "-ss", f"{start:.3f}",
        "-t", f"{end - start:.3f}",
        "-c:a", "aac", "-b:a", "192k",
        "-v", "error",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-200:]}")


# ---------------------------------------------------------------------------
# Title text (full label, no truncation)
# ---------------------------------------------------------------------------

def _get_title_text(section: dict) -> str:
    """Extract the complete section title from the label."""
    label = section.get("label", "")
    if label and label[0].isdigit():
        dot = label.find(".")
        if dot >= 0:
            label = label[dot + 1:].strip()
    return label or "Watch This"


def _get_point_number(section: dict) -> int:
    """Extract the point number from a section's label (e.g. '3. ...' → 3)."""
    label = section.get("label", "")
    if label and label[0].isdigit():
        dot = label.find(".")
        if dot >= 0:
            try:
                return int(label[:dot])
            except ValueError:
                pass
    sid = section.get("id", "")
    if sid.startswith("point_"):
        try:
            return int(sid.split("_")[1])
        except ValueError:
            pass
    return 0


_KEYWORD_MAP = {
    "agile": "FAKE AGILE",
    "waterfall": "FAKE AGILE",
    "sprint": "FAKE AGILE",
    "career": "CAREER MISTAKE",
    "co-founder": "CO-FOUNDER REALITY",
    "cofounder": "CO-FOUNDER REALITY",
    "startup": "STARTUP REALITY",
    "tech debt": "TECH DEBT",
    "code review": "CODE REVIEW",
    "engineering manager": "EM REALITY",
    "rewrite": "BIG REWRITE",
    "customer": "CUSTOMER REALITY",
    "user": "USER REALITY",
    "pm": "PM REALITY",
    "cto": "CTO REALITY",
    "senior engineer": "SENIOR DEV",
}


def _derive_supertitle_keyword(video_title: str) -> str:
    """Derive a short topic keyword from the video title."""
    title_lower = video_title.lower()
    for phrase, keyword in _KEYWORD_MAP.items():
        if phrase in title_lower:
            return keyword
    words = video_title.split()
    if len(words) >= 3:
        return " ".join(words[:3]).upper()
    return video_title.upper()


def _get_supertitle(video_title: str, point_num: int) -> str:
    """Build supertitle like 'FAKE AGILE — SIGN #3'."""
    keyword = _derive_supertitle_keyword(video_title)
    # Detect list format: "N signs/things/types/reasons..."
    title_lower = video_title.lower()
    label = "SIGN"
    for word in ["mistake", "thing", "type", "reason", "reality", "rule"]:
        if word in title_lower:
            label = word.upper()
            break
    return f"{keyword} — {label} #{point_num}"


# ---------------------------------------------------------------------------
# Persistent title bar (top 16% of frame, supertitle + main title)
# ---------------------------------------------------------------------------

def _render_title_bar(text: str, supertitle: str = "") -> Image.Image:
    """Pre-render the persistent title bar overlay with supertitle and main title."""
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bar_top = TITLE_BAR_Y_OFFSET
    bar_bottom = bar_top + TITLE_BAR_HEIGHT
    draw.rectangle([0, bar_top, WIDTH, bar_bottom], fill=TITLE_BAR_BG)

    max_text_w = WIDTH - (TITLE_PAD + TITLE_H_PAD) * 2

    # Main title font sizing
    font_size = TITLE_FONT_MAX
    font = _load_font(font_size, CAPTION_FONT_PATHS)
    lines = _wrap_text(text.upper(), font, max_text_w)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 8

    # Supertitle font
    super_font_size = max(int(font_size * SUPERTITLE_RATIO), 18)
    super_font = _load_font(super_font_size, CAPTION_FONT_PATHS)
    super_h = super_font.getbbox("Ag")[3] - super_font.getbbox("Ag")[1] + 6
    super_gap = 6

    max_main_h = TITLE_BAR_HEIGHT - 30 - (super_h + super_gap if supertitle else 0)

    while line_h * len(lines) > max_main_h and font_size > TITLE_FONT_MIN:
        font_size -= 2
        font = _load_font(font_size, CAPTION_FONT_PATHS)
        lines = _wrap_text(text.upper(), font, max_text_w)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 8
        super_font_size = max(int(font_size * SUPERTITLE_RATIO), 18)
        super_font = _load_font(super_font_size, CAPTION_FONT_PATHS)
        super_h = super_font.getbbox("Ag")[3] - super_font.getbbox("Ag")[1] + 6

    total_main_h = line_h * len(lines)
    total_h = total_main_h + (super_h + super_gap if supertitle else 0)
    y = bar_top + (TITLE_BAR_HEIGHT - total_h) // 2

    # Draw supertitle (golden yellow)
    if supertitle:
        sw = super_font.getbbox(supertitle)[2] - super_font.getbbox(supertitle)[0]
        draw.text(
            ((WIDTH - sw) // 2, y), supertitle, font=super_font,
            fill=(*HIGHLIGHT, 255),
            stroke_width=1,
            stroke_fill=(*PURPLE_STROKE, 180),
        )
        y += super_h + super_gap

    # Draw main title lines (white)
    for line in lines:
        lw = font.getbbox(line)[2] - font.getbbox(line)[0]
        draw.text(
            ((WIDTH - lw) // 2, y), line, font=font,
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(*PURPLE_STROKE, 200),
        )
        y += line_h

    return overlay


# ---------------------------------------------------------------------------
# CTA end frame
# ---------------------------------------------------------------------------

def _render_cta_frame() -> Image.Image:
    """1080×1920 CTA frame with channel branding."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (*DARK_BG, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 4], fill=(*PURPLE, 255))

    title_font = _load_font(48)
    channel = "DEV LIFE WITH UCHE"
    tw = title_font.getbbox(channel)[2] - title_font.getbbox(channel)[0]
    draw.text(((WIDTH - tw) // 2, HEIGHT // 2 - 120), channel,
              font=title_font, fill=(255, 255, 255, 255))

    cta_font = _load_font(CTA_FONT_SIZE)
    for i, line in enumerate(["FULL BREAKDOWN", "ON THE CHANNEL"]):
        cw = cta_font.getbbox(line)[2] - cta_font.getbbox(line)[0]
        draw.text(((WIDTH - cw) // 2, HEIGHT // 2 - 20 + i * 64), line,
                  font=cta_font, fill=(*CYAN, 255))

    sub_font = _load_font(28)
    sub = "Subscribe for more"
    sw = sub_font.getbbox(sub)[2] - sub_font.getbbox(sub)[0]
    draw.text(((WIDTH - sw) // 2, HEIGHT // 2 + 140), sub,
              font=sub_font, fill=(*AMBER, 255))
    return img


# ---------------------------------------------------------------------------
# Ken Burns (portrait)
# ---------------------------------------------------------------------------

def _ken_burns_crop(
    img: Image.Image, progress: float, motion: str = "zoom_in"
) -> Image.Image:
    if motion == "zoom_out":
        progress = 1.0 - progress
    scale = 1.0 + KB_ZOOM * progress
    w, h = img.size
    new_w, new_h = int(w / scale), int(h / scale)
    left = (w - new_w) // 2
    top = (h - new_h) // 2
    return img.crop((left, top, left + new_w, top + new_h)).resize(
        (WIDTH, HEIGHT), Image.LANCZOS
    )


# ---------------------------------------------------------------------------
# Caption renderer (purple stroke + yellow highlight)
# ---------------------------------------------------------------------------

CHUNK_MAX_CHARS = 34

class ShortsCaptionRenderer:
    def __init__(self, words: list[dict], font: ImageFont.FreeTypeFont):
        self.words = words
        self.font = font
        self.max_width = WIDTH - 100
        self.y_pos = int(HEIGHT * 0.78)
        self.chunks = self._build_chunks()

    def _build_chunks(self) -> list[dict]:
        """Pre-compute fixed word chunks. Each chunk stays on screen
        until every word in it has been spoken."""
        chunks = []
        current_words = []
        current_len = 0

        for w in self.words:
            word_len = len(w["word"]) + 1
            if current_len + word_len > CHUNK_MAX_CHARS and current_words:
                chunks.append({
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
            chunks.append({
                "words": current_words,
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
            })
        return chunks

    def _find_active_chunk(self, t: float) -> dict | None:
        for chunk in self.chunks:
            if chunk["start"] <= t <= chunk["end"] + 0.1:
                return chunk
        return None

    def _find_highlighted_index(self, chunk: dict, t: float) -> int:
        for i, w in enumerate(chunk["words"]):
            if w["start"] <= t <= w["end"]:
                return i
            if t < w["start"]:
                return i
        return len(chunk["words"]) - 1

    def render(self, t: float) -> Image.Image | None:
        chunk = self._find_active_chunk(t)
        if chunk is None:
            return None

        highlight_idx = self._find_highlighted_index(chunk, t)

        # Wrap chunk words into visual lines for rendering
        lines: list[list[tuple[dict, int]]] = []
        cur_line: list[tuple[dict, int]] = []
        cur_w = 0
        for ci, w in enumerate(chunk["words"]):
            ww = (self.font.getbbox(w["word"] + " ")[2]
                  - self.font.getbbox(w["word"] + " ")[0])
            if cur_w + ww > self.max_width and cur_line:
                lines.append(cur_line)
                cur_line = [(w, ci)]
                cur_w = ww
            else:
                cur_line.append((w, ci))
                cur_w += ww
        if cur_line:
            lines.append(cur_line)

        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        line_h = (self.font.getbbox("Ag")[3]
                  - self.font.getbbox("Ag")[1] + 14)
        total_h = line_h * len(lines) + 28
        bar_y = self.y_pos - 14

        draw.rounded_rectangle(
            [40, bar_y, WIDTH - 40, bar_y + total_h],
            radius=16, fill=(0, 0, 0, 140),
        )

        cy = self.y_pos
        for line in lines:
            total_lw = sum(
                self.font.getbbox(w["word"] + " ")[2]
                - self.font.getbbox(w["word"] + " ")[0]
                for w, _ in line
            )
            cx = (WIDTH - total_lw) // 2
            for w, ci in line:
                word_text = w["word"] + " "
                ww = (self.font.getbbox(word_text)[2]
                      - self.font.getbbox(word_text)[0])
                is_active = ci == highlight_idx
                fill = (*HIGHLIGHT, 255) if is_active else (255, 255, 255, 240)
                draw.text(
                    (cx, cy), word_text, font=self.font,
                    fill=fill,
                    stroke_width=CAPTION_STROKE_WIDTH,
                    stroke_fill=(*PURPLE_STROKE, 255),
                )
                cx += ww
            cy += line_h

        return overlay


# ---------------------------------------------------------------------------
# Short thumbnail
# ---------------------------------------------------------------------------

def _generate_thumbnail(
    portrait_path: Path, title_text: str, output_path: Path,
    supertitle: str = "",
):
    """9:16 thumbnail: portrait image with gradient + supertitle + title text."""
    img = _prepare_portrait(portrait_path).convert("RGBA")

    grad = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for y in range(HEIGHT // 2, HEIGHT):
        alpha = int(190 * (y - HEIGHT // 2) / (HEIGHT // 2))
        grad_draw.rectangle([0, y, WIDTH, y + 1], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad)

    font = _load_font(TITLE_FONT_MAX, CAPTION_FONT_PATHS)
    lines = _wrap_text(title_text.upper(), font, WIDTH - 100)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 16

    super_font = _load_font(max(int(TITLE_FONT_MAX * SUPERTITLE_RATIO), 18),
                            CAPTION_FONT_PATHS)
    super_h = super_font.getbbox("Ag")[3] - super_font.getbbox("Ag")[1] + 10
    super_gap = 8

    total_text_h = line_h * len(lines)
    if supertitle:
        total_text_h += super_h + super_gap
    text_y = int(HEIGHT * 0.75) - total_text_h // 2

    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    y = text_y

    if supertitle:
        sw = super_font.getbbox(supertitle)[2] - super_font.getbbox(supertitle)[0]
        draw.text(((WIDTH - sw) // 2, y), supertitle, font=super_font,
                  fill=(*HIGHLIGHT, 255),
                  stroke_width=2,
                  stroke_fill=(*PURPLE_STROKE, 220))
        y += super_h + super_gap

    for line in lines:
        lw = font.getbbox(line)[2] - font.getbbox(line)[0]
        draw.text(((WIDTH - lw) // 2, y), line, font=font,
                  fill=(255, 255, 255, 255),
                  stroke_width=CAPTION_STROKE_WIDTH,
                  stroke_fill=(*PURPLE_STROKE, 255))
        y += line_h
    img = Image.alpha_composite(img, text_layer)
    rgb = img.convert("RGB")
    rgb.save(output_path, "JPEG", quality=85)
    if output_path.stat().st_size > 2 * 1024 * 1024:
        rgb.save(output_path, "JPEG", quality=75)


# ---------------------------------------------------------------------------
# Assemble a single short
# ---------------------------------------------------------------------------

def _render_short(
    portrait_images: list[Image.Image],
    audio_path: Path,
    output_path: Path,
    title_text: str,
    section_words: list[dict],
    content_duration: float,
    supertitle: str = "",
):
    """
    Assemble one short:
      content with Ken Burns + title bar + captions → CTA (3s).
    Audio starts immediately (no delay).
    """
    content_frames = int(content_duration * FPS)
    cta_frames = int(CTA_DURATION * FPS)
    total_frames = content_frames + cta_frames
    xfade_frames = int(XFADE_DURATION * FPS)

    title_bar = _render_title_bar(title_text, supertitle)
    cta_img = _render_cta_frame()

    caption_font = _load_font(CAPTION_FONT_SIZE, CAPTION_FONT_PATHS)
    captions = ShortsCaptionRenderer(section_words, caption_font)

    n_imgs = len(portrait_images)
    seg_frames = content_frames // n_imgs if n_imgs else content_frames
    motions = ["zoom_in", "zoom_out"] * ((n_imgs + 1) // 2)

    video_tmp = output_path.with_suffix(".tmp.mp4")
    enc_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-v", "error",
        str(video_tmp),
    ]
    encoder = subprocess.Popen(
        enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
    )

    try:
        for i in range(total_frames):
            if i < content_frames:
                # ---- CONTENT PHASE ----
                t = i / FPS

                img_idx = min(i // seg_frames, n_imgs - 1)
                local = i - img_idx * seg_frames
                progress = local / seg_frames if seg_frames else 0

                frame = _ken_burns_crop(
                    portrait_images[img_idx], progress,
                    motions[img_idx % len(motions)],
                ).convert("RGBA")

                # Crossfade between images
                if n_imgs > 1 and img_idx < n_imgs - 1:
                    next_start = (img_idx + 1) * seg_frames
                    if i >= next_start - xfade_frames:
                        blend = (i - (next_start - xfade_frames)) / xfade_frames
                        nxt = _ken_burns_crop(
                            portrait_images[img_idx + 1], 0.0,
                            motions[(img_idx + 1) % len(motions)],
                        )
                        frame = Image.blend(
                            frame.convert("RGB"),
                            nxt.convert("RGB"),
                            blend,
                        ).convert("RGBA")

                # Title bar overlay
                frame = Image.alpha_composite(frame, title_bar)

                # Captions
                cap = captions.render(t)
                if cap is not None:
                    frame = Image.alpha_composite(frame, cap)

                # Fade to CTA in last 0.5s of content
                fade_out_frames = int(0.5 * FPS)
                if i >= content_frames - fade_out_frames:
                    blend = (content_frames - i) / fade_out_frames
                    frame = Image.blend(
                        cta_img.convert("RGB"),
                        frame.convert("RGB"),
                        blend,
                    ).convert("RGBA")

            else:
                # ---- CTA PHASE ----
                frame = cta_img

            encoder.stdin.write(frame.convert("RGB").tobytes())
    finally:
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"Encode failed: {err[-200:]}")

    # Mux audio directly (no delay)
    mux_cmd = [
        "ffmpeg", "-y",
        "-i", str(video_tmp),
        "-i", str(audio_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-v", "error",
        str(output_path),
    ]
    result = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Audio mux failed: {result.stderr[-200:]}")

    video_tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(job_dir: Path, points: list[int] | None = None) -> list[Path]:
    """
    Extract shorts from point sections in a completed job.

    Args:
        job_dir: Path to job directory.
        points:  Optional list of point numbers (e.g. [1, 2]).
                 If None, processes all points.
    """
    script_path = job_dir / "script.json"
    ts_path = job_dir / "timestamps.json"
    narration_path = job_dir / "narration.mp3"
    images_dir = job_dir / "images"
    vp_path = job_dir / "visual_prompts.json"

    for p in [script_path, ts_path, narration_path]:
        if not p.exists():
            raise FileNotFoundError(f"{p.name} not found in {job_dir}")

    script = json.loads(script_path.read_text())
    timestamps = json.loads(ts_path.read_text())
    visual_prompts = (
        json.loads(vp_path.read_text()) if vp_path.exists() else []
    )

    sections_ts = {s["id"]: s for s in timestamps["sections"]}
    sections_script = {s["id"]: s for s in script["sections"]}
    all_words = timestamps["words"]

    shorts_dir = job_dir / "shorts"
    shorts_dir.mkdir(exist_ok=True)

    # Collect point IDs in order
    point_ids = sorted(
        [sid for sid in sections_ts if sid.startswith("point_")],
        key=lambda x: int(x.split("_")[1]),
    )
    if points:
        point_ids = [
            f"point_{n}" for n in points if f"point_{n}" in sections_ts
        ]
    if not point_ids:
        print("  No point sections found.")
        return []

    print(f"\n{'=' * 50}")
    print(f"  Shorts Extraction")
    print(f"{'=' * 50}\n")
    video_title = script.get("title", "")
    print(f"  Job: {job_dir.name}")
    print(f"  Video: {video_title}")
    print(f"  Points: {len(point_ids)}\n")

    outputs: list[Path] = []

    for i, sid in enumerate(point_ids):
        ts = sections_ts[sid]
        start, end = ts["start"], ts["end"]
        duration = end - start
        script_sec = sections_script.get(sid, {})

        print(f"  [{i + 1}/{len(point_ids)}] {sid} ({duration:.1f}s)")

        # Title and supertitle
        title_text = _get_title_text(script_sec)
        point_num = _get_point_number(script_sec)
        supertitle = _get_supertitle(video_title, point_num)
        print(f"    Supertitle: \"{supertitle}\"")
        print(f"    Title: \"{title_text}\"")

        # Generate portrait images via Gemini
        point_img_dir = shorts_dir / sid / "images"
        print(f"    Generating portrait images...")
        portrait_paths = _generate_portrait_images(
            sid, visual_prompts, point_img_dir, count=2,
        )

        # Fallback to existing 16:9 images if generation produced nothing
        if not portrait_paths:
            print(f"    Falling back to cropped 16:9 images")
            portrait_paths = _fallback_crop_existing(sid, images_dir, count=2)

        if not portrait_paths:
            print(f"    No images available — skipping")
            continue

        portraits = [_prepare_portrait(p) for p in portrait_paths]
        print(f"    Images: {len(portraits)}")

        # Extract audio segment
        audio_path = shorts_dir / f"_audio_{sid}.m4a"
        _extract_audio(narration_path, start, end, audio_path)

        # Offset word timestamps to start from 0
        section_words = [
            {**w, "start": w["start"] - start, "end": w["end"] - start}
            for w in all_words
            if w["start"] >= start - 0.1 and w["end"] <= end + 0.1
        ]

        # Assemble the short
        short_path = shorts_dir / f"short_{sid}.mp4"
        print(f"    Assembling...", end=" ", flush=True)
        _render_short(
            portraits, audio_path, short_path,
            title_text, section_words, duration,
            supertitle=supertitle,
        )
        audio_path.unlink(missing_ok=True)

        # Thumbnail
        thumb_path = shorts_dir / f"thumb_{sid}.jpg"
        _generate_thumbnail(portrait_paths[0], title_text, thumb_path,
                            supertitle=supertitle)

        size_mb = short_path.stat().st_size / (1024 * 1024)
        total_dur = duration + CTA_DURATION
        print(f"OK ({size_mb:.1f}MB, {total_dur:.0f}s)")
        outputs.append(short_path)

    print(f"\n  {len(outputs)} short(s) generated in {shorts_dir}\n")
    return outputs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Dev Life with Uche — Shorts Extractor",
    )
    parser.add_argument("--job", required=True,
                        help="Path to job directory")
    parser.add_argument("--points", type=str, default=None,
                        help="Comma-separated point numbers (e.g. 1,2)")
    args = parser.parse_args()

    job = Path(args.job)
    if not job.is_absolute():
        job = config.JOBS_DIR / args.job

    if not job.is_dir():
        print(f"ERROR: {job} is not a directory", file=sys.stderr)
        sys.exit(1)

    pts = None
    if args.points:
        pts = [int(x.strip()) for x in args.points.split(",")]

    try:
        run(job, points=pts)
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
