"""The micro-experiment loop: hypothesize -> design -> execute -> evaluate -> reflect.

LangGraph StateGraph with setpoint's routing-gate pattern and regitel's
dependency-binding-via-partial. The verdict is computed *deterministically*
from probe evidence — CONFIRMED/REFUTED can never come from an LLM (design
principle #1). When an LLM is configured, ``driftlab.experiment.deep_agent``
adds an advisory DeepAgents pass on top; it can annotate, never decide.
"""

from __future__ import annotations

import logging
import operator
from functools import partial
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from driftlab.baseline.model import BaselinePolicy
from driftlab.domain.models import (
    DriftHypothesis,
    ExperimentRecord,
    ProbeResult,
    Verdict,
)
from driftlab.experiment.probes import RATE_KINDS, design_probe, execute_probe
from driftlab.experiment.sandbox import Sandbox

logger = logging.getLogger(__name__)


class ExperimentState(TypedDict, total=False):
    hypothesis: DriftHypothesis
    probe_spec: dict[str, Any]
    probes: Annotated[list[ProbeResult], operator.add]
    notes: Annotated[list[str], operator.add]
    validity_score: float
    verdict: str | None
    iteration: int
    max_iterations: int
    min_probe_samples: int
    confirm_threshold: float
    refute_threshold: float


# -- nodes ---------------------------------------------------------------------
def design_node(state: ExperimentState) -> dict:
    spec = design_probe(state["hypothesis"], state.get("iteration", 0))
    return {"probe_spec": spec, "notes": [f"iteration {state.get('iteration', 0) + 1}: designed probe {spec.get('probe_kind')} (scope {spec.get('scope')})"]}


def execute_node(state: ExperimentState, *, sandbox: Sandbox, policy: BaselinePolicy) -> dict:
    result = execute_probe(
        sandbox=sandbox,
        hypothesis=state["hypothesis"],
        policy=policy,
        probe_spec=state["probe_spec"],
    )
    return {
        "probes": [result],
        "notes": [
            f"probe {result.probe_id}: {result.violations}/{result.samples} "
            f"violations (rate {result.violation_rate})"
        ],
    }


def evaluate_node(state: ExperimentState) -> dict:
    """Deterministic verdict from probe evidence.

    Existence claims: one independently reproduced violation is proof;
    zero violations across enough samples is refutation.
    Rate claims: the fraction of ordered windows exceeding the budget is the
    validity — sustained drift confirms, uniformly-within-budget refutes.
    """
    hypothesis = state["hypothesis"]
    probes = state.get("probes", [])
    last = probes[-1]
    min_samples = state.get("min_probe_samples", 3)
    confirm = state.get("confirm_threshold", 0.7)
    refute = state.get("refute_threshold", 0.05)

    verdict: str | None = None
    if hypothesis.kind in RATE_KINDS:
        validity = last.violation_rate  # fraction of windows exceeding budget
        if last.samples >= 2:
            if validity >= confirm:
                verdict = Verdict.CONFIRMED.value
            elif validity <= refute:
                verdict = Verdict.REFUTED.value
    else:
        total_violations = sum(p.violations for p in probes)
        validity = 1.0 if total_violations > 0 else 0.0
        if total_violations > 0:
            verdict = Verdict.CONFIRMED.value
        elif last.samples >= min_samples:
            verdict = Verdict.REFUTED.value

    return {
        "validity_score": round(validity, 4),
        "verdict": verdict,
        "iteration": state.get("iteration", 0) + 1,
    }


def reflect_node(state: ExperimentState) -> dict:
    return {
        "notes": [
            f"inconclusive after iteration {state.get('iteration', 0)} "
            f"(samples={state['probes'][-1].samples}); widening probe scope"
        ]
    }


def route_after_evaluate(state: ExperimentState) -> str:
    if state.get("verdict"):
        return "done"
    if state.get("iteration", 0) >= state.get("max_iterations", 3):
        return "done"
    return "reflect"


# -- graph -----------------------------------------------------------------------
def build_experiment_graph(*, sandbox: Sandbox, policy: BaselinePolicy):
    graph = StateGraph(ExperimentState)
    graph.add_node("design", design_node)
    graph.add_node("execute", partial(execute_node, sandbox=sandbox, policy=policy))
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("reflect", reflect_node)

    graph.add_edge(START, "design")
    graph.add_edge("design", "execute")
    graph.add_edge("execute", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluate, {"done": END, "reflect": "reflect"})
    graph.add_edge("reflect", "design")
    return graph.compile()


def run_experiment(
    hypothesis: DriftHypothesis,
    *,
    sandbox: Sandbox,
    policy: BaselinePolicy,
    max_iterations: int = 3,
    min_probe_samples: int = 3,
    confirm_threshold: float = 0.7,
    refute_threshold: float = 0.05,
) -> ExperimentRecord:
    sandbox.assert_isolated()
    graph = build_experiment_graph(sandbox=sandbox, policy=policy)
    initial: ExperimentState = {
        "hypothesis": hypothesis,
        "iteration": 0,
        "max_iterations": max_iterations,
        "min_probe_samples": min_probe_samples,
        "confirm_threshold": confirm_threshold,
        "refute_threshold": refute_threshold,
    }
    recursion_limit = max(25, max_iterations * 4 + 10)
    final = graph.invoke(initial, config={"recursion_limit": recursion_limit})
    verdict = Verdict(final["verdict"]) if final.get("verdict") else Verdict.INCONCLUSIVE
    return ExperimentRecord(
        hypothesis=hypothesis,
        verdict=verdict,
        validity_score=float(final.get("validity_score", 0.0)),
        iterations=int(final.get("iteration", 0)),
        probes=list(final.get("probes", [])),
        notes=list(final.get("notes", [])),
    )


def run_experiments(
    hypotheses: list[DriftHypothesis],
    *,
    sandbox: Sandbox,
    policy: BaselinePolicy,
    **kwargs: Any,
) -> list[ExperimentRecord]:
    """Batch with per-item isolation (regitel batch-orchestrator contract):
    one experiment's failure never kills the cycle."""
    records: list[ExperimentRecord] = []
    for hypothesis in hypotheses:
        try:
            records.append(run_experiment(hypothesis, sandbox=sandbox, policy=policy, **kwargs))
        except Exception as exc:  # never propagate — record and continue
            logger.error("experiment %s failed: %s", hypothesis.hypothesis_id, exc)
            records.append(
                ExperimentRecord(
                    hypothesis=hypothesis,
                    verdict=Verdict.INCONCLUSIVE,
                    validity_score=0.0,
                    iterations=0,
                    notes=[f"experiment failed: {type(exc).__name__}: {exc}"],
                )
            )
    return records
