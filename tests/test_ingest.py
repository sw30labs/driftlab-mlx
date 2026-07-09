import pytest

from driftlab.domain.models import EventType
from driftlab.ingest.jsonl_ingestor import load_events_jsonl, trace_hash
from driftlab.ingest.normalizer import NormalizationError, normalize_event, normalize_events


def _raw(**kw):
    base = {"agent_id": "a", "run_id": "r1", "seq": 0, "event_type": "tool_call", "node": "n", "tool": "t"}
    base.update(kw)
    return base


def test_normalize_aliases():
    assert normalize_event(_raw(event_type="on_tool_start")).event_type is EventType.TOOL_CALL
    assert normalize_event(_raw(event_type="human_in_the_loop")).event_type is EventType.HITL
    assert normalize_event(_raw(event_type="interrupt")).event_type is EventType.HITL
    assert normalize_event(_raw(event_type="edge", target="m")).event_type is EventType.ROUTE


def test_normalize_unknown_type_is_loud():
    with pytest.raises(NormalizationError, match="unknown event_type"):
        normalize_event(_raw(event_type="mystery"))


def test_normalize_requires_agent_id():
    raw = _raw()
    raw.pop("agent_id")
    with pytest.raises(NormalizationError):
        normalize_event(raw)
    # ...unless the ingestion context provides one
    assert normalize_event(raw, default_agent_id="ctx").agent_id == "ctx"


def test_normalize_events_nonstrict_reports_problems():
    events, problems = normalize_events([_raw(), _raw(event_type="bogus", seq=1)], strict=False)
    assert len(events) == 1
    assert len(problems) == 1 and "bogus" in problems[0]


def test_events_sorted_and_event_id_ignores_timestamp():
    a = normalize_event(_raw(seq=1, ts="2026-01-01T00:00:00Z"))
    b = normalize_event(_raw(seq=1, ts="2026-06-06T06:06:06Z"))
    assert a.event_id == b.event_id  # ts is provenance, not identity
    events, _ = normalize_events([_raw(seq=2), _raw(seq=0), _raw(seq=1)])
    assert [e.seq for e in events] == [0, 1, 2]


def test_trace_hash_is_input_order_invariant(drifted_events):
    shuffled = list(reversed(drifted_events))
    assert trace_hash(drifted_events) == trace_hash(shuffled)


def test_jsonl_loader_reads_seed(drifted_events):
    assert len(drifted_events) == 262
    assert len({e.run_id for e in drifted_events}) == 20


def test_jsonl_loader_rejects_bad_json(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"run_id": "r1", "seq": 0\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_events_jsonl(bad, default_agent_id="a")
