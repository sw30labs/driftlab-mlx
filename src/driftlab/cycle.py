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
from .sensor import ResourceRecord, cumulative_spend


@dataclass
class CycleResult:
    agent: str
    cycle_id: str
    baseline_hash: str
    trace_hash: str
    score: int
    anomalies: list[Anomaly] = field(default_factory=list)
    experiments: list[dict[str, Any]] = field(default_factory=list)
    # DL-8: identity + summary of the resource stream, when one was observed.
    # Empty/None when no telemetry — keeps legacy ledgers byte-identical.
    resource_hash: str = ""
    resource_summary: dict[str, Any] | None = None

    def to_ledger(self) -> dict[str, Any]:
        ledger = {
            "agent": self.agent,
            "cycle_id": self.cycle_id,
            "baseline_hash": self.baseline_hash,
            "trace_hash": self.trace_hash,
            "score": self.score,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "experiments": self.experiments,
        }
        if self.resource_hash:
            ledger["resource_hash"] = self.resource_hash
        if self.resource_summary is not None:
            ledger["resource"] = self.resource_summary
        return ledger


def run_cycle(
    agent: str,
    profile_path: str,
    events: list[DecisionEvent],
    waivers: Waiver | None = None,
    run_experiments: bool = True,
    resource_records: list[ResourceRecord] | None = None,
) -> CycleResult:
    profile = load_profile(profile_path)
    policy = BaselineCompiler().compile(profile)
    diff = BehavioralDiff(policy, events, resource_records=resource_records)
    findings = diff.run()
    anomalies = AnomalyEngine(waivers).build(findings, diff=diff)
    score = AnomalyEngine.score(anomalies)

    # Fidelity confound annotation (ADR-001): when the sensor reports any
    # degraded fidelity in this window, every finding is annotated so
    # certified shedding is distinguishable from real drift. Deterministic:
    # derived only from the recorded stream. Post-build, so fingerprints and
    # anomaly ids are unaffected.
    fidelity_observed = sorted({r.fidelity for r in resource_records or []})
    if resource_records and any(f != "full" for f in fidelity_observed):
        for a in anomalies:
            a.extra["fidelity_observed"] = fidelity_observed

    trace_hash = _trace_hash(events)
    resource_hash = (
        "" if resource_records is None
        else _resource_hash(resource_records)
    )
    cid = cycle_id(agent, policy.baseline_hash, trace_hash, resource_hash)

    experiments: list[dict[str, Any]] = []
    if run_experiments:
        for a in anomalies:
            if a.waived or a.severity.value in ("info", "low"):
                continue
            outcome = run_experiment(generate(a, policy), events,
                                     resource_records=resource_records or [])
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

    resource_summary = None
    if resource_records is not None:
        resource_summary = {
            "records": len(resource_records),
            "spent": dict(sorted(cumulative_spend(resource_records).items())),
            "ceilings": dict(sorted(policy.resource_ceilings.items())),
            "fidelity_observed": fidelity_observed,
            "breaker_fired": any(bool(r.tripped) for r in resource_records),
        }

    return CycleResult(
        agent=agent,
        cycle_id=cid,
        baseline_hash=policy.baseline_hash,
        trace_hash=trace_hash,
        score=score,
        anomalies=anomalies,
        experiments=experiments,
        resource_hash=resource_hash,
        resource_summary=resource_summary,
    )


def _trace_hash(events: list[DecisionEvent]) -> str:
    from .identity import stable_json_digest
    return stable_json_digest([e.model_dump(mode="json") for e in events])


def _resource_hash(records: list[ResourceRecord]) -> str:
    from .identity import stable_json_digest
    return stable_json_digest([r.model_dump(mode="json") for r in records])