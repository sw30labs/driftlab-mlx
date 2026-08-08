"""Background job runner for the web command deck.

One compliance job at a time — the SQLite store is single-writer and a cycle
upserts. Narrative jobs take a second, independent slot: an advisory LLM call
is not part of the compliance path and must never queue behind, or block, a
cycle.

The HTTP layer polls; the worker thread pushes progress into a live ring
buffer via the monitor runner's ``on_event`` hook.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "busy",
    "narrative_busy",
    "active_job_id",
    "get_job",
    "list_jobs",
    "live_events",
    "start_cycle_job",
    "start_narrative_job",
    "narrative_for",
    "llm_status",
]

_MAX_LIVE_EVENTS = 500
_MAX_JOBS = 25

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_CYCLE_BUSY = threading.Lock()
_NARRATIVE_BUSY = threading.Lock()

_LIVE: dict[str, Any] = {
    "events": deque(maxlen=_MAX_LIVE_EVENTS),
    "active_job_id": None,
}
_LIVE_LOCK = threading.Lock()

# agent id -> {"status", "text", "model", "at", "error"}
_NARRATIVES: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def busy() -> bool:
    return _CYCLE_BUSY.locked()


def narrative_busy() -> bool:
    return _NARRATIVE_BUSY.locked()


def active_job_id() -> str | None:
    with _LIVE_LOCK:
        return _LIVE.get("active_job_id")


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = _MAX_JOBS) -> list[dict[str, Any]]:
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j.get("started_at") or "", reverse=True)
        return [dict(j) for j in jobs[:limit]]


def live_events(limit: int = 100) -> list[dict[str, Any]]:
    with _LIVE_LOCK:
        events = list(_LIVE["events"])
    return events[-limit:]


def llm_status() -> dict[str, Any]:
    """Advisory-LLM backend health (OMLX). Never raises."""
    from ..llm import probe

    status = probe()
    status["narrative_busy"] = narrative_busy()
    return status


# -- job bookkeeping ------------------------------------------------------


def _register(job_id: str, phase: str, params: dict[str, Any]) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "phase": phase,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "result": None,
            "error": None,
            "params": params,
            "progress": {"stage": "starting", "agent": None, "note": "", "events": 0},
        }
        if len(_JOBS) > _MAX_JOBS:
            stale = sorted(_JOBS, key=lambda k: _JOBS[k]["started_at"])
            for old in stale[: len(_JOBS) - _MAX_JOBS]:
                if _JOBS[old]["status"] != "running":
                    del _JOBS[old]


def _finish(job_id: str, status: str, result: Any, error: str | None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(status=status, result=result, error=error, finished_at=_now())


def _publish(job_id: str, event: dict[str, Any]) -> None:
    entry = {"at": _now(), **event}
    with _LIVE_LOCK:
        _LIVE["events"].append(entry)
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        progress = job.setdefault("progress", {})
        progress["events"] = int(progress.get("events") or 0) + 1
        kind = event.get("kind", "")
        if "agent" in event:
            progress["agent"] = event["agent"]
        if kind in ("agent.started", "trace.loaded", "resource.loaded", "cycle.scored"):
            progress["stage"] = kind
        if kind == "agent.started":
            # Notes are per-agent; carrying one over would show the previous
            # agent's score against the one now being checked.
            progress["note"] = ""
        if kind == "experiment.verdict":
            progress["stage"] = "experiment"
            progress["note"] = f"{event.get('control')} → {event.get('verdict')}"
        elif kind == "cycle.scored":
            progress["note"] = (f"score {event.get('score')}/100 · "
                                f"{event.get('anomalies')} active anomalies")
        elif kind == "agent.error":
            progress["stage"] = "error"
            progress["note"] = f"ERROR: {event.get('error', '?')}"
        elif kind == "estate.finished":
            progress["stage"] = "done"
            progress["note"] = (f"ran {event.get('ran')} · skipped {event.get('skipped')} "
                                f"· errors {event.get('errors')}")


# -- compliance cycle job -------------------------------------------------


def start_cycle_job(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """Launch an estate or single-agent compliance cycle.

    Returns ``(job_id, None)`` on success or ``(None, error)``.
    """
    agent = str(params.get("agent") or "").strip()
    scope = str(params.get("scope") or ("agent" if agent else "estate")).strip().lower()
    if scope not in ("estate", "agent"):
        return None, "scope must be 'estate' or 'agent'"
    if scope == "agent" and not agent:
        return None, "agent is required when scope is 'agent'"

    from .state import load_agents

    known = {a.id for a in load_agents()}
    if not known:
        return None, "no agents in the registry"
    if scope == "agent" and agent not in known:
        return None, f"unknown agent {agent!r}"

    if not _CYCLE_BUSY.acquire(blocking=False):
        return None, "another cycle is still running — wait for it to finish"

    job_id = f"dl-{uuid.uuid4().hex[:8]}"
    settings = {
        "scope": scope,
        "agent": agent or None,
        "force": bool(params.get("force", True)),
        "experiments": bool(params.get("experiments", True)),
        "narrative": bool(params.get("narrative")),
    }
    try:
        _register(job_id, "cycle", settings)
        with _LIVE_LOCK:
            _LIVE["active_job_id"] = job_id
            _LIVE["events"].clear()
        threading.Thread(target=_run_cycle, args=(job_id, settings), daemon=True).start()
    except BaseException:
        _finish(job_id, "error", None, "failed to start job thread")
        _CYCLE_BUSY.release()
        raise
    return job_id, None


def _run_cycle(job_id: str, params: dict[str, Any]) -> None:
    from ..monitor.runner import run_estate

    try:
        try:
            summary = run_estate(
                force=params["force"],
                no_email=True,
                run_experiments=params["experiments"],
                only=[params["agent"]] if params["scope"] == "agent" else None,
                on_event=lambda event: _publish(job_id, event),
            )
            status, error = ("error" if summary["errors"] else "done"), None
            if summary["errors"]:
                error = "; ".join(f"{e['agent']}: {e['error']}" for e in summary["errors"])
            _finish(job_id, status, summary, error)
            if params.get("narrative") and status == "done":
                for ran in summary["ran"]:
                    start_narrative_job(ran["agent"])
                    break  # one advisory narrative per run; the slot is single
        except Exception as exc:
            _publish(job_id, {"kind": "agent.error", "error": str(exc)})
            _finish(job_id, "error", None, str(exc))
    finally:
        with _LIVE_LOCK:
            if _LIVE.get("active_job_id") == job_id:
                _LIVE["active_job_id"] = None
        _CYCLE_BUSY.release()


# -- advisory narrative job ----------------------------------------------


def narrative_for(agent: str) -> dict[str, Any]:
    """Last advisory narrative generated for an agent, if any."""
    return dict(_NARRATIVES.get(agent) or {"status": "none", "text": "", "agent": agent})


def start_narrative_job(agent: str) -> tuple[str | None, str | None]:
    """Generate an advisory LLM narrative for an agent's latest cycle.

    Advisory only: the narrative is never persisted into a ledger and never
    influences a score, a severity, or a verdict.
    """
    from ..llm import is_enabled

    agent = str(agent or "").strip()
    if not agent:
        return None, "agent is required"
    if not is_enabled():
        return None, ("advisory LLM is disabled — set DRIFTLAB_LLM_PROVIDER=omlx "
                      "to enable narratives")

    from .state import agent_detail

    detail = agent_detail(agent)
    if detail is None:
        return None, f"unknown agent {agent!r}"
    if not detail.get("ledger"):
        return None, f"{agent} has no cycle yet — run a check first"

    if not _NARRATIVE_BUSY.acquire(blocking=False):
        return None, "a narrative is already being generated"

    job_id = f"nar-{uuid.uuid4().hex[:8]}"
    try:
        _register(job_id, "narrative", {"agent": agent})
        _NARRATIVES[agent] = {"agent": agent, "status": "running", "text": "",
                              "at": _now(), "error": None}
        threading.Thread(
            target=_run_narrative, args=(job_id, agent, detail["ledger"]), daemon=True
        ).start()
    except BaseException:
        _finish(job_id, "error", None, "failed to start narrative thread")
        _NARRATIVE_BUSY.release()
        raise
    return job_id, None


def _run_narrative(job_id: str, agent: str, ledger: dict[str, Any]) -> None:
    from ..config import get_settings
    from ..llm import executive_narrative_detailed

    try:
        _publish(job_id, {"kind": "narrative.started", "agent": agent})
        text, error = executive_narrative_detailed(ledger)
        model = get_settings().omlx_model
        if text:
            _NARRATIVES[agent] = {"agent": agent, "status": "done", "text": text,
                                  "model": model, "at": _now(), "error": None}
            _finish(job_id, "done", {"agent": agent, "chars": len(text)}, None)
            _publish(job_id, {"kind": "narrative.finished", "agent": agent,
                              "note": f"{len(text)} chars via {model}"})
        else:
            error = error or "advisory LLM returned nothing"
            _NARRATIVES[agent] = {"agent": agent, "status": "error", "text": "",
                                  "model": model, "at": _now(), "error": error}
            _finish(job_id, "error", None, error)
            _publish(job_id, {"kind": "narrative.failed", "agent": agent, "error": error})
    finally:
        _NARRATIVE_BUSY.release()
