"""Anomaly engine — turn raw diff findings into scored, waiver-aware anomalies.

Deterministic: identical (baseline, trace, waivers) always yields the same
anomaly ids, severities, and compliance score. No LLM is involved.

Scoring weights (per MEDIUM+ anomaly): critical 35, high 20, medium 8,
low 3, info 1. The compliance score starts at 100 and is reduced by the sum of
applicable weights, floored at 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain import Severity
from ..identity import anomaly_id, stable_json_digest
from ..diff import RawFinding

SEVERITY_WEIGHT = {
    Severity.CRITICAL: 35,
    Severity.HIGH: 20,
    Severity.MEDIUM: 8,
    Severity.LOW: 3,
    Severity.INFO: 1,
}

# Severity can be escalated by control semantics (e.g. DL-5 critical sink).( Shall I challenge this ?)
_CONTROL_BASE_SEVERITY = {
    "DL-1": Severity.HIGH,
    "DL-2": Severity.MEDIUM,
    "DL-3": Severity.CRITICAL,
    "DL-4": Severity.HIGH,
    "DL-5": Severity.CRITICAL,
    "DL-6": Severity.HIGH,
    "DL-7": Severity.MEDIUM,
    # DL-8 base is MEDIUM so "telemetry missing" lands MEDIUM; an actual
    # ceiling breach carries a "high" hint, which wins upward.
    "DL-8": Severity.MEDIUM,
}


@dataclass
class Anomaly:
    id: str
    control: str
    title: str
    detail: str
    severity: Severity
    evidence: list[str]
    fingerprint: str
    waived: bool = False
    waiver_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHT[self.severity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "control": self.control, "title": self.title,
            "detail": self.detail, "severity": self.severity.value,
            "evidence": self.evidence, "fingerprint": self.fingerprint,
            "waived": self.waived, "waiver_reason": self.waiver_reason,
            "extra": self.extra,
        }


class Waiver:
    def __init__(self, by_fingerprint: dict[str, str] | None = None):
        # fingerprint -> reason
        self.by_fingerprint = by_fingerprint or {}

    @classmethod
    def from_file(cls, path: str | None) -> "Waiver":
        if not path:
            return cls()
        import json
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text())
        return cls({k: v.get("reason", "") for k, v in data.items()})


class AnomalyEngine:
    def __init__(self, waivers: Waiver | None = None):
        self.waivers = waivers or Waiver()

    def _resolve_severity(self, finding: RawFinding) -> Severity:
        base = _CONTROL_BASE_SEVERITY.get(finding.control, Severity.MEDIUM)
        # The finding's own hint may be higher (e.g. DL-5 autonomous sink).
        hint = Severity(finding.severity_hint)
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return base if order.index(base) >= order.index(hint) else hint

    def build(self, findings: list[RawFinding], diff: "BehavioralDiff | None" = None) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        for f in findings:
            fp = self._fingerprint(f)
            sev = self._resolve_severity(f)
            waived = fp in self.waivers.by_fingerprint
            anomalies.append(Anomaly(
                id=anomaly_id(fp),
                control=f.control,
                title=f.title,
                detail=f.detail,
                severity=sev,
                evidence=f.evidence,
                fingerprint=fp,
                waived=waived,
                waiver_reason=self.waivers.by_fingerprint.get(fp),
                extra=f.extra,
            ))
        # DL-5: escalate severity when a violation's evidence reaches a
        # certified critical sink (irreversible action).
        if diff is not None:
            self.apply_critical_sink_escalation(anomalies, diff)
        # Deterministic ordering by severity desc then control.
        anomalies.sort(key=lambda a: (-SEVERITY_WEIGHT[a.severity], a.control, a.id))
        return anomalies

    @staticmethod
    def apply_critical_sink_escalation(anomalies: list[Anomaly], diff: "BehavioralDiff") -> None:
        sinks = set(diff.policy.critical_sinks)
        if not sinks:
            return
        by_id = {e.id: e for e in diff.events}
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        for a in anomalies:
            reaches_sink = any(
                by_id[eid].node in sinks for eid in a.evidence if eid in by_id
            )
            if reaches_sink and a.severity != Severity.CRITICAL:
                a.severity = Severity.CRITICAL
                a.extra["dl5_escalated"] = True

    def _fingerprint(self, f: RawFinding) -> str:
        return stable_json_digest({
            "control": f.control, "title": f.title, "detail": f.detail,
            "evidence": sorted(f.evidence), "extra": f.extra,
        })

    @staticmethod
    def score(anomalies: list[Anomaly]) -> int:
        penalty = sum(a.weight for a in anomalies if not a.waived)
        return max(0, 100 - penalty)