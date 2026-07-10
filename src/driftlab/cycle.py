"""One full compliance cycle, end to end.

A cycle takes an agent, its certified baseline, and its observed trace, and
produces: the anomaly ledger, the compliance score, the experiment outcomes,
and (via the emit layer) OSCAL + markdown artifacts. It is deterministic: the
same (baseline, trace) yields the same cycle id and byte-identical ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .anomaly import Anomaly, AnomalyEngine, Waiver
from .baseline import BaselineCompiler, load_profile
from .diff import BehavioralDiff
from .domain import BaselinePolicy, DecisionEvent
from .experiment.hypothesis import generate
from .experiment.loop import Verdict, run_experiment
from .identity import cycle_id


@dataclass
class CycleResult:
    agent: str
    cycle_id: str
    baseline_hash: str
    trace_hash: str
    score: int
    anomalies: list[Anomaly] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)

    def to_ledger(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "cycle_id": self.cycle_id,
            "baseline_hash": self.baseline_hash,
            "trace_hash": self.trace_hash,
            "score": self.score,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "experiments": self.experiments,
        }


def run_cycle(
    agent: str,
    profile_path: str,
    events: list[DecisionEvent],
    waivers: Waiver | None = None,
    run_experiments: bool = True,
) -> CycleResult:
    profile = load_profile(profile_path)
    policy = BaselineCompiler().compile(profile)
    diff = BehavioralDiff(policy, events)
    findings = diff.run()
    anomalies = AnomalyEngine(waivers).build(findings, diff=diff)
    score = AnomalyEngine.score(anomalies)

    trace_hash = _trace_hash(events)
    cid = cycle_id(agent, policy.baseline_hash, trace_hash)

    experiments: list[dict[str, Any]] = []
    if run_experiments:
        for a in anomalies:
            if a.waived or a.severity.value in ("info", "low"):
                continue
            outcome = run_experiment(generate(a, policy), events)
            experiments.append({
                "anomaly_id": outcome.anomaly_id,
                "control": a.control,
                "verdict": outcome.verdict.value,
                "rationale": outcome.rationale,
                "probe": {
                    "kind": outcome.probe.kind,
                    "samples": outcome.probe.samples,
                    "violations": outcome.probe.violations,
                    "detail": outcome.probe.detail,
                },
            })

    return CycleResult(
        agent=agent,
        cycle_id=cid,
        baseline_hash=policy.baseline_hash,
        trace_hash=trace_hash,
        score=score,
        anomalies=anomalies,
        experiments=experiments,
    )


def _trace_hash(events: list[DecisionEvent]) -> str:
    from .identity import stable_json_digest
    return stable_json_digest([e.model_dump(mode="json") for e in events])