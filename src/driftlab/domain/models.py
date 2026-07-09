"""Canonical domain models.

Ports the glass-graph spine (DeviationRecord -> AnomalyRecord, Severity,
WaiverDefinition, PathImpact) and generalizes it from graph *structure* to
runtime *behavior*. One deliberate upgrade over glass-graph: anomaly and
deviation IDs are deterministic (uuid5 of the fingerprint), never uuid4, so
the same drift keeps the same identity across cycles — enabling dedup and
first-seen/still-open lifecycle tracking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from driftlab.identity import content_hash, deterministic_id, deterministic_uuid


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: severity -> penalty weight (glass-graph `_score`, ported verbatim)
SEVERITY_WEIGHTS: dict[str, int] = {
    Severity.CRITICAL.value: 35,
    Severity.HIGH.value: 20,
    Severity.MEDIUM.value: 8,
    Severity.LOW.value: 3,
    Severity.INFO.value: 1,
}

SEVERITY_ORDER: dict[str, int] = {s.value: i for i, s in enumerate(Severity)}


class ComparisonType(str, Enum):
    """Which pair of evidence views produced a deviation."""

    OBSERVED_VS_BASELINE = "observed_vs_baseline"  # runtime traces vs certified OSCAL baseline
    DECLARED_VS_BASELINE = "declared_vs_baseline"  # declared graph/config vs baseline (optional 3rd way)
    OBSERVED_VS_DECLARED = "observed_vs_declared"


class DriftKind(str, Enum):
    """Behavioral deviation taxonomy (replaces glass-graph's structural kinds)."""

    UNEXPECTED_TOOL_CALL = "unexpected_tool_call"
    UNAUTHORIZED_ROUTE = "unauthorized_route"
    MISSING_HITL = "missing_hitl"
    AUTONOMY_BUDGET_EXCEEDED = "autonomy_budget_exceeded"
    FALLBACK_VIOLATION = "fallback_violation"
    MISSING_STEP = "missing_step"
    FREQUENCY_DRIFT = "frequency_drift"
    EVIDENCE_QUALITY = "evidence_quality"


class EventType(str, Enum):
    """Canonical decision-event vocabulary emitted by trace ingestors."""

    NODE_ENTER = "node_enter"
    TOOL_CALL = "tool_call"
    ROUTE = "route"
    HITL = "hitl"
    ESCALATION = "escalation"
    REFUSAL = "refusal"
    FALLBACK = "fallback"
    ERROR = "error"
    OUTPUT_COMMIT = "output_commit"


class Verdict(str, Enum):
    """Outcome of a micro-experiment. CONFIRMED/REFUTED are evidence-based
    and computed deterministically — never by an LLM."""

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------
# Trace layer
# --------------------------------------------------------------------------
class DecisionEvent(BaseModel):
    """One observed decision made by a running agent.

    ``event_id`` is a pure function of the decision content (agent, run, seq,
    what happened) — the timestamp is provenance, not identity, so replaying
    the same trace yields the same IDs.
    """

    agent_id: str
    run_id: str
    seq: int
    event_type: EventType
    node: str
    tool: str | None = None
    target: str | None = None  # route target node
    autonomy: Literal["auto", "assisted", "human"] | None = None
    decision_context: dict[str, Any] = Field(default_factory=dict)
    ts: str | None = None  # ISO timestamp — provenance only, excluded from identity
    attrs: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def event_id(self) -> str:
        key = content_hash(
            {
                "agent_id": self.agent_id,
                "run_id": self.run_id,
                "seq": self.seq,
                "event_type": self.event_type.value,
                "node": self.node,
                "tool": self.tool,
                "target": self.target,
                "autonomy": self.autonomy,
                "decision_context": self.decision_context,
            }
        )
        return deterministic_id("evt", key)


class EvidenceRef(BaseModel):
    """Provenance breadcrumb: which trace evidence supports a claim.

    Every anomaly must trace back to source events (twinops: provenance is
    load-bearing; nothing enters the ledger without a DERIVED_FROM path).
    """

    origin: str = "trace"  # trace | baseline | experiment
    event_ids: list[str] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    control_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Findings layer (two-tier, glass-graph pattern)
# --------------------------------------------------------------------------
class PathImpact(BaseModel):
    node_path: list[str] = Field(default_factory=list)
    reaches_critical_sink: bool = False
    blast_radius_nodes: list[str] = Field(default_factory=list)


class DeviationRecord(BaseModel):
    """Raw output of the behavioral diff engine (pre-severity, pre-waiver)."""

    comparison_type: ComparisonType
    kind: DriftKind
    fingerprint: str  # deterministic finding identity, e.g. "observed_vs_baseline:missing_hitl:DL-3:assess"
    control_id: str | None = None
    title: str
    description: str
    impacted_nodes: list[str] = Field(default_factory=list)
    impacted_routes: list[str] = Field(default_factory=list)  # "from->to"
    evidence: EvidenceRef = Field(default_factory=EvidenceRef)
    measurement: dict[str, Any] = Field(default_factory=dict)  # observed vs allowed numbers

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deviation_id(self) -> str:
        return deterministic_uuid(f"deviation:{self.fingerprint}")


class WaiverDefinition(BaseModel):
    """Time-boxed, fingerprint-scoped severity cap living in the certified
    baseline (glass-graph WaiverDefinition, ported verbatim)."""

    waiver_id: str
    title: str
    applies_to: list[str] = Field(default_factory=list)  # fingerprints
    severity_cap: Severity = Severity.INFO
    rationale: str = ""
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def applies(self, fingerprint: str, now: datetime | None = None) -> bool:
        from driftlab.clock import naive_utcnow

        current = now or naive_utcnow()
        if self.effective_from and current < self.effective_from:
            return False
        if self.effective_to and current > self.effective_to:
            return False
        return fingerprint in self.applies_to


class AnomalyRecord(BaseModel):
    """The persisted finding: deviation + severity + waiver + path impact."""

    comparison_type: ComparisonType
    severity: Severity
    kind: DriftKind
    fingerprint: str
    control_id: str | None = None
    title: str
    description: str
    impacted_nodes: list[str] = Field(default_factory=list)
    impacted_routes: list[str] = Field(default_factory=list)
    impacted_paths: list[PathImpact] = Field(default_factory=list)
    evidence: EvidenceRef = Field(default_factory=EvidenceRef)
    measurement: dict[str, Any] = Field(default_factory=dict)
    waiver_status: Literal["none", "waived"] = "none"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def anomaly_id(self) -> str:
        # Deterministic: same drift -> same identity across cycles.
        return deterministic_uuid(f"anomaly:{self.fingerprint}")


# --------------------------------------------------------------------------
# Hypothesis + experiment layer
# --------------------------------------------------------------------------
class DriftHypothesis(BaseModel):
    """A testable claim derived from an anomaly, with a concrete probe spec."""

    anomaly_fingerprint: str
    control_id: str | None = None
    kind: DriftKind
    statement: str
    probe_spec: dict[str, Any] = Field(default_factory=dict)
    expected_under_baseline: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hypothesis_id(self) -> str:
        return deterministic_uuid(f"hypothesis:{self.anomaly_fingerprint}")


class ProbeResult(BaseModel):
    """One controlled probe execution against the sandboxed replay."""

    probe_id: str
    samples: int
    violations: int
    violation_rate: float
    matched_run_ids: list[str] = Field(default_factory=list)
    violating_event_ids: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class ExperimentRecord(BaseModel):
    """Full record of a micro-experiment: hypothesis -> probes -> verdict."""

    hypothesis: DriftHypothesis
    verdict: Verdict
    validity_score: float
    iterations: int
    probes: list[ProbeResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    narrative: str | None = None  # optional LLM prose; advisory only

    @computed_field  # type: ignore[prop-decorator]
    @property
    def experiment_id(self) -> str:
        return deterministic_uuid(f"experiment:{self.hypothesis.anomaly_fingerprint}")


# --------------------------------------------------------------------------
# Cycle output
# --------------------------------------------------------------------------
class CycleResult(BaseModel):
    """Everything one monitor cycle produced for one agent."""

    agent_id: str
    cycle_id: str
    baseline_id: str
    baseline_hash: str
    trace_hash: str
    compliance_score: float = 100.0
    severity_counts: dict[str, int] = Field(default_factory=dict)
    anomalies: list[AnomalyRecord] = Field(default_factory=list)
    experiments: list[ExperimentRecord] = Field(default_factory=list)
    runs_observed: int = 0
    events_observed: int = 0
    started_at: str | None = None
    finished_at: str | None = None

    def ledger(self) -> dict[str, Any]:
        """Deterministic anomaly ledger: pure function of (baseline, trace).

        Wall-clock fields are deliberately excluded so re-running the same
        cycle on the same inputs is byte-identical (design principle #4).
        """
        return {
            "ledger_version": 1,
            "agent_id": self.agent_id,
            "baseline_id": self.baseline_id,
            "baseline_hash": self.baseline_hash,
            "trace_hash": self.trace_hash,
            "compliance_score": self.compliance_score,
            "severity_counts": dict(sorted(self.severity_counts.items())),
            "runs_observed": self.runs_observed,
            "events_observed": self.events_observed,
            "anomalies": [
                a.model_dump(mode="json")
                for a in sorted(self.anomalies, key=lambda a: a.fingerprint)
            ],
        }
