"""Configuration constants for DocStringAgent."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Model Defaults ──────────────────────────────────────────────
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
TEMPERATURE = 0.1

# ── Ollama ──────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ── Gemini ──────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Agent Behaviour ─────────────────────────────────────────────
STRICT_MODE = True
MAX_CORRECTION_PASSES = 2
RATE_LIMIT_DELAY = 1.0  # Seconds to wait between function processing
MAX_RETRIES = 3         # Max retries for 429/Resource Exhausted errors

# ── Server ──────────────────────────────────────────────────────
DEFAULT_PORT = 8000
