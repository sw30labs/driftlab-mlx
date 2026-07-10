"""LLM layer: none-by-default, mocked-model behavior, budget guard, and the
advisory-only invariant for the DeepAgents pass (project-pulse mock style)."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from driftlab.config import Settings
from driftlab.llm import TokenBudgetExceeded, TokenUsage, build_chat_model, invoke_with_retries, narrate


def test_provider_none_builds_nothing():
    assert build_chat_model(Settings(llm_provider="none")) is None


def test_settings_reject_remote_openai_provider():
    with pytest.raises(ValidationError, match="llm_provider"):
        Settings(llm_provider="openai")


def test_omlx_uses_chat_openai_only_as_compatible_client():
    chat_openai = MagicMock(return_value=object())
    module = ModuleType("langchain_openai")
    module.ChatOpenAI = chat_openai
    settings = Settings(
        llm_provider="omlx",
        llm_model="local-model",
        omlx_base_url="http://omlx.internal:8000/v1",
    )

    with patch.dict(sys.modules, {"langchain_openai": module}):
        model = build_chat_model(settings)

    assert model is chat_openai.return_value
    chat_openai.assert_called_once_with(
        model="local-model",
        base_url="http://omlx.internal:8000/v1",
        api_key="test",
        timeout=600.0,
        streaming=False,
        temperature=0.2,
    )


def test_bypassed_settings_cannot_enable_remote_openai_provider():
    """The builder stays OMLX-only even if pydantic validation is bypassed."""
    settings = Settings.model_construct(llm_provider="openai")
    with patch.dict(sys.modules, {"langchain_openai": None}):
        assert build_chat_model(settings) is None


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
    with patch.object(da, "create_deep_agent", fake_create):
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
    with patch.object(da, "create_deep_agent", fake_create):
        note = da.deep_annotate(
            record, sandbox=ReplaySandbox(drifted_events), policy=loan_policy, model=MagicMock()
        )
    assert note is None
