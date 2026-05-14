"""Dev Life with Uche — Configuration loaded from .env"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]

# ---------------------------------------------------------------------------
# Image Generation (Google Gemini)
# ---------------------------------------------------------------------------
IMAGEN_MODEL = os.getenv("IMAGEN_MODEL", "gemini-3-pro-image-preview")

# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "PLACEHOLDER_VOICE_ID")

# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------
YOUTUBE_CLIENT_SECRET_PATH = os.getenv("YOUTUBE_CLIENT_SECRET_PATH", "./client_secret.json")
PUBLISH_DAYS = [
    os.getenv("PUBLISH_DAY_1", "Tuesday"),
    os.getenv("PUBLISH_DAY_2", "Thursday"),
    os.getenv("PUBLISH_DAY_3", "Saturday"),
]
PUBLISH_HOUR = int(os.getenv("PUBLISH_HOUR", "14"))
PUBLISH_TIMEZONE = os.getenv("PUBLISH_TIMEZONE", "Europe/Berlin")
APPROVAL_WINDOW_HOURS = int(os.getenv("APPROVAL_WINDOW_HOURS", "24"))
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
MAX_CONCURRENT_IMAGE_REQUESTS = int(os.getenv("MAX_CONCURRENT_IMAGE_REQUESTS", "5"))
TARGET_SCENE_DURATION_SECONDS = int(os.getenv("TARGET_SCENE_DURATION_SECONDS", "15"))
SCRIPT_MIN_WORDS = int(os.getenv("SCRIPT_MIN_WORDS", "1400"))
SCRIPT_MAX_WORDS = int(os.getenv("SCRIPT_MAX_WORDS", "1750"))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
PROJECT_ROOT = ROOT_DIR.parent
JOBS_DIR = ROOT_DIR / "jobs"
PROMPTS_DIR = ROOT_DIR / "prompts"
ASSETS_DIR = ROOT_DIR / "assets"

# Character reference (kept for thumbnail/other uses)
CHARACTER_REF_PATH = PROJECT_ROOT / "character_sheet.png"
CHANNEL_ASSETS_DIR = PROJECT_ROOT / "Channel Assets"
