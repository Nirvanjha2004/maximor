"""Central configuration + tiny .env loader (no external dependency)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Load KEY=VALUE pairs from .env into os.environ (does not override existing)."""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Fallback chain of free OpenRouter models (tried in order).
# Verified Sep 2026: nemotron-nano returns clean content; others kept as fallback.
OPENROUTER_FALLBACKS = [
    m.strip() for m in os.environ.get(
        "OPENROUTER_FALLBACKS",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"
        "nvidia/nemotron-3-super-120b-a12b:free,"
        "minimax/minimax-m2.7:free,"
        "google/gemma-4-31b-it:free,"
        "z-ai/glm-5.2:free",
    ).split(",") if m.strip()
]

# Rough list prices (USD per million tokens) used for the cost scoreboard.
PRICE_IN_PER_MTOK = float(os.environ.get("PRICE_IN_PER_MTOK", "3"))
PRICE_OUT_PER_MTOK = float(os.environ.get("PRICE_OUT_PER_MTOK", "15"))
