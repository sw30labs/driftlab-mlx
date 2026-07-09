"""OSCAL profile/catalog -> BaselinePolicy compiler.

Follows the OSCAL-skills-guardrails pattern: the certified baseline is an
OSCAL *profile* that imports the driftlab control catalog and binds concrete
policy via ``props`` under the ``dl:`` namespace
(``https://sw30labs.com/ns/dl``). Unknown ``dl:`` props are a loud error —
a certified artifact with typos must not silently certify less than intended.

Prop vocabulary (all values are strings; repeatable unless noted):
    dl:allow-tool        "node:tool" or "*:tool"
    dl:allow-route       "from->to"
    dl:hitl-when         "trigger_id|at_node|cond1&cond2|require_route_to[|description]"
    dl:fallback          "node->fallback_node"  ("*" = any node)
    dl:critical-sink     "node"
    dl:auto-target       "node"   (route target counting against the autonomy budget)
    dl:decision-node     "node"   (explicit DL-6 decision population; recommended
                                   whenever a HITL gate also routes to an auto target)
    dl:max-auto-fraction "0.40"   (single; may also come from set-parameters
                                   param-id dl-max-auto-fraction)
    dl:required-step     "node"
    dl:waiver            "waiver_id|severity_cap|fp1,fp2|rationale[|from_iso[|to_iso]]"
Metadata props: dl:agent-id (required), dl:baseline-status.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from driftlab.baseline.model import BaselinePolicy, Condition, FallbackRule, HitlTrigger
from driftlab.domain.models import Severity, WaiverDefinition

DL_NS = "https://sw30labs.com/ns/dl"

_KNOWN_PROPS = {
    "dl:allow-tool",
    "dl:allow-route",
    "dl:hitl-when",
    "dl:fallback",
    "dl:critical-sink",
    "dl:auto-target",
    "dl:decision-node",
    "dl:max-auto-fraction",
    "dl:required-step",
    "dl:waiver",
    "dl:agent-id",
    "dl:baseline-status",
    "dl:schema-version",
}


class BaselineCompileError(ValueError):
    """The OSCAL artifact could not be compiled into an executable policy."""


def load_oscal_json(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def _iter_props(container: dict[str, Any]):
    for prop in container.get("props", []) or []:
        yield str(prop.get("name", "")), str(prop.get("value", ""))


def _parse_dt(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _parse_waiver(value: str) -> WaiverDefinition:
    parts = value.split("|")
    if len(parts) < 4:
        raise BaselineCompileError(f"dl:waiver needs 'id|cap|fps|rationale[...]', got {value!r}")
    waiver_id, cap, fps, rationale = parts[0], parts[1], parts[2], parts[3]
    try:
        severity_cap = Severity(cap.strip().lower())
    except ValueError as exc:
        raise BaselineCompileError(f"dl:waiver {waiver_id}: unknown severity cap {cap!r}") from exc
    return WaiverDefinition(
        waiver_id=waiver_id.strip(),
        title=f"Waiver {waiver_id.strip()}",
        applies_to=[fp.strip() for fp in fps.split(",") if fp.strip()],
        severity_cap=severity_cap,
        rationale=rationale.strip(),
        effective_from=_parse_dt(parts[4]) if len(parts) > 4 else None,
        effective_to=_parse_dt(parts[5]) if len(parts) > 5 else None,
    )


def _parse_hitl(value: str) -> HitlTrigger:
    parts = value.split("|")
    if len(parts) < 4:
        raise BaselineCompileError(
            f"dl:hitl-when needs 'id|node|conds|route_to[|description]', got {value!r}"
        )
    trigger_id, at_node, conds, require = (p.strip() for p in parts[:4])
    description = parts[4].strip() if len(parts) > 4 else ""
    when = [Condition.parse(c) for c in conds.split("&") if c.strip()]
    return HitlTrigger(
        trigger_id=trigger_id, at_node=at_node, when=when,
        require_route_to=require, description=description,
    )


def _split_arrow(value: str, prop: str) -> tuple[str, str]:
    if "->" not in value:
        raise BaselineCompileError(f"{prop} needs 'a->b', got {value!r}")
    a, b = value.split("->", 1)
    return a.strip(), b.strip()


def compile_baseline(profile_doc: dict[str, Any], *, source_path: str | None = None) -> BaselinePolicy:
    """Compile an OSCAL profile document into an executable BaselinePolicy."""
    profile = profile_doc.get("profile")
    if not isinstance(profile, dict):
        raise BaselineCompileError("document has no top-level 'profile' key")

    metadata = profile.get("metadata", {})
    agent_id = ""
    status = "draft"
    for name, value in _iter_props(metadata):
        if name == "dl:agent-id":
            agent_id = value
        elif name == "dl:baseline-status":
            status = value
        elif name.startswith("dl:") and name not in _KNOWN_PROPS:
            raise BaselineCompileError(f"unknown dl: metadata prop {name!r}")
    if not agent_id:
        raise BaselineCompileError("profile metadata is missing required prop dl:agent-id")

    policy = BaselinePolicy(
        baseline_id=str(profile.get("uuid", "baseline")),
        agent_id=agent_id,
        version=str(metadata.get("version", "0.0.0")),
        status=status,  # type: ignore[arg-type]
        title=str(metadata.get("title", "")),
        source_path=source_path,
    )

    # set-parameters: org-level defaults
    modify = profile.get("modify", {}) or {}
    for param in modify.get("set-parameters", []) or []:
        if param.get("param-id") == "dl-max-auto-fraction":
            values = param.get("values") or []
            if values:
                policy.max_auto_fraction = float(values[0])

    # controls[].props: the concrete certified policy
    controls = list(modify.get("controls", []) or [])
    # strict alters[].adds[].props form is also accepted (skills-guardrails parity)
    for alter in modify.get("alters", []) or []:
        for add in alter.get("adds", []) or []:
            controls.append({"control-id": alter.get("control-id"), "props": add.get("props", [])})

    for control in controls:
        for name, value in _iter_props(control):
            if not name.startswith("dl:"):
                continue
            if name not in _KNOWN_PROPS:
                raise BaselineCompileError(
                    f"unknown dl: prop {name!r} on control {control.get('control-id')!r}"
                )
            if name == "dl:allow-tool":
                if ":" not in value:
                    raise BaselineCompileError(f"dl:allow-tool needs 'node:tool', got {value!r}")
                node, tool = (s.strip() for s in value.split(":", 1))
                policy.allowed_tools.setdefault(node, [])
                if tool not in policy.allowed_tools[node]:
                    policy.allowed_tools[node].append(tool)
            elif name == "dl:allow-route":
                frm, to = _split_arrow(value, name)
                policy.allowed_routes.setdefault(frm, [])
                if to not in policy.allowed_routes[frm]:
                    policy.allowed_routes[frm].append(to)
            elif name == "dl:hitl-when":
                policy.hitl_triggers.append(_parse_hitl(value))
            elif name == "dl:fallback":
                node, target = _split_arrow(value, name)
                policy.fallback_rules.append(FallbackRule(on_error_at=node, require_next_node=target))
            elif name == "dl:critical-sink":
                if value not in policy.critical_sinks:
                    policy.critical_sinks.append(value)
            elif name == "dl:auto-target":
                if value not in policy.autonomy_auto_targets:
                    policy.autonomy_auto_targets.append(value)
            elif name == "dl:decision-node":
                if value not in policy.autonomy_decision_nodes:
                    policy.autonomy_decision_nodes.append(value)
            elif name == "dl:max-auto-fraction":
                policy.max_auto_fraction = float(value)
            elif name == "dl:required-step":
                if value not in policy.required_steps:
                    policy.required_steps.append(value)
            elif name == "dl:waiver":
                policy.waivers.append(_parse_waiver(value))

    policy.hitl_triggers.sort(key=lambda t: t.trigger_id)
    return policy


def load_baseline(path: Path | str) -> BaselinePolicy:
    """Load + compile an OSCAL profile from disk, resolving its catalog import."""
    path = Path(path)
    doc = load_oscal_json(path)
    policy = compile_baseline(doc, source_path=str(path))
    imports = (doc.get("profile", {}) or {}).get("imports", []) or []
    for imp in imports:
        href = str(imp.get("href", ""))
        if href and not href.startswith(("http://", "https://", "#")):
            catalog = (path.parent / href).resolve()
            if catalog.exists():
                policy.catalog_path = str(catalog)
    return policy


def catalog_control_index(catalog_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """control_id -> {title, prose, sp800_53} from the driftlab catalog."""
    index: dict[str, dict[str, Any]] = {}
    catalog = catalog_doc.get("catalog", {}) or {}
    for group in catalog.get("groups", []) or []:
        for control in group.get("controls", []) or []:
            cid = str(control.get("id", "")).lower()
            prose = ""
            for part in control.get("parts", []) or []:
                if part.get("name") == "statement":
                    prose = str(part.get("prose", ""))
            links = [
                str(link.get("href", "")).lstrip("#").upper()
                for link in control.get("links", []) or []
                if link.get("rel") == "related"
            ]
            index[cid] = {"title": control.get("title", cid), "prose": prose, "sp800_53": links}
    return index
