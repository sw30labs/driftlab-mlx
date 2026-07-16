"""OSCAL-shaped evidence emitter + human-readable report.

Produces, per cycle:
* ``assessment-plan.json`` — OSCAL 1.1.2-shaped plan derived from the baseline
  (the controls assessed and their CA-7 continuous-monitoring anchor).
* ``assessment-results.json`` — OSCAL 1.1.2-shaped results: each control is
  marked ``satisfied`` / ``not-satisfied`` with observations carrying trace
  evidence and experiment verdicts.
* ``report.md`` — operator-facing markdown summary.

The artifacts are structured evidence inputs (see NOTES.md for the v0.2
strict-conformance milestone). They are generated deterministically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..anomaly import Anomaly
from ..baseline import load_profile
from ..cycle import CycleResult
from ..domain import BaselinePolicy


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_assessment_plan(agent: str, policy: BaselinePolicy, out_dir: Path) -> Path:
    plan = {
        "assessment-plan": {
            "uuid": f"plan-{agent}-{policy.baseline_hash[:12]}",
            "metadata": {
                "title": f"DriftLab Continuous Assessment Plan — {agent}",
                "version": "1.1.2",
                "published": _now(),
            },
            "import-ssp": {
                "href": f"baseline://{policy.baseline_id}",
                "remarks": "Points to the certified baseline profile (v0.1 pragmatic deviation).",
            },
            "assessment-subjects": {
                "component": [{"title": agent, "type": "service"}]
            },
            "assessment-methods": {
                "method": [{
                    "uuid": "method-driftlab-behavioral",
                    "type": "automated-test",
                    "description": "Continuous behavioral diff of observed decision traces "
                                   "and resource telemetry against the certified baseline "
                                   "(DL-1..8).",
                }]
            },
            "assessment-activities": {
                "assessment-activity": [
                    {"uuid": f"act-{c.id}", "description": f"{c.id} {c.title}",
                     "props": [{"name": "control-id", "value": c.id},
                               {"name": "nist-800-53", "value": ",".join(c.nist_800_53)},
                               {"name": "ca-7", "value": "true" if c.is_ca7 else "false"}]}
                    for c in policy.controls
                ]
            },
        }
    }
    return _write(out_dir / "assessment-plan.json", plan)


def emit_assessment_results(
    agent: str, policy: BaselinePolicy, result: CycleResult, out_dir: Path
) -> Path:
    # Group anomalies by control.
    by_control: dict[str, list[Anomaly]] = {}
    for a in result.anomalies:
        by_control.setdefault(a.control, []).append(a)
    exp_by_anom = {e["anomaly_id"]: e for e in result.experiments}

    results = {
        "assessment-results": {
            "uuid": f"results-{agent}-{result.cycle_id}",
            "metadata": {
                "title": f"DriftLab Assessment Results — {agent}",
                "version": "1.1.2",
                "published": _now(),
            },
            "results": {
                "result": []
            },
            "observations": {"observation": []},
        }
    }
    res_list = results["assessment-results"]["results"]["result"]
    obs_list = results["assessment-results"]["observations"]["observation"]
    for c in policy.controls:
        anoms = by_control.get(c.id, [])
        satisfied = len(anoms) == 0
        res_list.append({
            "uuid": f"res-{c.id}",
            "description": f"{c.id} {c.title}",
            "prop": [{"name": "result", "value": "satisfied" if satisfied else "not-satisfied"}],
        })
        for a in anoms:
            exp = exp_by_anom.get(a.id)
            obs_list.append({
                "uuid": f"obs-{a.id}",
                "description": a.detail,
                "props": [
                    {"name": "control-id", "value": a.control},
                    {"name": "severity", "value": a.severity.value},
                    {"name": "waived", "value": "true" if a.waived else "false"},
                    {"name": "evidence", "value": ",".join(a.evidence[:5])},
                    {"name": "experiment-verdict",
                     "value": (exp or {}).get("verdict", "not-run")},
                ],
            })
    return _write(out_dir / "assessment-results.json", results)


def emit_report(agent: str, result: CycleResult, out_dir: Path) -> Path:
    lines = [
        f"# DriftLab Compliance Report — {agent}",
        "",
        f"- Cycle: `{result.cycle_id}`",
        f"- Compliance score: **{result.score}/100**",
        f"- Baseline hash: `{result.baseline_hash[:12]}`",
        f"- Trace hash: `{result.trace_hash[:12]}`",
        "",
        "## Findings",
        "",
    ]
    active = [a for a in result.anomalies if not a.waived]
    if not active:
        lines.append("_No active anomalies. Agent is compliant this cycle._")
    else:
        lines.append("| Control | Severity | Title | Experiment |")
        lines.append("|---|---|---|---|")
        exp_by_anom = {e["anomaly_id"]: e for e in result.experiments}
        for a in active:
            v = (exp_by_anom.get(a.id) or {}).get("verdict", "—")
            lines.append(f"| {a.control} | {a.severity.value.upper()} | {a.title} | {v} |")
    if result.resource_summary is not None:
        rs = result.resource_summary
        lines.append("")
        lines.append("## Resource budget (DL-8)")
        lines.append("")
        lines.append(f"- Records: {rs['records']} · Breaker fired: "
                     f"{'yes' if rs['breaker_fired'] else 'no'} · Fidelity: "
                     f"{', '.join(rs['fidelity_observed']) or '—'}")
        for cur, ceiling in rs["ceilings"].items():
            spent = rs["spent"].get(cur, 0.0)
            flag = "  **EXCEEDED**" if spent > ceiling else ""
            lines.append(f"- {cur}: {spent:g} / {ceiling:g}{flag}")
    lines.append("")
    lines.append("## Experiment evidence")
    lines.append("")
    if not result.experiments:
        lines.append("_No experiments run._")
    else:
        for e in result.experiments:
            lines.append(f"- **{e['control']}** → `{e['verdict']}`: {e['rationale']}")
    lines.append("")
    return _write(out_dir / "report.md", "\n".join(lines))


def _write(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        path.write_text(obj)
    else:
        path.write_text(json.dumps(obj, indent=2, sort_keys=True))
    return path