"""LangGraph / LangChain callback handler -> DecisionEvent stream.

Attach ``DriftLabTraceHandler`` to a graph invocation to capture node entries,
tool calls, routing decisions and human-in-the-loop triggers as canonical
decision events. Events are buffered and flushed to a JSONL sink on
``commit()`` (or returned in-memory for tests).

The handler is dependency-light: it imports langchain callbacks lazily so the
core compliance path has no hard LangGraph/LangChain runtime requirement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import DecisionEvent, EventKind


class DriftLabTraceHandler:
    """A minimal callback collector. Works without langchain installed.

    If langchain is available it can also be used as a ``BaseCallbackHandler``
    via :meth:`as_langchain_handler`; otherwise feed events manually with
    :meth:`record`.
    """

    def __init__(self, agent: str, run_id: str, sink: str | Path | None = None):
        self.agent = agent
        self.run_id = run_id
        self.sink = Path(sink) if sink else None
        self._events: list[DecisionEvent] = []
        self._seq = 0

    def record(self, kind: str, node: str, **fields: Any) -> DecisionEvent:
        ev = DecisionEvent(
            agent=self.agent,
            seq=self._seq,
            kind=EventKind(kind),
            node=node,
            tool=fields.get("tool"),
            route_from=fields.get("route_from"),
            route_to=fields.get("route_to"),
            amount=fields.get("amount"),
            payload={k: v for k, v in fields.items() if k not in _SKIP},
        )
        self._seq += 1
        self._events.append(ev)
        return ev

    def commit(self) -> list[DecisionEvent]:
        """Flush buffered events to the JSONL sink (if any) and return them."""
        if self.sink:
            self.sink.parent.mkdir(parents=True, exist_ok=True)
            with self.sink.open("a") as fh:
                for ev in self._events:
                    fh.write(json.dumps(ev.model_dump(mode="json")) + "\n")
        return self._events

    @property
    def events(self) -> list[DecisionEvent]:
        return list(self._events)

    def as_langchain_handler(self):
        """Return a langchain-compatible callback handler (requires langchain)."""
        from langchain_core.callbacks import BaseCallbackHandler

        parent = self

        class _Handler(BaseCallbackHandler):
            def on_chain_start(self, serialized, inputs, **kwargs):  # noqa: ANN001
                name = (serialized or {}).get("name") or kwargs.get("name") or "chain"
                parent.record("route", str(name), route_from="__start__", route_to=str(name))

            def on_tool_start(self, serialized, input_str, **kwargs):  # noqa: ANN001
                name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
                node = kwargs.get("parent_run_id") and str(kwargs["parent_run_id"]) or "tool"
                parent.record("tool_call", node, tool=str(name))

            def on_llm_error(self, error, **kwargs):  # noqa: ANN001
                parent.record("error", "llm", payload={"error": str(error)})

        return _Handler()


_SKIP = {"kind", "node", "tool", "route_from", "route_to", "amount"}