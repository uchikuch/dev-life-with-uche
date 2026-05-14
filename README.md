# Dev Life with Uche

An illustrated YouTube channel about software engineering, startup culture, and developer realities. Long-form videos and shorts are produced end-to-end by an automated pipeline: scriptwriting with Claude, narration with ElevenLabs, illustration with Gemini, video assembly with FFmpeg, and scheduled publishing to YouTube.

This repository is the pipeline itself. Brand assets, trained model weights, and the editorial calendar are intentionally **not** included — you bring your own.

## Architecture

```
topic ─▶ script_gen ─▶ voice_gen ─▶ image_gen ─▶ assemble ─▶ thumbnail ─▶ shorts ─▶ publish
        (Claude)      (ElevenLabs)  (Gemini)     (FFmpeg)                            (YouTube)
```

Each stage is independently runnable. Output of one stage is the input to the next, written to a per-job directory under `pipeline/jobs/JOB_ID/`.

### Pipeline stages

1. **Script Generation** — Claude generates a listicle script (1400–1750 words, 8–10 min) with per-section visual prompts.
2. **Voice Generation** — ElevenLabs synthesises narration with word-level timestamps for caption sync.
3. **Image Generation** — Gemini (`gemini-3-pro-image-preview`) generates cel-shaded illustrations using a character reference image for identity consistency.
4. **Video Assembly** — Ken Burns motion, Perlin-noise particles, karaoke captions, FFmpeg encoding.
5. **Thumbnail** — Dark background, Impact font with purple glow, character composite.
6. **Shorts Extraction** — Individual points extracted as 9:16 portrait shorts.
7. **Publish** — Upload to YouTube as private, approval gate, then schedule for Tue/Thu/Sat at 14:00 in the configured timezone.

## Content Pillars

| Pillar | Description |
|--------|-------------|
| Startup Realities | The unsexy truth about founding and scaling |
| Sprint & Agile | Ceremonies, velocity theater, and what actually works |
| Customer Reality | What users actually think, say, and do |
| Career Navigation | Promotions, role transitions, and career inflection points |
| Tech Debt & Culture | Code rot, culture rot, and how to fight both |
| PM vs Engineer | The eternal dance between product and engineering |
| Founder / CTO | Technical leadership, loneliness, and hard decisions |

The full pillar configuration with tones and example topics lives in [`pipeline/content_config.json`](pipeline/content_config.json).

## Setup

### Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) on `$PATH` (`brew install ffmpeg` on macOS)
- Accounts for the APIs listed below

### Required accounts

| Service | Used for | Cost model |
|---------|---------|------------|
| [Anthropic](https://console.anthropic.com/) | Claude — script generation | Per-token |
| [Google AI Studio](https://aistudio.google.com/apikey) | Gemini — image generation | Per-image |
| [ElevenLabs](https://elevenlabs.io/) | Voice synthesis | Per-character |
| [Google Cloud Console](https://console.cloud.google.com/) | YouTube Data API OAuth | Free quota |
| [Pexels](https://www.pexels.com/api/) *(optional)* | Stock imagery fallback | Free |

### Install

```bash
git clone https://github.com/<your-username>/dev-life-with-uche.git
cd dev-life-with-uche/pipeline

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in API keys in .env

python validate_keys.py
```

### YouTube OAuth

1. Create a Google Cloud project, enable the YouTube Data API v3.
2. Create an OAuth 2.0 Client ID (Desktop type) and download the JSON.
3. Save it as `pipeline/client_secret.json`.
4. Run `python auth_youtube.py` once to authorise — the token is cached at `~/.dev-life-credentials.json`.

### Assets you provide yourself

The pipeline expects these files but does **not** ship them:

| Path | What it is |
|------|-----------|
| `character_sheet.png` | Reference image of your channel's character (passed to Gemini for identity consistency) |
| `pipeline/assets/logo/logo.png` | Channel logo used in thumbnails and end screens |
| `pipeline/assets/endscreen.png` | End-screen background image |
| `pipeline/assets/music/*.mp3` or `*.wav` | Background music tracks (pipeline picks one per video) |

For the character sheet specifically, a single front-facing reference at ~1024×1024 is enough — Gemini does the rest.

## Usage

```bash
cd pipeline

# Validate API keys before doing anything
python validate_keys.py

# Run a single topic through the full pipeline
python run.py --topic "why sprint planning is broken"

# Re-run a specific stage on an existing job
python run.py --job JOB_ID --stage voice

# Run a batch from content_config.json
python pipeline/scheduler.py --batch 3

# Generate just the thumbnail
python -m pipeline.thumbnail --job jobs/JOB_ID

# Extract shorts from a completed job
python -m pipeline.shorts --job jobs/JOB_ID

# Publish a completed job to YouTube
python -m pipeline.publish --job-id JOB_ID
```

## Visual Identity

- **Style:** Cel-shaded cartoon with realistic lighting, semi-realistic art style
- **Primary accent:** Purple `#7B3FE4`
- **Secondary accents:** Cyan `#4ECDC4`, Amber `#FFB830`
- **Thumbnails:** Dark background, Impact font, purple glow, character composite

See [`visual_identity.md`](visual_identity.md) for the full spec.

## License

[MIT](LICENSE).
