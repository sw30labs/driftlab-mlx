"""Optional, advisory-only LLM layer — OMLX.

Speaks the same contract as the sibling projects on this workstation
(book-buddy-2026's ``OMLXBackend``, contingency-atlas's ``OMLXClient``): a
local, OpenAI-compatible MLX server, an explicit model id, and **never**
streaming — streaming hangs indefinitely against OMLX on large models.

The LLM may write narratives and recommendations; it NEVER makes a severity or
verdict decision. If no provider is configured
(``DRIFTLAB_LLM_PROVIDER=none``, the default) or the endpoint is unreachable,
every generation function returns ``None`` and the platform works fully without
it — that invariant is tested.

The transport is stdlib ``urllib`` rather than an SDK, for the same reason the
web deck is stdlib-only: the advisory path must never be the thing that makes
an install fail, and a compliance tool should be auditable end to end.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse

from .config import get_settings

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


class LLMError(RuntimeError):
    """Any advisory-path failure. Never propagates into a compliance result."""


def is_enabled() -> bool:
    return get_settings().llm_provider != "none"


def _require_local_endpoint(base_url: str) -> None:
    """Local-first: refuse to ship trace context off-host without consent."""
    if get_settings().allow_remote_llm:
        return
    host = urlparse(base_url).hostname or ""
    if host not in _LOOPBACK_HOSTS:
        raise LLMError(
            f"refusing to send trace context to non-loopback LLM endpoint {base_url!r}. "
            f"DriftLab is local-first; set DRIFTLAB_ALLOW_REMOTE_LLM=1 to accept the egress."
        )


def _endpoint() -> str:
    s = get_settings()
    base_url = s.llm_base_url
    if not base_url:
        raise LLMError(f"no base_url configured for llm_provider={s.llm_provider!r}")
    _require_local_endpoint(base_url)
    return base_url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects.

    ``_require_local_endpoint`` vets the *configured* URL, so a redirect would
    otherwise be a hole straight through it: a compromised or misconfigured
    local endpoint could 302 the trace context to any host. Returning None
    makes urllib surface the 3xx as an HTTPError instead of following it.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _request(path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    s = get_settings()
    url = f"{_endpoint()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {s.omlx_api_key}",
            "Content-Type": "application/json",
        },
        method="POST" if data is not None else "GET",
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not isinstance(body, dict):
            raise LLMError(
                f"{url} returned {type(body).__name__}, not a JSON object — "
                f"is this an OpenAI-compatible endpoint?"
            )
        return body
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise LLMError(f"HTTP {exc.code} from {url}{': ' + detail if detail else ''}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach {url}: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LLMError(f"malformed response from {url}: {exc}") from exc
    except OSError as exc:
        raise LLMError(f"cannot reach {url}: {exc}") from exc


def list_models(timeout: float = 3.0) -> list[str]:
    """Model ids the configured endpoint serves. Raises :class:`LLMError`."""
    data = _request("/models", None, timeout)
    return [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]


def probe(timeout: float = 3.0) -> dict[str, Any]:
    """Backend health for the web deck. Never raises."""
    s = get_settings()
    status: dict[str, Any] = {
        "provider": s.llm_provider,
        "enabled": is_enabled(),
        "base_url": s.llm_base_url,
        "model": s.omlx_model,
        "reachable": False,
        "models": [],
        "detail": "",
    }
    if not is_enabled():
        status["detail"] = ("LLM disabled (DRIFTLAB_LLM_PROVIDER=none) — "
                            "advisory narratives off")
        return status
    try:
        status["models"] = list_models(timeout=timeout)
        status["reachable"] = True
        if status["model"] not in status["models"]:
            status["detail"] = (
                f"configured model {s.omlx_model!r} is not served by this endpoint"
            )
    except LLMError as exc:
        status["detail"] = str(exc)
    return status


def chat(prompt: str, timeout: float | None = None) -> str:
    """One non-streaming completion. Raises :class:`LLMError` on any failure."""
    s = get_settings()
    data = _request(
        "/chat/completions",
        {
            "model": s.omlx_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": s.omlx_max_tokens,
            "stream": False,  # OMLX hangs when streaming large models
        },
        timeout if timeout is not None else s.omlx_timeout,
    )
    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"no choices in response from {s.omlx_model}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    if not content:
        finish = choices[0].get("finish_reason", "?")
        raise LLMError(
            f"{s.omlx_model} returned empty content (finish_reason={finish})"
        )
    return str(content).strip()


def generate(prompt: str) -> tuple[Optional[str], Optional[str]]:
    """Advisory completion as ``(text, error)``. Never raises.

    Callers that only want the text use the wrappers below; the web deck uses
    this form so it can show the operator *why* a narrative is unavailable.
    """
    if not is_enabled():
        return None, ("advisory LLM is disabled — set DRIFTLAB_LLM_PROVIDER=omlx "
                      "to enable narratives")
    try:
        return chat(prompt), None
    except LLMError as exc:
        return None, str(exc)
    except Exception as exc:  # advisory only — never fail a run on LLM issues
        return None, f"{type(exc).__name__}: {exc}"


def _narrative_prompt(ledger: dict) -> str:
    return (
        "Summarize this agent compliance cycle in 2-3 sentences for a "
        "compliance officer. Facts only, no recommendations beyond noting "
        f"the score and confirmed drifts.\n{ledger}"
    )


def executive_narrative(ledger: dict) -> Optional[str]:
    """Generate a short human narrative for a cycle. Returns None if LLM off."""
    return generate(_narrative_prompt(ledger))[0]


def executive_narrative_detailed(ledger: dict) -> tuple[Optional[str], Optional[str]]:
    """:func:`executive_narrative` with the failure reason attached."""
    return generate(_narrative_prompt(ledger))


def analyst_decomposition(claim: str, rationale: str) -> Optional[str]:
    """Optional DeepAgents-style advisory decomposition of a confirmed drift.

    Advisory only; cannot alter a finding or verdict. Returns None if disabled
    or on any error.
    """
    return generate(
        "As an advisory analyst (read-only), suggest 2 decomposition angles "
        f"to further investigate this confirmed drift. Claim: {claim}. "
        f"Evidence: {rationale}."
    )[0]
