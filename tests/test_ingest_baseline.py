"""Unit tests: trace normalization (fail-closed) and baseline compilation."""

from pathlib import Path

import pytest

from driftlab.ingest import normalize_record, load_jsonl, NormalizationError
from driftlab.baseline import BaselineCompiler, load_profile, CompileError

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def test_normalize_record_basic():
    ev = normalize_record("a", 0, {"kind": "tool_call", "node": "decide", "tool": "approve"})
    assert ev.kind.value == "tool_call"
    assert ev.tool == "approve"
    assert ev.id


def test_normalize_record_unknown_kind_raises():
    with pytest.raises(NormalizationError):
        normalize_record("a", 0, {"kind": "teleport", "node": "x"})


def test_normalize_record_missing_node_raises():
    with pytest.raises(NormalizationError):
        normalize_record("a", 0, {"kind": "tool_call"})


def test_load_jsonl_roundtrip():
    events = load_jsonl(SEED / "traces" / "support-triage-trace.jsonl", "support-triage")
    assert len(events) > 0
    assert all(e.node for e in events)


def test_compile_fail_closed_on_unknown_prop():
    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    profile.props.append({"name": "dl:bogus", "value": "x"})
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)


def test_compile_fail_closed_on_bad_budget():
    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    profile.props = [p for p in profile.props if p["name"] != "dl:autonomy-budget"]
    profile.props.append({"name": "dl:autonomy-budget", "value": "1.5"})
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)


def test_compile_success_produces_policy():
    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    policy = BaselineCompiler().compile(profile)
    assert policy.autonomy_budget == 0.40
    assert policy.tool_allowlist["decide"] == ["approve", "decline"]
    assert policy.baseline_hash


def test_compile_resource_ceilings():
    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    policy = BaselineCompiler().compile(profile)
    assert policy.resource_ceilings == {"tokens": 120000.0, "iterations": 40.0}
    assert any(c.id == "DL-8" for c in policy.controls)


def test_compile_fail_closed_on_unknown_resource_currency():
    profile = load_profile(SEED / "baselines" / "support-triage-baseline.json")
    profile.props.append({"name": "dl:resource-budget", "value": "parsecs|12"})
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)


def test_compile_fail_closed_on_bad_resource_ceiling():
    profile = load_profile(SEED / "baselines" / "support-triage-baseline.json")
    profile.props.append({"name": "dl:resource-budget", "value": "cpu_seconds|lots"})
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)
    profile.props[-1] = {"name": "dl:resource-budget", "value": "cpu_seconds|0"}
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)


def test_compile_fail_closed_on_duplicate_resource_currency():
    profile = load_profile(SEED / "baselines" / "support-triage-baseline.json")
    profile.props.append({"name": "dl:resource-budget", "value": "tokens|99"})
    with pytest.raises(CompileError):
        BaselineCompiler().compile(profile)