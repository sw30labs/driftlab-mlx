"""Deterministically (re)generate the seed demo traces.

Run:  python seed/generate_traces.py
No randomness — the JSONL files are a pure function of this script, so the
E2E determinism tests can rely on their content.

loan-officer-drifted.jsonl encodes four known drifts against the certified
baseline (see seed/baselines/loan-officer-profile.json):
  * 5 of 8 high-value runs bypass the hitl_review gate    -> MISSING_HITL (critical)
  * 13 of 20 routing decisions go full-autonomy (65%>40%) -> AUTONOMY_BUDGET_EXCEEDED (high)
  * 2 runs call the unvetted 'external_data_broker' tool  -> UNEXPECTED_TOOL_CALL (high)
  * 1 error at 'assess' continues without the fallback    -> FALLBACK_VIOLATION (high)
loan-officer-clean.jsonl and support-triage-clean.jsonl are fully compliant.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACES = HERE / "traces"

BASE_TS = "2026-07-08T0{h}:{m:02d}:00Z"


def _ts(i: int) -> str:
    return BASE_TS.format(h=(i // 60) % 10, m=i % 60)


def loan_run(run_id: str, amount: int, risk: str, path: str, *, bad_tool: bool = False,
             error_then: str | None = None, tick: int = 0) -> list[dict]:
    """One loan-officer run. path: 'auto' | 'hitl' | 'refuse'."""
    ctx = {"amount": amount, "risk": risk}
    ev: list[dict] = []
    seq = 0

    def add(event_type: str, node: str, **kw):
        nonlocal seq
        ev.append({"agent_id": "loan-officer", "run_id": run_id, "seq": seq,
                   "event_type": event_type, "node": node, "ts": _ts(tick * 20 + seq), **kw})
        seq += 1

    add("node_enter", "intake", decision_context=ctx)
    add("tool_call", "intake", tool="doc_parse")
    add("route", "intake", target="assess")
    add("node_enter", "assess", decision_context=ctx)
    add("tool_call", "assess", tool="credit_check")
    if bad_tool:
        add("tool_call", "assess", tool="external_data_broker")
    if error_then is not None:
        add("error", "assess", attrs={"error": "CreditBureauTimeout"})
        if error_then == "fallback":
            add("route", "assess", target="escalate_human")
            add("node_enter", "escalate_human")
            add("output_commit", "escalate_human")
            return ev
        # error_then == "continue": drift — proceed as if nothing happened
    if path == "auto":
        add("route", "assess", target="auto_approve", decision_context=ctx)
        add("node_enter", "auto_approve")
        add("tool_call", "auto_approve", tool="draft_offer")
        add("route", "auto_approve", target="disburse_funds")
        add("node_enter", "disburse_funds")
        add("route", "disburse_funds", target="notify_customer")
        add("node_enter", "notify_customer")
        add("output_commit", "notify_customer")
    elif path == "hitl":
        add("route", "assess", target="hitl_review", decision_context=ctx)
        add("node_enter", "hitl_review")
        add("hitl", "hitl_review")
        add("tool_call", "hitl_review", tool="draft_offer")
        add("route", "hitl_review", target="disburse_funds")
        add("node_enter", "disburse_funds")
        add("route", "disburse_funds", target="notify_customer")
        add("node_enter", "notify_customer")
        add("output_commit", "notify_customer")
    else:  # refuse
        add("route", "assess", target="hitl_review", decision_context=ctx)
        add("node_enter", "hitl_review")
        add("hitl", "hitl_review")
        add("route", "hitl_review", target="refuse")
        add("node_enter", "refuse")
        add("output_commit", "refuse")
    return ev


def triage_run(run_id: str, sentiment: str, path: str, tick: int = 0) -> list[dict]:
    ctx = {"sentiment": sentiment}
    ev: list[dict] = []
    seq = 0

    def add(event_type: str, node: str, **kw):
        nonlocal seq
        ev.append({"agent_id": "support-triage", "run_id": run_id, "seq": seq,
                   "event_type": event_type, "node": node, "ts": _ts(tick * 20 + seq), **kw})
        seq += 1

    add("node_enter", "triage", decision_context=ctx)
    add("tool_call", "triage", tool="kb_search")
    if path == "faq":
        add("route", "triage", target="faq_reply", decision_context=ctx)
        add("node_enter", "faq_reply")
        add("tool_call", "faq_reply", tool="draft_reply")
        add("route", "faq_reply", target="send_reply")
    else:
        add("route", "triage", target="human_agent", decision_context=ctx)
        add("node_enter", "human_agent")
        add("hitl", "human_agent")
        add("tool_call", "human_agent", tool="draft_reply")
        add("route", "human_agent", target="send_reply")
    add("node_enter", "send_reply")
    add("output_commit", "send_reply")
    return ev


def build_loan_drifted() -> list[dict]:
    """20 runs. High-value (>50000): r03,r05,r08,r11,r14,r17,r19,r20.
    Violating high-value autos: r03,r08,r11,r17,r20 (5 of 8).
    Auto routes: 13 of 20 = 65% (budget 40%)."""
    runs: list[dict] = []
    spec: list[tuple[str, int, str, str, dict]] = [
        ("r01", 12000, "low", "auto", {}),
        ("r02", 8000, "low", "auto", {}),
        ("r03", 82000, "medium", "auto", {}),          # HITL bypass
        ("r04", 15000, "low", "auto", {}),
        ("r05", 96000, "medium", "hitl", {}),          # compliant high-value
        ("r06", 22000, "low", "auto", {"bad_tool": True}),
        ("r07", 31000, "medium", "hitl", {}),
        ("r08", 61000, "low", "auto", {}),             # HITL bypass
        ("r09", 18000, "low", "auto", {"error_then": "continue"}),  # fallback drift
        ("r10", 27000, "high", "hitl", {}),            # high-risk compliant
        ("r11", 75000, "medium", "auto", {}),          # HITL bypass
        ("r12", 9000, "medium", "refuse", {}),
        ("r13", 14000, "low", "auto", {"bad_tool": True}),
        ("r14", 58000, "low", "hitl", {}),             # compliant high-value
        ("r15", 20000, "low", "auto", {}),
        ("r16", 25000, "medium", "hitl", {"error_then": "fallback"}),  # compliant fallback
        ("r17", 88000, "medium", "auto", {}),          # HITL bypass
        ("r18", 11000, "low", "auto", {}),
        ("r19", 67000, "high", "hitl", {}),            # compliant high-value+risk
        ("r20", 71000, "low", "auto", {}),             # HITL bypass
    ]
    for tick, (rid, amount, risk, path, kw) in enumerate(spec):
        runs.extend(loan_run(rid, amount, risk, path, tick=tick, **kw))
    return runs


def build_loan_clean() -> list[dict]:
    """12 runs, fully compliant. Auto routes: 4 of 12 = 33% (budget 40%)."""
    runs: list[dict] = []
    spec: list[tuple[str, int, str, str, dict]] = [
        ("c01", 12000, "low", "auto", {}),
        ("c02", 64000, "medium", "hitl", {}),
        ("c03", 9000, "low", "auto", {}),
        ("c04", 88000, "low", "hitl", {}),
        ("c05", 23000, "medium", "hitl", {}),
        ("c06", 17000, "low", "auto", {}),
        ("c07", 54000, "high", "hitl", {}),
        ("c08", 31000, "medium", "refuse", {}),
        ("c09", 26000, "low", "hitl", {"error_then": "fallback"}),
        ("c10", 19000, "low", "auto", {}),
        ("c11", 72000, "medium", "hitl", {}),
        ("c12", 42000, "high", "hitl", {}),
    ]
    for tick, (rid, amount, risk, path, kw) in enumerate(spec):
        runs.extend(loan_run(rid, amount, risk, path, tick=tick, **kw))
    return runs


def build_triage_clean() -> list[dict]:
    """10 runs, compliant. FAQ autos: 6 of 10 = 60% (budget 70%)."""
    runs: list[dict] = []
    spec = [
        ("t01", "neutral", "faq"), ("t02", "happy", "faq"), ("t03", "angry", "human"),
        ("t04", "neutral", "faq"), ("t05", "neutral", "faq"), ("t06", "angry", "human"),
        ("t07", "happy", "faq"), ("t08", "neutral", "human"), ("t09", "neutral", "faq"),
        ("t10", "angry", "human"),
    ]
    for tick, (rid, sentiment, path) in enumerate(spec):
        runs.extend(triage_run(rid, sentiment, path, tick=tick))
    return runs


def write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    print(f"wrote {len(events):4d} events -> {path.relative_to(HERE.parent)}")


if __name__ == "__main__":
    write_jsonl(TRACES / "loan-officer-drifted.jsonl", build_loan_drifted())
    write_jsonl(TRACES / "loan-officer-clean.jsonl", build_loan_clean())
    write_jsonl(TRACES / "support-triage-clean.jsonl", build_triage_clean())
