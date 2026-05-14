"""
Stage 1: Script Generation via Claude API

Calls Claude twice:
  1. Generate the full narration script as JSON (listicle format)
  2. Generate Gemini image prompts for each section as JSON

Both outputs are validated before saving to the job directory.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import anthropic

import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text().strip()


def _count_words(sections: list[dict]) -> int:
    return sum(len(s["text"].split()) for s in sections)


def _has_em_dash(sections: list[dict]) -> bool:
    for s in sections:
        if "\u2014" in s["text"] or " -- " in s["text"]:
            return True
    return False


def _extract_json(text: str) -> dict | list:
    """Extract JSON from Claude's response, handling possible markdown fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


REQUIRED_SECTION_IDS = ["hook", "intro", "conclusion", "cta"]


def _validate_script(data: dict) -> list[str]:
    """Validate script JSON against spec requirements. Returns list of errors."""
    errors = []

    for field in ("title", "description", "tags", "sections"):
        if field not in data:
            errors.append(f"Missing top-level field: {field}")

    if errors:
        return errors

    if len(data["title"]) > 120:
        errors.append(f"Title too long: {len(data['title'])} chars (max 120)")

    if not isinstance(data["tags"], list) or len(data["tags"]) == 0:
        errors.append("Tags must be a non-empty list")

    sections = data["sections"]
    section_ids = [s["id"] for s in sections]

    for sid in REQUIRED_SECTION_IDS:
        if sid not in section_ids:
            errors.append(f"Missing required section: {sid}")

    point_sections = [s for s in sections if s["id"].startswith("point_")]
    if len(point_sections) < 3:
        errors.append(f"Need at least 3 point sections, got {len(point_sections)}")

    for s in sections:
        for field in ("id", "label", "text", "duration_estimate"):
            if field not in s:
                errors.append(f"Section missing field '{field}': {s.get('id', '?')}")

    word_count = _count_words(sections)
    if word_count < config.SCRIPT_MIN_WORDS:
        errors.append(f"Word count too low: {word_count} (min {config.SCRIPT_MIN_WORDS})")
    if word_count > config.SCRIPT_MAX_WORDS:
        errors.append(f"Word count too high: {word_count} (max {config.SCRIPT_MAX_WORDS})")

    if _has_em_dash(sections):
        errors.append("Em dashes found in narration text. Use full stops instead.")

    return errors


def _validate_visual_prompts(data: list, section_ids: list[str]) -> list[str]:
    errors = []
    if not isinstance(data, list):
        errors.append("Visual prompts must be a JSON array")
        return errors

    mandatory_prefix = "Generate an image based on the character in the reference image."

    for item in data:
        if "section_id" not in item:
            errors.append("Visual prompt missing 'section_id'")
        if "sub_index" not in item:
            errors.append(f"Visual prompt missing 'sub_index' for '{item.get('section_id', '?')}'")
        if "prompt" not in item:
            errors.append("Visual prompt missing 'prompt'")
        elif not item["prompt"].startswith(mandatory_prefix):
            errors.append(
                f"Visual prompt for '{item.get('section_id', '?')}' missing mandatory prefix"
            )
        if "particle_direction" not in item:
            errors.append(f"Visual prompt for '{item.get('section_id', '?')}' missing 'particle_direction'")
        if "prompt" in item:
            prompt_lower = item["prompt"].lower()
            male_terms = ["male", "masculine", "goatee", "mustache", "short haircut"]
            male_count = sum(1 for t in male_terms if t in prompt_lower)
            if male_count < 2:
                errors.append(
                    f"Prompt '{item.get('section_id', '?')}[{item.get('sub_index', '?')}]' "
                    f"missing male descriptors for main character (need 2+ of: male, masculine, goatee, mustache, short haircut)"
                )

    from collections import Counter
    prompt_counts = Counter(p.get("section_id") for p in data)
    for sid in section_ids:
        if sid not in prompt_counts:
            errors.append(f"No visual prompt for section: {sid}")
        elif sid.startswith("point_") and prompt_counts[sid] < 2:
            errors.append(f"Section '{sid}' needs at least 2 image prompts, got {prompt_counts[sid]}")

    skin_tone_terms = [
        "caucasian", "east asian", "south asian", "latina", "latino",
        "pale", "fair-skinned", "light-skinned", "olive-skinned",
        "middle eastern", "european", "dark-skinned", "brown-skinned",
        "black", "african", "southeast asian", "mixed-race",
    ]
    banned_clothing = ["purple", "violet", "lavender", "lilac"]

    for item in data:
        prompt = item.get("prompt", "").lower()
        if "other character" in prompt or "colleague" in prompt or "two-shot" in prompt.lower() or "group" in prompt:
            tone_count = sum(1 for t in skin_tone_terms if t in prompt)
            if tone_count < 1:
                errors.append(
                    f"Multi-character prompt '{item.get('section_id')}[{item.get('sub_index')}]' "
                    f"missing explicit skin tones for supporting characters"
                )
            clothing_phrases = [
                f"{b} shirt" for b in banned_clothing
            ] + [
                f"{b} hoodie" for b in banned_clothing
            ] + [
                f"{b} jacket" for b in banned_clothing
            ] + [
                f"{b} top" for b in banned_clothing
            ] + [
                f"wearing {b}" for b in banned_clothing
            ]
            allowed_phrases = ["purple hoodie with no text", "neon purple hoodie",
                               "plain neon purple hoodie", "purple hoodie"]
            for phrase in clothing_phrases:
                if phrase in prompt and not any(a in prompt for a in allowed_phrases if phrase in a):
                    errors.append(
                        f"Prompt '{item.get('section_id')}[{item.get('sub_index')}]' "
                        f"uses banned clothing colour in '{phrase}' on supporting character"
                    )

    return errors


# ---------------------------------------------------------------------------
# Main generation functions
# ---------------------------------------------------------------------------

def generate_script(topic: str, max_attempts: int = 6) -> dict:
    """Call Claude API to generate the narration script. Returns validated dict."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_prompt = _load_prompt("script_system.txt")
    user_prompt = _load_prompt("script_user.txt").format(
        topic=topic,
        min_words=config.SCRIPT_MIN_WORDS,
        max_words=config.SCRIPT_MAX_WORDS,
    )

    messages = [{"role": "user", "content": user_prompt}]
    last_errors = []

    for attempt in range(1, max_attempts + 1):
        print(f"  Generating script (attempt {attempt})...")

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=system_prompt,
            messages=messages,
        )

        raw = resp.content[0].text
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}")
            if attempt < max_attempts:
                messages = [{"role": "user", "content": user_prompt}]
                continue
            raise ValueError(f"Failed to parse script JSON after {max_attempts} attempts")

        errors = _validate_script(data)
        word_count = _count_words(data["sections"])

        if not errors:
            print(f"  Script validated. Word count: {word_count}")
            return data

        last_errors = errors
        print(f"  Validation errors (attempt {attempt}, {word_count} words):")
        for err in errors:
            print(f"    - {err}")

        if attempt < max_attempts:
            section_counts = "\n".join(
                f"  {s['id']}: {len(s['text'].split())} words"
                for s in data["sections"]
            )
            target = (config.SCRIPT_MIN_WORDS + config.SCRIPT_MAX_WORDS) // 2

            diff = word_count - target
            if word_count < config.SCRIPT_MIN_WORDS:
                adjust = f"You need to ADD approximately {abs(diff)} words. Expand the point sections with more specific examples, anecdotes, and detail."
            else:
                adjust = f"You need to CUT approximately {abs(diff)} words. Trim the longer sections while keeping the essential content. Do not cut below {config.SCRIPT_MIN_WORDS} words."

            fix_prompt = (
                f"Your script has {word_count} words. The target is EXACTLY {target} words "
                f"(acceptable range: {config.SCRIPT_MIN_WORDS}-{config.SCRIPT_MAX_WORDS}). "
                f"This is a tight window. Count carefully.\n\n"
                f"Current word counts per section:\n{section_counts}\n\n"
                f"Issues to fix:\n"
                + "\n".join(f"- {e}" for e in errors)
                + f"\n\n{adjust}\n\n"
                "Regenerate the COMPLETE script JSON. Return valid JSON only, no preamble."
            )
            messages = [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": fix_prompt},
            ]
        else:
            messages = [{"role": "user", "content": user_prompt}]

    raise ValueError(f"Script generation failed validation after {max_attempts} attempts. Last errors: {last_errors}")


def generate_visual_prompts(script: dict, max_retries: int = 5) -> list[dict]:
    """Call Claude API to generate image prompts for each script section."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_prompt = _load_prompt("visual_system.txt")
    section_ids = [s["id"] for s in script["sections"]]

    sections_summary = "\n\n".join(
        f"SECTION: {s['id']} ({s['label']}) — {s['duration_estimate']}s\n"
        + (s["text"][:300] + "..." if len(s["text"]) > 300 else s["text"])
        for s in script["sections"]
    )

    user_prompt = (
        f"Generate multiple image prompts for these {len(script['sections'])} script sections.\n"
        f"Target: one scene change every ~{config.TARGET_SCENE_DURATION_SECONDS} seconds.\n\n"
        f"Image count guidelines:\n"
        f"- hook: 1-2 images\n"
        f"- intro: 1-2 images\n"
        f"- each point section: 2-3 images (vary angle, expression, composition)\n"
        f"- conclusion: 1-2 images\n"
        f"- cta: 1-2 images\n\n"
        f"CRITICAL composition requirements:\n"
        f"- Rotate camera framing: wide, medium, close-up, full body, over-the-shoulder, group\n"
        f"- Vary character position: left third, right third, centered (sparingly)\n"
        f"- At least 40% of images must include other characters\n"
        f"- At least 3 full body shots showing sneakers\n"
        f"- No two consecutive sub-scenes same framing\n"
        f"- Dynamic poses: walking, leaning, pointing, gesturing — not just seated\n\n"
        f"{sections_summary}\n\n"
        "Return a JSON array only. No preamble. No markdown fences."
    )

    messages = [{"role": "user", "content": user_prompt}]

    for attempt in range(1, max_retries + 1):
        print(f"  Generating visual prompts (attempt {attempt})...")

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16384,
            system=system_prompt,
            messages=messages,
        )

        raw = resp.content[0].text
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e}")
            if attempt < max_retries:
                messages = [{"role": "user", "content": user_prompt}]
                continue
            raise ValueError(f"Failed to parse visual prompts JSON after {max_retries} attempts")

        errors = _validate_visual_prompts(data, section_ids)
        if not errors:
            print(f"  Visual prompts validated. {len(data)} prompts generated.")
            return data

        print(f"  Validation errors (attempt {attempt}):")
        for err in errors:
            print(f"    - {err}")

        if attempt < max_retries:
            fix_prompt = (
                "Your visual prompts have validation errors:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nREMINDER for multi-character scenes:\n"
                "- Every supporting character MUST have an explicit skin tone phrase "
                "(e.g. 'light-skinned Caucasian', 'East Asian with pale complexion', "
                "'olive-skinned South Asian', 'fair-skinned redhead').\n"
                "- No purple/violet/lavender clothing on supporting characters.\n"
                "- No hoodies, caps, or short low haircuts on supporting characters.\n\n"
                "Fix ONLY the problematic prompts and regenerate the COMPLETE JSON array. "
                "Return valid JSON only, no preamble."
            )
            messages = [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": fix_prompt},
            ]
        else:
            messages = [{"role": "user", "content": user_prompt}]

    raise ValueError(f"Visual prompt generation failed after {max_retries} attempts")


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------

def create_job_dir(topic: str) -> Path:
    """Create a timestamped job directory."""
    from datetime import datetime

    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40]
    job_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"
    job_dir = config.JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "images").mkdir(exist_ok=True)
    return job_dir


def run(topic: str, dry_run: bool = False) -> Path:
    """
    Run Stage 1: generate script and visual prompts, save to job directory.

    Returns:
        Path to the job directory.
    """
    print(f"\n{'=' * 50}")
    print(f"Stage 1: Script Generation")
    print(f"Topic: {topic}")
    print(f"{'=' * 50}\n")

    job_dir = create_job_dir(topic)
    print(f"  Job directory: {job_dir.name}\n")

    script = generate_script(topic)
    script_path = job_dir / "script.json"
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))
    print(f"  Saved: {script_path.name}")

    total_words = _count_words(script["sections"])
    print(f"\n  Title: {script['title']}")
    print(f"  Words: {total_words}")
    print(f"  Sections: {len(script['sections'])}")
    for s in script["sections"]:
        wc = len(s["text"].split())
        print(f"    {s['id']:<16} {wc:>4} words  ({s['duration_estimate']}s)")

    if dry_run:
        print(f"\n  [DRY RUN] Skipping visual prompt generation.")
        return job_dir

    print()
    visual_prompts = generate_visual_prompts(script)
    vp_path = job_dir / "visual_prompts.json"
    vp_path.write_text(json.dumps(visual_prompts, indent=2, ensure_ascii=False))
    print(f"  Saved: {vp_path.name}")

    print(f"\n  Stage 1 complete.\n")
    return job_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Script Generation (Stage 1)")
    parser.add_argument("--topic", required=True, help="Video topic brief")
    parser.add_argument("--dry-run", action="store_true", help="Script only, skip visual prompts")
    args = parser.parse_args()

    try:
        job_dir = run(args.topic, dry_run=args.dry_run)
        print(f"  Output: {job_dir}")
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        sys.exit(1)
