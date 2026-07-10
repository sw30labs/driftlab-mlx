"""Optional, advisory-only LLM layer.

Reaches a local OMLX OpenAI-compatible server (or any OpenAI-compatible
endpoint the operator controls). The LLM may write narratives and
recommendations; it NEVER makes a severity or verdict decision. If no provider
is configured (``DRIFTLAB_LLM_PROVIDER=none``) or the endpoint is unreachable,
every function returns ``None`` and the platform works fully without it — that
invariant is tested.

IMPORTANT: always construct ``ChatOpenAI`` with ``streaming=False``. The default
``streaming=True`` hangs indefinitely against OMLX with large models.
"""

from __future__ import annotations

from typing import Optional

from .config import get_settings


def is_enabled() -> bool:
    return get_settings().llm_provider != "none"


def _client():
    from langchain_openai import ChatOpenAI

    s = get_settings()
    return ChatOpenAI(
        model="local",
        base_url=s.omlx_base_url,
        api_key=s.omlx_api_key,
        streaming=False,  # required for OMLX
        temperature=0.0,
    )


def executive_narrative(ledger: dict) -> Optional[str]:
    """Generate a short human narrative for a cycle. Returns None if LLM off."""
    if not is_enabled():
        return None
    try:
        client = _client()
        prompt = (
            "Summarize this agent compliance cycle in 2-3 sentences for a "
            "compliance officer. Facts only, no recommendations beyond noting "
            f"the score and confirmed drifts.\n{ledger}"
        )
        resp = client.invoke(prompt)
        return resp.content
    except Exception:
        # Advisory only — never fail a compliance run on LLM issues.
        return None


def analyst_decomposition(claim: str, rationale: str) -> Optional[str]:
    """Optional DeepAgents-style advisory decomposition of a confirmed drift.

    Advisory only; cannot alter a finding or verdict. Returns None if disabled
    or on any error.
    """
    if not is_enabled():
        return None
    try:
        client = _client()
        resp = client.invoke(
            "As an advisory analyst (read-only), suggest 2 decomposition angles "
            f"to further investigate this confirmed drift. Claim: {claim}. "
            f"Evidence: {rationale}."
        )
        return resp.content
    except Exception:
        return None