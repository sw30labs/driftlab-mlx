"""Monitor digest — what changed across the estate this cycle (regitel pattern).

``has_alerts`` gates email delivery; rendering is a pure function of the
digest so the same content prints to console with --no-email."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MonitorDigest:
    run_id: str
    started_at: str
    finished_at: str | None = None
    agents_checked: list[dict[str, Any]] = field(default_factory=list)  # {id, score, anomalies, confirmed}
    new_critical: list[dict[str, Any]] = field(default_factory=list)
    confirmed_drifts: list[dict[str, Any]] = field(default_factory=list)
    refuted_drifts: list[dict[str, Any]] = field(default_factory=list)
    score_drops: list[dict[str, Any]] = field(default_factory=list)  # {id, previous, current}
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_alerts(self) -> bool:
        return bool(self.new_critical or self.confirmed_drifts or self.score_drops or self.errors)

    @property
    def subject(self) -> str:
        parts = []
        if self.new_critical:
            parts.append(f"{len(self.new_critical)} critical")
        if self.confirmed_drifts:
            parts.append(f"{len(self.confirmed_drifts)} drift(s) proven")
        if self.score_drops:
            parts.append(f"{len(self.score_drops)} score drop(s)")
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        summary = ", ".join(parts) if parts else "estate compliant"
        return f"Drift monitor — {summary}"


def render_text(digest: MonitorDigest) -> str:
    lines = [f"DriftLab monitor run {digest.run_id} ({digest.started_at})", ""]
    if digest.agents_checked:
        lines.append("Agents checked:")
        for item in digest.agents_checked:
            lines.append(
                f"  - {item['id']}: score {item['score']}, "
                f"{item['anomalies']} anomalie(s), {item['confirmed']} confirmed drift(s)"
            )
    else:
        lines.append("No agents were due this run.")
    if digest.new_critical:
        lines.append("")
        lines.append("NEW CRITICAL anomalies:")
        for item in digest.new_critical:
            lines.append(f"  ! [{item['agent_id']}] {item['title']}")
    if digest.confirmed_drifts:
        lines.append("")
        lines.append("Experimentally CONFIRMED drifts:")
        for item in digest.confirmed_drifts:
            lines.append(
                f"  * [{item['agent_id']}] {item['kind']} (validity {item['validity']}): {item['statement']}"
            )
    if digest.refuted_drifts:
        lines.append("")
        lines.append("Refuted (no longer reproduces):")
        for item in digest.refuted_drifts:
            lines.append(f"  - [{item['agent_id']}] {item['kind']}")
    if digest.score_drops:
        lines.append("")
        lines.append("Score drops:")
        for item in digest.score_drops:
            lines.append(f"  v [{item['id']}] {item['previous']} -> {item['current']}")
    if digest.errors:
        lines.append("")
        lines.append("Errors (cycle continued — batch isolation):")
        for item in digest.errors:
            lines.append(f"  x [{item['agent_id']}] {item['error']}")
    lines.append("")
    return "\n".join(lines)


def render_html(digest: MonitorDigest) -> str:
    def esc(s: Any) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    rows = []
    for item in digest.agents_checked:
        rows.append(
            f"<tr><td style='padding:4px 12px'>{esc(item['id'])}</td>"
            f"<td style='padding:4px 12px'>{esc(item['score'])}</td>"
            f"<td style='padding:4px 12px'>{esc(item['anomalies'])}</td>"
            f"<td style='padding:4px 12px'>{esc(item['confirmed'])}</td></tr>"
        )
    sections = [
        f"<h2 style='font-family:sans-serif'>DriftLab monitor — run {esc(digest.run_id)}</h2>",
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        "<tr><th style='text-align:left;padding:4px 12px'>Agent</th><th style='padding:4px 12px'>Score</th>"
        "<th style='padding:4px 12px'>Anomalies</th><th style='padding:4px 12px'>Confirmed</th></tr>"
        + "".join(rows)
        + "</table>",
    ]
    if digest.new_critical:
        items = "".join(
            f"<li><b>[{esc(i['agent_id'])}]</b> {esc(i['title'])}</li>" for i in digest.new_critical
        )
        sections.append(f"<h3 style='color:#cf1322;font-family:sans-serif'>New critical</h3><ul>{items}</ul>")
    if digest.confirmed_drifts:
        items = "".join(
            f"<li><b>[{esc(i['agent_id'])}]</b> {esc(i['kind'])} (validity {esc(i['validity'])}): "
            f"{esc(i['statement'])}</li>"
            for i in digest.confirmed_drifts
        )
        sections.append(f"<h3 style='color:#9a6700;font-family:sans-serif'>Confirmed drifts</h3><ul>{items}</ul>")
    if digest.errors:
        items = "".join(f"<li><b>[{esc(i['agent_id'])}]</b> {esc(i['error'])}</li>" for i in digest.errors)
        sections.append(f"<h3 style='font-family:sans-serif'>Errors</h3><ul>{items}</ul>")
    return "<html><body>" + "".join(sections) + "</body></html>"
