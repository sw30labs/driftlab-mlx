"""OSCAL-shaped behavioral baseline: catalog, profile vocabulary, loader.

The certified baseline is expressed as an OSCAL **profile** that imports the
DriftLab **catalog** (``driftlab-catalog.json``). The catalog defines eight
behavioral controls (DL-1..8), each crosswalked to SP 800-53r5, with DL-6..8
anchored on CA-7 (continuous monitoring). The profile binds concrete policy
via ``dl:`` props. A :class:`BaselineCompiler` turns that into an executable,
fail-closed :class:`BaselinePolicy`.

This module does NOT require the NIST oscal-cli; it validates the structures
it needs and fails closed on malformed input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..domain import BaselinePolicy, ControlDef, Severity
from ..sensor import Currency

CATALOG_PATH = Path(__file__).resolve().parent.parent / "seed" / "baselines" / "driftlab-catalog.json"

# The eight behavioral controls. CA-7 is the continuous-monitoring umbrella.
CONTROL_FAMILY: list[ControlDef] = [
    ControlDef(id="DL-1", title="Decision rights", description="Per-node tool allowlists",
               nist_800_53=["AC-3", "AC-6", "CM-7(5)"]),
    ControlDef(id="DL-2", title="Routing rules", description="Certified transitions only",
               nist_800_53=["AC-4", "CM-3"]),
    ControlDef(id="DL-3", title="Human-in-the-loop triggers",
               description="Matching decisions reach the human gate",
               nist_800_53=["AC-3", "CM-3(1)"]),
    ControlDef(id="DL-4", title="Fallback protocols",
               description="Required recovery after errors", nist_800_53=["SI-4", "IR-4"]),
    ControlDef(id="DL-5", title="Critical sinks",
               description="Severity escalation near irreversible actions",
               nist_800_53=["AC-6(1)", "CM-5"]),
    ControlDef(id="DL-6", title="Autonomy budget",
               description="Capped full-autonomy fraction", nist_800_53=["AC-6", "CA-7"],
               is_ca7=True),
    ControlDef(id="DL-7", title="Required steps + continuous trace evidence",
               description="Mandated nodes present every cycle", nist_800_53=["AU-2", "AU-12", "CA-7"],
               is_ca7=True),
    ControlDef(id="DL-8", title="Resource budget",
               description="Cumulative resource spend stays under certified ceilings",
               nist_800_53=["SC-6", "CA-7"], is_ca7=True),
]


class CompileError(ValueError):
    """Raised on malformed baseline input — fail closed, never pass silently."""


# Map of dl: prop names to policy targets.
_DL_PROPS = {
    "dl:tool-allow", "dl:route-allow", "dl:hitl-when", "dl:fallback-for",
    "dl:critical-sink", "dl:autonomy-budget", "dl:required-step",
    "dl:decision-node", "dl:resource-budget",
}


def load_catalog(path: str | Path = CATALOG_PATH) -> dict[str, Any]:
    with Path(path).open() as fh:
        return json.load(fh)


class BaselineProfile(BaseModel):
    """Parsed view of an OSCAL profile with ``dl:`` props."""

    agent: str
    baseline_id: str
    title: str
    props: list[dict[str, str]] = Field(default_factory=list)


def load_profile(path: str | Path) -> BaselineProfile:
    """Load an OSCAL profile JSON/YAML and extract its dl: props."""
    p = Path(path)
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    metadata = data.get("metadata", {})
    props = data.get("props", [])
    # Also accept a simplified "dl" block for ergonomics in seed files.
    dl_block = data.get("dl", {})
    flat: list[dict[str, str]] = []
    for prop in props:
        if prop.get("name", "").startswith("dl:"):
            flat.append(prop)
    for key, value in dl_block.items():
        name = key if key.startswith("dl:") else f"dl:{key}"
        flat.append({"name": name, "value": str(value)})
    return BaselineProfile(
        agent=data.get("agent", metadata.get("title", "unknown")),
        baseline_id=data.get("uuid", metadata.get("title", "unknown")),
        title=metadata.get("title", "Untitled baseline"),
        props=flat,
    )


class BaselineCompiler:
    """Compile a BaselineProfile (plus the canonical catalog) into a
    fail-closed, executable BaselinePolicy."""

    def __init__(self, catalog: dict[str, Any] | None = None):
        self.catalog = catalog or load_catalog()

    def compile(self, profile: BaselineProfile) -> BaselinePolicy:
        policy = BaselinePolicy(
            agent=profile.agent,
            baseline_id=profile.baseline_id,
            baseline_hash="",
            title=profile.title,
            controls=list(CONTROL_FAMILY),
        )
        seen: set[str] = set()
        for prop in profile.props:
            name = prop.get("name", "")
            value = prop.get("value", "")
            if name not in _DL_PROPS:
                raise CompileError(f"unrecognized baseline prop {name!r}")
            self._apply(policy, name, value, seen)

        # Validate structural sanity (fail-closed).
        if not (0.0 <= policy.autonomy_budget <= 1.0):
            raise CompileError(f"autonomy_budget out of range: {policy.autonomy_budget}")
        policy.baseline_hash = policy.digest()
        return policy

    def _apply(self, policy: BaselinePolicy, name: str, value: str, seen: set[str]) -> None:
        if name == "dl:tool-allow":
            # value: "node|tool1,tool2"
            node, _, tools = value.partition("|")
            node = node.strip()
            policy.tool_allowlist[node] = [t.strip() for t in tools.split(",") if t.strip()]
        elif name == "dl:route-allow":
            frm, _, to = value.partition("->")
            policy.allowed_routes.append((frm.strip(), to.strip()))
        elif name == "dl:hitl-when":
            # value: "tag|condition|node|explanation"
            tag, _, rest = value.partition("|")
            cond, _, node = rest.partition("|")
            policy.hitl_when.append({"tag": tag.strip(), "condition": cond.strip(),
                                     "node": node.strip(), "raw": value})
        elif name == "dl:fallback-for":
            err, _, node = value.partition("|")
            policy.fallback_for[err.strip()] = node.strip()
        elif name == "dl:critical-sink":
            policy.critical_sinks.append(value.strip())
        elif name == "dl:autonomy-budget":
            policy.autonomy_budget = float(value.strip())
        elif name == "dl:decision-node":
            policy.decision_nodes.append(value.strip())
        elif name == "dl:required-step":
            policy.required_steps.append(value.strip())
        elif name == "dl:resource-budget":
            # value: "currency|ceiling", e.g. "tokens|200000" (DL-8; ADR-001)
            cur_raw, _, ceiling_raw = value.partition("|")
            cur_raw = cur_raw.strip()
            try:
                currency = Currency(cur_raw)
            except ValueError:
                known = ", ".join(c.value for c in Currency)
                raise CompileError(
                    f"dl:resource-budget unknown currency {cur_raw!r}; known: {known}")
            if currency.value in policy.resource_ceilings:
                raise CompileError(
                    f"dl:resource-budget duplicate currency {currency.value!r}")
            try:
                ceiling = float(ceiling_raw.strip())
            except ValueError:
                raise CompileError(
                    f"dl:resource-budget ceiling not numeric: {ceiling_raw!r}")
            if not ceiling > 0:
                raise CompileError(
                    f"dl:resource-budget ceiling must be > 0, got {ceiling}")
            policy.resource_ceilings[currency.value] = ceiling