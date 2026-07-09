"""LLM layer — OMLX-first, optional, advisory-only.

The entire compliance path (diff, anomaly, score, experiment verdicts) runs
with ``llm_provider="none"``. When OMLX is configured, the LLM adds prose:
report narratives and experiment annotations. It never assigns severity and
never decides a verdict.

OMLX notes (article-buddy llm_factory pattern):
* generic OpenAI-compatible client, base_url http://127.0.0.1:8000/v1, api_key "test";
* long timeout — OMLX loads models on demand;
* ALWAYS ``streaming=False``: the default streaming path hangs indefinitely
  against OMLX with large models (confirmed on Qwen3.6-27B-bf16).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from driftlab.config import Settings

logger = logging.getLogger(__name__)


class TokenBudgetExceeded(RuntimeError):
    """The advisory LLM budget for this cycle is spent."""


@dataclass
class TokenUsage:
    """Check-before-spend budget guard (project-pulse pattern)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    call_count: int = 0
    budget_limit: int | None = None
    _est_chars_per_token: int = field(default=4, repr=False)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def check_budget(self, estimated_tokens: int = 0) -> None:
        if self.budget_limit is not None and self.total_tokens + estimated_tokens > self.budget_limit:
            raise TokenBudgetExceeded(
                f"token budget {self.budget_limit} would be exceeded "
                f"(used {self.total_tokens}, requested ~{estimated_tokens})"
            )

    def record(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.call_count += 1

    def estimate(self, text: str) -> int:
        return max(1, len(text) // self._est_chars_per_token)


def build_chat_model(settings: Settings) -> Any | None:
    """ChatOpenAI against OMLX/OpenAI, or None when provider is 'none' /
    the optional dependency is missing. Callers must handle None."""
    provider = settings.llm_provider.lower().strip()
    if provider in ("", "none"):
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning("llm_provider=%s but langchain-openai is not installed; running LLM-free", provider)
        return None

    if provider == "omlx":
        model = settings.llm_model or _discover_omlx_model(settings)
        if not model:
            logger.warning("no OMLX model discoverable at %s; running LLM-free", settings.omlx_base_url)
            return None
        return ChatOpenAI(
            model=model,
            base_url=settings.omlx_base_url,
            api_key=settings.omlx_api_key,
            timeout=settings.omlx_request_timeout,
            streaming=False,  # REQUIRED for OMLX — streaming hangs with large models
            temperature=0.2,
        )
    if provider == "openai":
        if not settings.llm_model:
            logger.warning("llm_provider=openai requires DRIFTLAB_LLM_MODEL; running LLM-free")
            return None
        return ChatOpenAI(model=settings.llm_model, streaming=False, temperature=0.2)
    logger.warning("unknown llm_provider %r; running LLM-free", provider)
    return None


def _discover_omlx_model(settings: Settings) -> str | None:
    """GET /models on the local OMLX server (article-buddy auto-discovery)."""
    try:
        import httpx

        response = httpx.get(
            f"{settings.omlx_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.omlx_api_key}"},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        return str(data[0]["id"]) if data else None
    except Exception as exc:  # any failure -> LLM-free, never fatal
        logger.debug("OMLX model discovery failed: %s", exc)
        return None


def invoke_with_retries(model: Any, messages: list, *, max_retries: int = 2, usage: TokenUsage | None = None) -> Any:
    """model.invoke with exponential backoff capped at 8s (article-buddy)."""
    if usage is not None:
        est = sum(usage.estimate(getattr(m, "content", str(m))) for m in messages)
        usage.check_budget(est)
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            response = model.invoke(messages)
            if usage is not None:
                meta = getattr(response, "usage_metadata", None) or {}
                usage.record(int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0)))
            return response
        except TokenBudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — provider errors are retryable
            last_err = exc
            if attempt <= max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise last_err  # type: ignore[misc]


def narrate(model: Any | None, prompt: str, *, usage: TokenUsage | None = None, max_retries: int = 2) -> str | None:
    """Advisory prose. Any failure returns None — narratives are optional."""
    if model is None:
        return None
    try:
        from langchain_core.messages import HumanMessage

        response = invoke_with_retries(model, [HumanMessage(content=prompt)], max_retries=max_retries, usage=usage)
        text = getattr(response, "content", None)
        return str(text).strip() if text else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM narrative skipped: %s", exc)
        return None
