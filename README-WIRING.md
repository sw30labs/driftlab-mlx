# Wiring DriftLab to Existing LangGraph Agentic Systems

The easiest path is already built into the repo: a purpose-made
`DriftLabTraceHandler` in `src/driftlab/ingest/langgraph_hook.py` bridges
LangGraph/LangChain into DriftLab's canonical `DecisionEvent` stream.

DriftLab does **not** run *inside* your graph. It **observes** your graph
from the outside via LangChain's callback system, so wiring is non-invasive —
you attach a handler at invoke time and flush the captured trace afterward.

## Option A — Zero-touch, automatic capture (recommended)

Pass the handler in as a LangChain callback when you invoke your graph. It
lazily builds a `BaseCallbackHandler` that maps `on_chain_start` → `route`
events and `on_tool_start` → `tool_call` events automatically:

```python
from langgraph.graph import StateGraph
from driftlab.ingest.langgraph_hook import DriftLabTraceHandler

graph = build_my_graph()  # your existing LangGraph app

handler = DriftLabTraceHandler(agent="payments-bot", run_id="run-123",
                               sink="traces/payments-bot.jsonl")

# Run your graph exactly as before — just add callbacks=[...]
result = graph.invoke(input, config={"callbacks": [handler.as_langchain_handler()]})

# Flush the captured trace to JSONL (then DriftLab's monitor picks it up)
handler.commit()
```

That's the whole integration. No graph code changes, no new nodes.

## Option B — Manual recording (more control, still simple)

If you'd rather emit specific decisions at known points (e.g. HITL gates,
refusals, escalations — things the generic callback can't infer), call
`handler.record()` directly from your nodes:

```python
handler = DriftLabTraceHandler(agent="payments-bot", run_id="run-123",
                               sink="traces/payments-bot.jsonl")

# inside a node:
handler.record("tool_call", node="approve", tool="ach_transfer", amount=4500.0)
handler.record("escalation", node="approve", route_to="human_review")
handler.record("hitl", node="human_review")
handler.commit()
```

Supported `kind` values (mapped to `EventKind`): `tool_call`, `route`,
`escalation`, `refusal`, `error`, `hitl`.

## Then let DriftLab do the compliance work

The JSONL the handler writes is exactly what DriftLab's monitor consumes
(see `runner.py:_run_one` → `load_jsonl`). Once traces land in a file, the
existing pipeline diffs them against a certified OSCAL baseline and runs
proof experiments:

```bash
driftlab monitor --registry agents.yaml   # or: python -m driftlab.cli monitor
```

Or programmatically, feed events straight into the cycle (no file needed):

```python
from driftlab.cycle import run_cycle
from driftlab.ingest import normalize_stream

events = normalize_stream("payments-bot", [raw_dict, ...])  # or handler.events
result = run_cycle("payments-bot", "seed/baselines/payments.yaml", events)
print(result.score, result.ledger)
```

## Why this is the easy/right path

- **No hard LangGraph dependency** in the core: the handler imports
  `langchain_core` lazily, so the compliance path stays pure-Python and
  deterministic.
- **Fail-closed normalization** (`ingest/__init__.py`): unrecognized event
  shapes raise instead of silently dropping evidence — important for a
  compliance observer.
- **Round-trips cleanly** into the existing monitor:
  `sink=...jsonl` → `load_jsonl` → `run_cycle`.

The one friction point: `as_langchain_handler()` auto-captures `route` /
`tool_call` but can't infer *semantic* events like `escalation` /
`refusal` / `hitl`. For full DL-3/DL-6/DL-7 coverage you'll want to sprinkle
a few manual `handler.record(...)` calls at your human-gate and refusal
points.