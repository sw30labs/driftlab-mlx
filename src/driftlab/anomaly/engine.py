"""Anomaly engine: deviations -> severity -> waivers -> score.

Severity is a deterministic function of (drift kind x critical-sink
reachability x magnitude) — glass-graph's tag-driven escalation, re-aimed at
behavior. A CRITICAL fires because the diff engine found a certified control
violated on a path that reaches a critical sink, never because an LLM
"thought" something looked wrong. Waiver capping and the 35/20/8/3/1 scoring
weights are ported from glass-graph verbatim.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from driftlab.baseline.model import BaselinePolicy
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.domain.models import (
    SEVERITY_WEIGHTS,
    AnomalyRecord,
    DeviationRecord,
    DriftKind,
    Severity,
)


class AnomalyEngine:
    def build_anomalies(
        self,
        *,
        policy: BaselinePolicy,
        deviations: list[DeviationRecord],
        graph: BehaviorGraph,
        now: datetime | None = None,
    ) -> list[AnomalyRecord]:
        anomalies: list[AnomalyRecord] = []
        for deviation in sorted(deviations, key=lambda d: d.fingerprint):
            severity = self._resolve_severity(deviation, policy, graph)
            waiver_status: str = "none"
            description = deviation.description
            for waiver in policy.waivers:
                if waiver.applies(deviation.fingerprint, now):
                    if SEVERITY_WEIGHTS[waiver.severity_cap.value] < SEVERITY_WEIGHTS[severity.value]:
                        severity = waiver.severity_cap
                    waiver_status = "waived"
                    description = f"{description} (waived: {waiver.title})"
                    break
            impacted_paths = [
                graph.path_impact(node, policy.critical_sinks)
                for node in sorted(set(deviation.impacted_nodes))
            ]
            anomalies.append(
                AnomalyRecord(
                    comparison_type=deviation.comparison_type,
                    severity=severity,
                    kind=deviation.kind,
                    fingerprint=deviation.fingerprint,
                    control_id=deviation.control_id,
                    title=deviation.title,
                    description=description,
                    impacted_nodes=sorted(set(deviation.impacted_nodes)),
                    impacted_routes=sorted(set(deviation.impacted_routes)),
                    impacted_paths=impacted_paths,
                    evidence=deviation.evidence,
                    measurement=deviation.measurement,
                    waiver_status=waiver_status,  # type: ignore[arg-type]
                )
            )
        return anomalies

    # -- deterministic severity table -----------------------------------------
    def _resolve_severity(
        self, deviation: DeviationRecord, policy: BaselinePolicy, graph: BehaviorGraph
    ) -> Severity:
        sinks = policy.critical_sinks
        touches_sink = any(node in sinks for node in deviation.impacted_nodes)
        reaches_sink = touches_sink or any(
            graph.reaches(node, sinks) for node in deviation.impacted_nodes
        )

        kind = deviation.kind
        if kind is DriftKind.UNEXPECTED_TOOL_CALL:
            tool = str(deviation.measurement.get("tool", ""))
            if tool in sinks or touches_sink:
                return Severity.CRITICAL
            return Severity.HIGH if reaches_sink else Severity.MEDIUM
        if kind is DriftKind.UNAUTHORIZED_ROUTE:
            return Severity.CRITICAL if reaches_sink else Severity.HIGH
        if kind is DriftKind.MISSING_HITL:
            return Severity.CRITICAL if reaches_sink else Severity.HIGH
        if kind is DriftKind.AUTONOMY_BUDGET_EXCEEDED:
            overshoot = float(deviation.measurement.get("overshoot", 0.0))
            return Severity.HIGH if overshoot >= 0.10 else Severity.MEDIUM
        if kind is DriftKind.FALLBACK_VIOLATION:
            return Severity.HIGH if reaches_sink else Severity.MEDIUM
        if kind is DriftKind.MISSING_STEP:
            return Severity.HIGH if reaches_sink else Severity.MEDIUM
        if kind is DriftKind.FREQUENCY_DRIFT:
            return Severity.MEDIUM
        return Severity.LOW  # EVIDENCE_QUALITY and anything unmapped

    # -- scoring (glass-graph `_score`, ported verbatim) -------------------------
    @staticmethod
    def score(anomalies: list[AnomalyRecord]) -> tuple[float, dict[str, int]]:
        counts: Counter[str] = Counter(a.severity.value for a in anomalies)
        penalty = sum(SEVERITY_WEIGHTS.get(key, 0) * value for key, value in counts.items())
        return max(0.0, round(100.0 - penalty, 1)), dict(sorted(counts.items()))
