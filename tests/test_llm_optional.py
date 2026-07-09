"""LLM layer: none-by-default, mocked-model behavior, budget guard, and the
advisory-only invariant for the DeepAgents pass (project-pulse mock style)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from driftlab.config import Settings
from driftlab.llm import TokenBudgetExceeded, TokenUsage, build_chat_model, invoke_with_retries, narrate


def test_provider_none_builds_nothing():
    assert build_chat_model(Settings(llm_provider="none")) is None
    assert build_chat_model(Settings(llm_provider="")) is None


def test_openai_without_model_degrades():
    assert build_chat_model(Settings(llm_provider="openai", llm_model="")) is None


def _fake_model(content="hello", fail_times=0):
    model = MagicMock()
    calls = {"n": 0}

    def invoke(messages):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError("provider hiccup")
        return SimpleNamespace(content=content, usage_metadata={"input_tokens": 10, "output_tokens": 5})

    model.invoke.side_effect = invoke
    return model, calls


def test_invoke_retries_then_succeeds():
    model, calls = _fake_model(fail_times=2)
    with patch("time.sleep"):
        response = invoke_with_retries(model, [], max_retries=2)
    assert response.content == "hello" and calls["n"] == 3


def test_invoke_exhausts_retries_and_raises():
    model, _ = _fake_model(fail_times=99)
    with patch("time.sleep"), pytest.raises(RuntimeError, match="hiccup"):
        invoke_with_retries(model, [], max_retries=1)


def test_token_budget_blocks_before_call():
    usage = TokenUsage(budget_limit=100)
    usage.record(prompt=90, completion=9)
    model, calls = _fake_model()
    with pytest.raises(TokenBudgetExceeded):
        invoke_with_retries(model, [SimpleNamespace(content="x" * 400)], usage=usage)
    assert calls["n"] == 0  # the API was never hit


def test_narrate_none_model_and_failure_are_silent():
    assert narrate(None, "prompt") is None
    model, _ = _fake_model(fail_times=99)
    with patch("time.sleep"):
        assert narrate(model, "prompt", max_retries=0) is None


def test_narrate_returns_text():
    model, _ = _fake_model(content="  a narrative  ")
    assert narrate(model, "prompt") == "a narrative"


# -- DeepAgents advisory pass ---------------------------------------------------
def test_deep_annotate_without_model_is_none(loan_policy, drifted_events):
    from driftlab.domain.models import DriftHypothesis, DriftKind, ExperimentRecord, Verdict
    from driftlab.experiment.deep_agent import deep_annotate
    from driftlab.experiment.sandbox import ReplaySandbox

    record = ExperimentRecord(
        hypothesis=DriftHypothesis(anomaly_fingerprint="fp", kind=DriftKind.MISSING_HITL, statement="s"),
        verdict=Verdict.CONFIRMED,
        validity_score=1.0,
        iterations=1,
    )
    assert deep_annotate(record, sandbox=ReplaySandbox(drifted_events), policy=loan_policy, model=None) is None


def test_deep_annotate_uses_mocked_agent_and_never_decides(loan_policy, drifted_events):
    from driftlab.domain.models import DriftHypothesis, DriftKind, ExperimentRecord, Verdict
    from driftlab.experiment import deep_agent as da
    from driftlab.experiment.sandbox import ReplaySandbox

    record = ExperimentRecord(
        hypothesis=DriftHypothesis(anomaly_fingerprint="fp", kind=DriftKind.MISSING_HITL, statement="s"),
        verdict=Verdict.CONFIRMED,
        validity_score=1.0,
        iterations=1,
    )
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(type="ai", content="analyst note: drift concentrated in high-amount runs")]
    }
    fake_create = MagicMock(return_value=fake_agent)
    with patch.object(da, "create_deep_agent", fake_create, create=True), patch(
        "deepagents.create_deep_agent", fake_create
    ):
        note = da.deep_annotate(
            record, sandbox=ReplaySandbox(drifted_events), policy=loan_policy, model=MagicMock()
        )
    assert note.startswith("analyst note")
    # advisory-only: verdict and validity untouched
    assert record.verdict is Verdict.CONFIRMED and record.validity_score == 1.0
    # the agent got read-only tools
    _, kwargs = fake_create.call_args
    tool_names = {t.__name__ for t in kwargs["tools"]}
    assert tool_names == {"list_runs", "inspect_run", "run_probe"}


def test_deep_annotate_agent_crash_is_silent(loan_policy, drifted_events):
    from driftlab.domain.models import DriftHypothesis, DriftKind, ExperimentRecord, Verdict
    from driftlab.experiment import deep_agent as da
    from driftlab.experiment.sandbox import ReplaySandbox

    record = ExperimentRecord(
        hypothesis=DriftHypothesis(anomaly_fingerprint="fp", kind=DriftKind.MISSING_HITL, statement="s"),
        verdict=Verdict.CONFIRMED,
        validity_score=1.0,
        iterations=1,
    )
    fake_create = MagicMock(side_effect=RuntimeError("model exploded"))
    with patch("deepagents.create_deep_agent", fake_create):
        note = da.deep_annotate(
            record, sandbox=ReplaySandbox(drifted_events), policy=loan_policy, model=MagicMock()
        )
    assert note is None
