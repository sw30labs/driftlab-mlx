"""Micro-experiment loop — prove or refute a drift hypothesis with evidence.

This is DriftLab's differentiator. Instead of merely *flagging* a suspected
drift, the loop *proves* it: it designs a controlled probe, executes it against
the **sandboxed replay** of the agent (never the live system), evaluates the
evidence, and reflects on whether the claim is CONFIRMED / REFUTED /
INCONCLUSIVE.

The orchestration is a LangGraph StateGraph (design -> execute -> evaluate ->
reflect). The verdict itself is computed deterministically from probe counts —
no LLM is involved in the verdict. An optional advisory LLM pass (DeepAgents
style) may enrich the narrative but cannot change a verdict.

Bounded by construction: a fixed max number of probe designs and iterations.
The sandbox is replay-only; the test suite proves the loop cannot reach the
network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..domain import DecisionEvent
from ..sensor import Sensor
from .hypothesis import ClaimKind, Hypothesis, Verdict, _build_predicate
from .sandbox import ProbeResult, ReplaySandbox


@dataclass
class ExperimentState:
    hypothesis: Hypothesis | None = None
    sandbox: ReplaySandbox | None = None
    # Recorded resource stream for RESOURCE (DL-8) claims — replay-only, like
    # the event sandbox; the loop never reads live telemetry.
    resource_records: list = field(default_factory=list)
    probe_results: list[ProbeResult] = field(default_factory=list)
    verdict: str = ""
    rationale: str = ""
    iterations: int = 0


def _design_probe(state: ExperimentState) -> dict[str, Any]:
    # A single, well-scoped probe per hypothesis (bounded). The "design" is to
    # materialize the replay predicate and decide the claim kind.
    hypo = state.hypothesis
    state.iterations += 1
    return {"iterations": state.iterations}


def _execute_probe(state: ExperimentState) -> dict[str, Any]:
    hypo = state.hypothesis
    sb = state.sandbox
    if hypo.kind == ClaimKind.RESOURCE:
        records = state.resource_records or []
        currency = hypo.predicate_spec.get("currency")
        ceiling = hypo.predicate_spec.get("ceiling")
        if currency is None or ceiling is None:
            res = ProbeResult(
                probe_id=f"p{hypo.anomaly_id[-4:]}", claim=hypo.claim, kind="resource",
                samples=len(records), violations=0,
                detail=f"{len(records)} resource record(s) available for certified ceilings")
        else:
            over = [r for r in records if float(r.spent.get(currency, 0.0)) > float(ceiling)]
            res = ProbeResult(
                probe_id=f"p{hypo.anomaly_id[-4:]}", claim=hypo.claim, kind="resource",
                samples=len(records), violations=len(over),
                detail=f"{len(over)}/{len(records)} replayed resource records show "
                       f"{currency} over ceiling {float(ceiling):g}")
        return {"probe_results": [res]}
    if hypo.kind == ClaimKind.EXISTENCE:
        predicate = _build_predicate(hypo.predicate_spec)
        matched = sb.matching(predicate)
        violations = len(matched)
        res = ProbeResult(
            probe_id=f"p{hypo.anomaly_id[-4:]}", claim=hypo.claim, kind="existence",
            samples=len(sb.events), violations=violations,
            detail=f"{violations} matching violation(s) in {len(sb.events)} replayed events")
    else:  # RATE
        decision_nodes = set(hypo.predicate_spec.get("decision_nodes", []))
        budget = hypo.rate_threshold or 1.0
        w = hypo.window_size or 5
        # Walk the event stream in order; each decision-point (autonomous tool at a
        # decision node) or human-authority event advances the sequence. Group into
        # windows and compute autonomy rate per window.
        seq = [e for e in sb.events
               if (e.kind.value == "tool_call" and e.node in decision_nodes)
               or e.kind.value in ("hitl", "refusal", "escalation")]
        windows = [seq[i:i + w] for i in range(0, len(seq), w)] or [[]]
        over_windows = 0
        for win in windows:
            auto = sum(1 for e in win if e.kind.value == "tool_call" and e.node in decision_nodes)
            human = sum(1 for e in win if e.kind.value in ("hitl", "refusal", "escalation"))
            tot = auto + human
            if tot == 0:
                continue
            if (auto / tot) > budget:
                over_windows += 1
        violations = over_windows
        res = ProbeResult(
            probe_id=f"p{hypo.anomaly_id[-4:]}", claim=hypo.claim, kind="rate",
            samples=len(seq), violations=violations,
            detail=f"{over_windows}/{len(windows)} decision windows sustain excess over "
                   f"budget {budget:.0%}")
    return {"probe_results": [res]}


def _evaluate(state: ExperimentState) -> dict[str, Any]:
    hypo = state.hypothesis
    res = state.probe_results[0]
    if hypo.kind == ClaimKind.EXISTENCE:
        if res.violations >= 1:
            verdict, rationale = Verdict.CONFIRMED, (
                f"probe reproduced the violation {res.violations}x on replay "
                f"({res.samples} events) -> claim holds with evidence")
        elif res.samples >= hypo.min_samples:
            verdict, rationale = Verdict.REFUTED, (
                f"probe examined {res.samples} events, zero violations -> claim refuted")
        else:
            verdict, rationale = Verdict.INCONCLUSIVE, "insufficient samples"
    elif hypo.kind == ClaimKind.RESOURCE:
        if res.samples == 0:
            verdict, rationale = Verdict.INCONCLUSIVE, (
                "no resource telemetry available to examine -> cannot verify the "
                "certified budget either way")
        elif res.violations >= 1:
            verdict, rationale = Verdict.CONFIRMED, (
                f"replayed stream shows {res.violations} record(s) with spend over "
                f"the certified ceiling -> breach holds with evidence")
        else:
            verdict, rationale = Verdict.REFUTED, (
                f"replayed stream ({res.samples} records) never crosses the "
                f"ceiling -> claim refuted")
    else:  # RATE
        if res.violations == 0:
            verdict, rationale = Verdict.REFUTED, "no window sustains the excess -> refuted"
        elif res.violations == 1:
            verdict, rationale = Verdict.INCONCLUSIVE, "single-window excess -> inconclusive (burst?)"
        else:
            verdict, rationale = Verdict.CONFIRMED, (
                f"{res.violations} windows sustain the autonomy excess -> confirmed")
    return {"verdict": verdict.value, "rationale": rationale}


def _reflect(state: ExperimentState) -> dict[str, Any]:
    # Terminal reflection is a no-op for verdict; it could attach an advisory
    # narrative. Verdict already set in evaluate.
    return {}


def build_graph() -> StateGraph:
    g = StateGraph(ExperimentState)
    g.add_node("design", _design_probe)
    g.add_node("execute", _execute_probe)
    g.add_node("evaluate", _evaluate)
    g.add_node("reflect", _reflect)
    g.add_edge(START, "design")
    g.add_edge("design", "execute")
    g.add_edge("execute", "evaluate")
    g.add_edge("evaluate", "reflect")
    g.add_edge("reflect", END)
    return g


_GRAPH = build_graph().compile()


@dataclass
class ExperimentOutcome:
    anomaly_id: str
    verdict: Verdict
    rationale: str
    probe: ProbeResult


def run_experiment(
    hypothesis: Hypothesis,
    events: list[DecisionEvent],
    resource_records: list | None = None,
) -> ExperimentOutcome:
    """Run one hypothesis to a deterministic verdict against a replay sandbox."""
    sandbox = ReplaySandbox(hypothesis and events[0].agent if events else "?", events)
    state = ExperimentState(hypothesis=hypothesis, sandbox=sandbox,
                            resource_records=resource_records or [])
    # Dogfood (ADR-001): the proof engine runs under the same telemetry
    # discipline it audits. Observe-only — no ceilings here, because a
    # CPU/wall breaker would make compliance verdicts machine-speed-
    # dependent; the telemetry plane never touches the deterministic
    # artifacts.
    sensor = Sensor("driftlab-experiment")
    with sensor.iteration(control=hypothesis.control, anomaly=hypothesis.anomaly_id):
        result = _GRAPH.invoke(state)
    res = result["probe_results"][0]
    return ExperimentOutcome(
        anomaly_id=hypothesis.anomaly_id,
        verdict=Verdict(result["verdict"]),
        rationale=result["rationale"],
        probe=res,
    )