"""OpenAI-compatible LLM client for the AI reviewer.

Supports both local Ollama instances (openai-compatible server on
``http://localhost:11434``) and online providers behind an API key (OpenAI,
OpenRouter, Groq, ...). Uses only the stdlib ``urllib`` so no extra package is
required. Every call is wrapped so a failure never blocks the deterministic
review pipeline (fail-closed: no model -> deterministic hypothesis).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Optional

from trading_bot.ai.review import ReviewLLM
from trading_bot.storage.interfaces import ModelConfigRecord

DEFAULT_TIMEOUT = 30


def _chat_endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    if "v1" not in base:
        return f"{base}/v1/chat/completions"
    return f"{base}/chat/completions"


class OpenAICompatLLM(ReviewLLM):
    """Thin chat-completions client. Safe to call; raises on failure."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        system_prompt: str = "",
    ):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.system_prompt = system_prompt or (
            "You are an expert quantitative trading analyst. "
            "Be concise, concrete and falsifiable."
        )

    def generate_hypothesis(self, prompt: str) -> str:
        url = _chat_endpoint(self.base_url)
        if not url:
            raise ValueError("model base_url is not set")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AI-ImprovBot/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"model HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"model unreachable: {e.reason}") from e
        except (socket.timeout, TimeoutError) as e:
            raise RuntimeError(f"model timed out after {self.timeout}s") from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"model returned no choices: {data}")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("model returned empty content")
        return content.strip()

    def ping(self) -> dict:
        """Quick connectivity probe for the settings page."""
        start = time.time()
        try:
            out = self.generate_hypothesis("Reply with the single word: ok")
            latency = round((time.time() - start) * 1000)
            return {"ok": True, "latency_ms": latency, "reply": out[:80]}
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            return {"ok": False, "error": str(e), "latency_ms": round((time.time() - start) * 1000)}


def model_base_url(rec: ModelConfigRecord) -> str:
    """Default base URLs per provider when the user leaves it blank."""
    provider_urls = {
        "ollama": "http://localhost:11434",
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "groq": "https://api.groq.com/openai/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    }
    return rec.base_url or provider_urls.get(rec.provider, "")


def default_model_name(rec: ModelConfigRecord) -> str:
    defaults = {
        "ollama": "llama3.1:8b",
        "openai": "gpt-4o-mini",
        "openrouter": "openai/gpt-4o-mini",
        "groq": "llama-3.3-70b-versatile",
        "anthropic": "claude-3-5-haiku-latest",
        "gemini": "gemini-1.5-flash",
    }
    return rec.model or defaults.get(rec.provider, "")


def llm_from_config(rec: ModelConfigRecord) -> Optional[OpenAICompatLLM]:
    """Build a client from a stored model config. None if unusable."""
    if rec is None:
        return None
    base_url = model_base_url(rec)
    model = default_model_name(rec)
    if not base_url or not model:
        return None
    if rec.provider == "ollama" and not rec.api_key:
        return OpenAICompatLLM(base_url=base_url, model=model, api_key="")
    if rec.provider != "ollama" and not rec.api_key:
        return None  # online providers require an API key
    return OpenAICompatLLM(base_url=base_url, model=model, api_key=rec.api_key or "")
