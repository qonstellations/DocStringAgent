"""Model factory — supports Ollama (local) and Gemini (cloud).

Auto-detects locally available Ollama models at startup and falls back
to Gemini 2.5 when no local models are found.
"""

from __future__ import annotations

import httpx
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

from src import config


# ── Ollama Discovery ────────────────────────────────────────────


def list_ollama_models() -> list[str]:
    """Query the local Ollama server for available model tags.

    Returns:
        A list of model name strings, e.g. ["llama3.2:latest", "codellama:7b"].
        Returns an empty list if Ollama is unreachable.
    """
    try:
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def detect_default_model() -> tuple[str, str]:
    """Pick the best available model automatically.

    Scans local Ollama first; if any model is found, selects the first one.
    Otherwise falls back to the Gemini cloud model.

    Returns:
        A (provider, model_name) tuple, e.g. ("ollama", "llama3.2:latest")
        or ("gemini", "gemini-2.5-flash").
    """
    local_models = list_ollama_models()
    if local_models:
        return ("ollama", local_models[0])
    return ("gemini", config.DEFAULT_GEMINI_MODEL)


# ── LLM Factory ────────────────────────────────────────────────


def get_llm(
    provider: str = "auto",
    model_name: str | None = None,
    temperature: float = config.TEMPERATURE,
):
    """Return a LangChain chat model for the requested provider.

    Args:
        provider: "ollama", "gemini", or "auto" (detect best available).
        model_name: Model identifier.  When *None* the default for the
            chosen provider is used.
        temperature: Sampling temperature (0.0–1.0).

    Returns:
        A LangChain BaseChatModel instance.

    Raises:
        ValueError: If the provider is unknown or Gemini is requested
            without a configured API key.
    """
    if provider == "auto":
        provider, auto_model = detect_default_model()
        if model_name is None:
            model_name = auto_model

    if provider == "ollama":
        model_name = model_name or config.DEFAULT_OLLAMA_MODEL
        return ChatOllama(
            model=model_name,
            temperature=temperature,
            base_url=config.OLLAMA_BASE_URL,
        )

    if provider == "gemini":
        model_name = model_name or config.DEFAULT_GEMINI_MODEL
        api_key = config.GEMINI_API_KEY
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Add it to your .env file."
            )
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
        )

    raise ValueError(f"Unknown provider: {provider!r}. Use 'ollama' or 'gemini'.")
