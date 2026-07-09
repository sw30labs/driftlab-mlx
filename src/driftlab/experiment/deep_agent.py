"""Optional DeepAgents pass over a completed experiment — advisory only.

The deterministic loop (loop.py) owns the verdict. When an LLM is configured,
this module gives a DeepAgents autonomous agent read-only probe tools against
the same sandbox so it can decompose "characterize this drift" into
sub-probes (which contexts drift, since when, how concentrated) and write an
analyst note. Its output is attached to ``ExperimentRecord.narrative`` and is
never allowed to alter verdict or validity.

Reserved for the genuine long-horizon case per the brief: probe-space
exploration is open-ended; the pipeline itself stays a plain StateGraph.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from driftlab.baseline.model import BaselinePolicy
from driftlab.domain.models import ExperimentRecord
from driftlab.experiment.probes import execute_probe
from driftlab.experiment.sandbox import Sandbox

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are DriftLab's drift analyst. A deterministic engine has already \
reached a verdict on a drift hypothesis for an AI agent; your job is to characterize the \
confirmed drift for a compliance audience, using the read-only probe tools against a \
sandboxed replay. Decompose the question: which decision contexts drift, how concentrated \
is it across runs, does magnitude trend? Run at most 6 probes. You CANNOT change the \
verdict — end with a concise analyst note (<= 200 words) grounded only in probe outputs."""


def _build_tools(sandbox: Sandbox, policy: BaselinePolicy, hypothesis: Any) -> list:
    def list_runs() -> str:
        """List run ids available in the sandboxed replay with event counts."""
        return json.dumps({rid: len(evs) for rid, evs in sandbox.runs().items()}, sort_keys=True)

    def inspect_run(run_id: str) -> str:
        """Return the ordered decision events of one replay run as JSON."""
        events = sandbox.runs().get(run_id, [])
        return json.dumps([e.model_dump(mode="json") for e in events], sort_keys=True)

    def run_probe(probe_kind: str, params_json: str = "{}") -> str:
        """Execute one read-only probe against the sandboxed replay.

        probe_kind: hitl_replay | tool_replay | route_replay | autonomy_windows |
        fallback_replay | step_replay. params_json: JSON object with the probe's
        parameters (e.g. {"trigger_id": "high-value"} or {"node": "assess", "tool": "x"}).
        """
        spec = {"probe_kind": probe_kind, "scope": 1, **json.loads(params_json or "{}")}
        result = execute_probe(sandbox=sandbox, hypothesis=hypothesis, policy=policy, probe_spec=spec)
        return result.model_dump_json()

    return [list_runs, inspect_run, run_probe]


def deep_annotate(
    record: ExperimentRecord,
    *,
    sandbox: Sandbox,
    policy: BaselinePolicy,
    model: Any | None,
    max_agent_steps: int = 12,
) -> str | None:
    """Run the advisory DeepAgents pass. Returns the analyst note or None.

    Every failure path returns None: the compliance run must be identical
    with or without this pass (LLM-optional invariant).
    """
    if model is None:
        return None
    try:
        from deepagents import create_deep_agent
    except ImportError:
        logger.debug("deepagents not installed; skipping advisory pass")
        return None
    try:
        sandbox.assert_isolated()
        agent = create_deep_agent(
            model=model,
            tools=_build_tools(sandbox, policy, record.hypothesis),
            system_prompt=_SYSTEM_PROMPT,
        )
        task = (
            f"Hypothesis ({record.verdict.value}, validity {record.validity_score}): "
            f"{record.hypothesis.statement}\n"
            f"Probe evidence so far: "
            f"{json.dumps([p.model_dump(mode='json') for p in record.probes], sort_keys=True)}\n"
            "Characterize the drift and write the analyst note."
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": max(10, max_agent_steps * 2)},
        )
        messages = result.get("messages", [])
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if content and getattr(message, "type", "") == "ai":
                return str(content).strip()
        return None
    except Exception as exc:  # noqa: BLE001 — advisory pass must never break a cycle
        logger.warning("DeepAgents advisory pass skipped: %s", exc)
        return None
