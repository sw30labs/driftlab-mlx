"""LangChain/LangGraph callback handler -> DecisionEvents.

Attach ``DriftLabTraceHandler`` to any LangGraph/LangChain agent via
``config={"callbacks": [handler]}``. It captures node entries, tool calls,
routing transitions, errors, and interrupts as canonical DecisionEvents and
(optionally) appends them to a JSONL sink for later replay.

Soft dependency: importing this module works without langchain-core; only
constructing the handler requires it. The rest of driftlab never imports this
module — the compliance path stays LLM-framework-free.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from driftlab.domain.models import DecisionEvent, EventType

try:  # soft import — keeps the deterministic core dependency-light
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - exercised in envs without langchain
    BaseCallbackHandler = object  # type: ignore[assignment,misc]

#: LangGraph internal chain names that are orchestration noise, not decisions
_IGNORED_NAMES = {"LangGraph", "RunnableSequence", "RunnableLambda", "ChannelWrite", "_write", "__start__"}


class DriftLabTraceHandler(BaseCallbackHandler):  # type: ignore[misc]
    """Records agent decisions as canonical events.

    Parameters
    ----------
    agent_id: registered driftlab agent id.
    run_id:   caller-provided run id (one handler per run, or call new_run()).
    sink:     optional JSONL path; every event is appended as one line.
    """

    raise_error = False

    def __init__(self, agent_id: str, run_id: str, sink: Path | str | None = None) -> None:
        if BaseCallbackHandler is object:
            raise ImportError("langchain-core is required for DriftLabTraceHandler (pip install 'driftlab[llm]')")
        self.agent_id = agent_id
        self.run_id = run_id
        self.sink = Path(sink) if sink else None
        self.events: list[DecisionEvent] = []
        self._seq = 0
        self._last_node: str | None = None
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------------
    def _emit(self, event_type: EventType, node: str, **kw: Any) -> None:
        with self._lock:
            event = DecisionEvent(
                agent_id=self.agent_id,
                run_id=self.run_id,
                seq=self._seq,
                event_type=event_type,
                node=node,
                **kw,
            )
            self._seq += 1
            self.events.append(event)
            if self.sink:
                self.sink.parent.mkdir(parents=True, exist_ok=True)
                with self.sink.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event.model_dump(mode="json", exclude={"event_id"})) + "\n")

    @staticmethod
    def _node_name(serialized: dict | None, kwargs: dict) -> str | None:
        meta = kwargs.get("metadata") or {}
        name = meta.get("langgraph_node") or kwargs.get("name") or (serialized or {}).get("name")
        if not name or name in _IGNORED_NAMES:
            return None
        return str(name)

    # -- langchain callback surface -----------------------------------------
    def on_chain_start(self, serialized: dict | None, inputs: Any, **kwargs: Any) -> None:
        node = self._node_name(serialized, kwargs)
        if node is None:
            return
        if self._last_node and self._last_node != node:
            self._emit(EventType.ROUTE, self._last_node, target=node)
        self._last_node = node
        ctx = inputs if isinstance(inputs, dict) else {}
        safe_ctx = {k: v for k, v in ctx.items() if isinstance(v, (str, int, float, bool))}
        self._emit(EventType.NODE_ENTER, node, decision_context=safe_ctx)

    def on_tool_start(self, serialized: dict | None, input_str: str, **kwargs: Any) -> None:
        tool = (serialized or {}).get("name") or kwargs.get("name") or "unknown_tool"
        self._emit(EventType.TOOL_CALL, self._last_node or "unknown", tool=str(tool))

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        self._emit(EventType.ERROR, self._last_node or "unknown", attrs={"error": type(error).__name__})

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        self._emit(EventType.ERROR, self._last_node or "unknown", attrs={"error": type(error).__name__})

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        # interrupt surfacing: LangGraph human-in-the-loop pauses show up as
        # "__interrupt__" in outputs of the graph-level chain end.
        if isinstance(outputs, dict) and "__interrupt__" in outputs:
            self._emit(EventType.HITL, self._last_node or "unknown")

    def commit(self, node: str | None = None) -> None:
        """Mark the run's terminal output commit (call after invoke returns)."""
        self._emit(EventType.OUTPUT_COMMIT, node or self._last_node or "end")
