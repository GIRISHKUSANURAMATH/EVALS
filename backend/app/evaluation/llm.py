"""Optional LLM-assisted enhancement interface.

EVALS works fully offline with deterministic processing. This module defines a small
interface for *suggesting* candidate expected outputs with an LLM. Suggestions are always
stored as ``candidate`` and must be human-approved; the default provider does nothing.

An OpenAI-compatible provider is included so a local server (e.g. Ollama, LM Studio,
vLLM) can be plugged in later via environment variables. It is disabled by default.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx


class ExpectedOutputSuggester(Protocol):
    name: str

    def suggest(self, user_input: str, system_prompt: str | None, failure_type: str | None) -> str | None: ...


class NoOpSuggester:
    name = "none"

    def suggest(self, user_input: str, system_prompt: str | None, failure_type: str | None) -> str | None:
        return None


class OpenAICompatibleSuggester:
    """Calls a /v1/chat/completions endpoint. Inputs are already PII-redacted."""

    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.client = httpx.Client(timeout=timeout, transport=transport)

    def suggest(self, user_input: str, system_prompt: str | None, failure_type: str | None) -> str | None:
        messages = [
            {
                "role": "system",
                "content": "You write concise reference answers for an evaluation dataset. "
                "If you are unsure, answer exactly: UNSURE.",
            },
            {
                "role": "user",
                "content": f"System prompt of the original app:\n{system_prompt or '(none)'}\n\n"
                f"User input:\n{user_input}\n\nWrite the ideal assistant response.",
            },
        ]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={"model": self.model, "messages": messages, "temperature": 0},
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None
        return None if not text or text == "UNSURE" else text


def get_suggester(provider: str) -> ExpectedOutputSuggester:
    if provider == "openai_compatible":
        base = os.environ.get("EVALS_LLM_BASE_URL", "http://localhost:11434/v1")
        model = os.environ.get("EVALS_LLM_MODEL", "llama3.1")
        return OpenAICompatibleSuggester(base, model, os.environ.get("EVALS_LLM_API_KEY"))
    return NoOpSuggester()
