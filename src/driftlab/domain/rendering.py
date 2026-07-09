"""Visual scheme — ported verbatim from glass-graph's DEFAULT_CLASS_DEFS
so both dashboards speak the same color language across the estate."""

from __future__ import annotations

from driftlab.domain.models import Severity

#: Mermaid classDefs (glass-graph src/domain/rendering.py)
DEFAULT_CLASS_DEFS = {
    "ok": "fill:#d9f7be,stroke:#389e0d,color:#000",
    "warning": "fill:#fff7cc,stroke:#d48806,color:#000",
    "medium": "fill:#ffe7cc,stroke:#fa8c16,color:#000",
    "critical": "fill:#fff6d6,stroke:#cf1322,color:#000",
    "unknown": "fill:#f0f0f0,stroke:#8c8c8c,color:#000",
    "waived": "fill:#f9e6ff,stroke:#722ed1,color:#000",
    "focus": "fill:#e6f4ff,stroke:#1677ff,stroke-width:3px,color:#000",
}

#: severity value -> css class (glass-graph visualization._class_for_severity)
def class_for_severity(severity: str, waived: bool = False) -> str:
    if waived:
        return "waived"
    if severity in (Severity.CRITICAL.value, Severity.HIGH.value):
        return "critical"
    if severity == Severity.MEDIUM.value:
        return "medium"
    if severity == Severity.LOW.value:
        return "warning"
    return "ok"


#: severity value -> hex accent used by the dashboard badges
SEVERITY_HEX = {
    "critical": "#cf1322",
    "high": "#cf1322",
    "medium": "#fa8c16",
    "low": "#d48806",
    "info": "#8c8c8c",
}


def score_class(score: float) -> str:
    if score >= 90:
        return "ok"
    if score >= 70:
        return "warning"
    if score >= 40:
        return "medium"
    return "critical"
