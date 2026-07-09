"""The compiled, executable form of a certified baseline.

The OSCAL profile is the *certified artifact*; ``BaselinePolicy`` is what the
diff engine actually evaluates. The compiler in ``oscal_loader`` is the only
bridge between the two, mirroring skills-guardrails' ``compile_profile``.

Control family (defined in seed/baselines/driftlab-catalog.json):
    DL-1 decision rights (tool allowlists)       -> AC-3, AC-6, CM-7(5)
    DL-2 routing rules                           -> AC-4, CM-3
    DL-3 human-in-the-loop triggers              -> AC-3, CM-3(1)
    DL-4 fallback protocols                      -> SI-4, IR-4
    DL-5 critical sinks                          -> AC-6(1), CM-5
    DL-6 autonomy budget                         -> AC-6, CA-7
    DL-7 required steps / evidence               -> AU-2, AU-12, CA-7
"""

from __future__ import annotations

import operator
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from driftlab.domain.models import WaiverDefinition
from driftlab.identity import content_hash

_OPS = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
}


class Condition(BaseModel):
    """One predicate over a DecisionEvent's decision_context, e.g. amount>50000."""

    field: str
    op: Literal[">", ">=", "<", "<=", "==", "!="]
    value: float | str

    @classmethod
    def parse(cls, expr: str) -> "Condition":
        expr = expr.strip()
        for token in (">=", "<=", "==", "!=", ">", "<"):  # longest first
            if token in expr:
                field, raw = expr.split(token, 1)
                raw = raw.strip()
                try:
                    value: float | str = float(raw)
                except ValueError:
                    value = raw
                return cls(field=field.strip(), op=token, value=value)
        raise ValueError(f"unparseable condition {expr!r}")

    def evaluate(self, context: dict[str, Any]) -> bool:
        if self.field not in context:
            return False  # absent field never fires a trigger (conservative)
        actual = context[self.field]
        expected = self.value
        if isinstance(expected, float):
            try:
                actual = float(actual)
            except (TypeError, ValueError):
                return False
        return bool(_OPS[self.op](actual, expected))

    def render(self) -> str:
        return f"{self.field}{self.op}{self.value}"


class HitlTrigger(BaseModel):
    """When *all* conditions match at ``at_node``, the run must route the
    decision to ``require_route_to`` (the human gate)."""

    trigger_id: str
    at_node: str
    when: list[Condition] = Field(default_factory=list)
    require_route_to: str
    description: str = ""

    def matches(self, context: dict[str, Any]) -> bool:
        return all(c.evaluate(context) for c in self.when) if self.when else False


class FallbackRule(BaseModel):
    """After an ERROR event at ``on_error_at`` ("*" = any node), the next
    event in the run must occur at ``require_next_node``."""

    on_error_at: str = "*"
    require_next_node: str

    def applies_to(self, node: str) -> bool:
        return self.on_error_at in ("*", node)


class BaselinePolicy(BaseModel):
    """Certified intended behavior, compiled from the OSCAL profile."""

    baseline_id: str
    agent_id: str
    version: str = "0.0.0"
    status: Literal["draft", "in_review", "certified", "active", "deprecated", "retired"] = "draft"
    title: str = ""

    #: node -> allowed tool names; "*" key = tools allowed at any node.
    allowed_tools: dict[str, list[str]] = Field(default_factory=dict)
    #: from_node -> allowed route targets. Only nodes present as keys are constrained.
    allowed_routes: dict[str, list[str]] = Field(default_factory=dict)
    hitl_triggers: list[HitlTrigger] = Field(default_factory=list)
    #: max fraction of routing decisions allowed to take the full-autonomy path.
    max_auto_fraction: float | None = None
    #: node names whose ROUTE targets count as "full autonomy" for the budget.
    autonomy_auto_targets: list[str] = Field(default_factory=list)
    #: explicit decision population for DL-6. When set, only ROUTE events from
    #: these nodes count toward the autonomy budget. Without it, decision
    #: nodes are inferred from allowed_routes — which wrongly counts a HITL
    #: gate's *exit* as an autonomous decision whenever the gate routes to an
    #: auto target (found integrating the first real agent, soc-ir-tabletop).
    autonomy_decision_nodes: list[str] = Field(default_factory=list)
    fallback_rules: list[FallbackRule] = Field(default_factory=list)
    critical_sinks: list[str] = Field(default_factory=list)
    required_steps: list[str] = Field(default_factory=list)
    waivers: list[WaiverDefinition] = Field(default_factory=list)
    #: policy-area -> OSCAL control id, used by the evidence emitter.
    control_map: dict[str, str] = Field(
        default_factory=lambda: {
            "tools": "dl-1",
            "routes": "dl-2",
            "hitl": "dl-3",
            "fallback": "dl-4",
            "critical_sink": "dl-5",
            "autonomy": "dl-6",
            "steps": "dl-7",
        }
    )
    source_path: str | None = None
    catalog_path: str | None = None

    def tool_allowed(self, node: str, tool: str) -> bool:
        if tool in self.allowed_tools.get("*", []):
            return True
        node_list = self.allowed_tools.get(node)
        if node_list is not None:
            return tool in node_list
        # Node has no explicit list: fall back to the global list if one exists.
        return not self.allowed_tools

    def has_tool_policy(self) -> bool:
        return bool(self.allowed_tools)

    def route_allowed(self, from_node: str, to_node: str) -> bool | None:
        """True/False when constrained; None when this from-node is uncertified."""
        targets = self.allowed_routes.get(from_node)
        if targets is None:
            return None
        return to_node in targets

    @computed_field  # type: ignore[prop-decorator]
    @property
    def baseline_hash(self) -> str:
        """Content hash of the *certified policy core* (not file paths/prose)."""
        return content_hash(
            {
                "baseline_id": self.baseline_id,
                "agent_id": self.agent_id,
                "version": self.version,
                "allowed_tools": {k: sorted(v) for k, v in sorted(self.allowed_tools.items())},
                "allowed_routes": {k: sorted(v) for k, v in sorted(self.allowed_routes.items())},
                "hitl_triggers": [
                    {
                        "id": t.trigger_id,
                        "at": t.at_node,
                        "when": sorted(c.render() for c in t.when),
                        "require": t.require_route_to,
                    }
                    for t in sorted(self.hitl_triggers, key=lambda t: t.trigger_id)
                ],
                "max_auto_fraction": self.max_auto_fraction,
                "autonomy_auto_targets": sorted(self.autonomy_auto_targets),
                "autonomy_decision_nodes": sorted(self.autonomy_decision_nodes),
                "fallback_rules": sorted(f"{r.on_error_at}->{r.require_next_node}" for r in self.fallback_rules),
                "critical_sinks": sorted(self.critical_sinks),
                "required_steps": sorted(self.required_steps),
            }
        )
