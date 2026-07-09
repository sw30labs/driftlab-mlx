import pytest

from driftlab.baseline.model import Condition
from driftlab.baseline.oscal_loader import BaselineCompileError, compile_baseline
from driftlab.domain.models import Severity


def test_condition_parse_and_eval():
    c = Condition.parse("amount>50000")
    assert c.evaluate({"amount": 50001}) and not c.evaluate({"amount": 50000})
    assert not c.evaluate({})  # absent field never fires
    assert Condition.parse("risk==high").evaluate({"risk": "high"})
    assert Condition.parse("score<=0.5").evaluate({"score": "0.4"})  # string coercion
    with pytest.raises(ValueError):
        Condition.parse("nonsense")


def test_loan_policy_compiles(loan_policy):
    p = loan_policy
    assert p.agent_id == "loan-officer"
    assert p.status == "certified"
    assert p.max_auto_fraction == 0.40  # from set-parameters
    assert p.allowed_tools["assess"] == ["credit_check", "policy_lookup"]
    assert "auto_approve" in p.allowed_routes["assess"]
    assert [t.trigger_id for t in p.hitl_triggers] == ["high-risk", "high-value"]  # sorted
    assert p.critical_sinks == ["disburse_funds"]
    assert p.autonomy_auto_targets == ["auto_approve"]
    assert p.required_steps == ["assess"]
    assert p.fallback_rules[0].on_error_at == "*"


def test_baseline_hash_tracks_policy_not_prose(loan_policy):
    h1 = loan_policy.baseline_hash
    copy = loan_policy.model_copy(deep=True)
    copy.title = "renamed for humans"
    assert copy.baseline_hash == h1  # prose is not policy
    copy.critical_sinks.append("new_sink")
    assert copy.baseline_hash != h1  # policy change -> new hash


def _minimal_profile(props=None, meta_props=None):
    return {
        "profile": {
            "uuid": "u",
            "metadata": {
                "title": "t",
                "version": "1",
                "props": meta_props
                if meta_props is not None
                else [{"name": "dl:agent-id", "value": "x"}],
            },
            "modify": {"controls": [{"control-id": "dl-1", "props": props or []}]},
        }
    }


def test_unknown_dl_prop_is_loud():
    doc = _minimal_profile(props=[{"name": "dl:allow-tools", "value": "a:b"}])  # typo
    with pytest.raises(BaselineCompileError, match="unknown dl: prop"):
        compile_baseline(doc)


def test_missing_agent_id_is_fatal():
    with pytest.raises(BaselineCompileError, match="dl:agent-id"):
        compile_baseline(_minimal_profile(meta_props=[]))


def test_waiver_parsing():
    doc = _minimal_profile(
        props=[{"name": "dl:waiver", "value": "w1|low|fp-a,fp-b|accepted risk until refactor"}]
    )
    policy = compile_baseline(doc)
    waiver = policy.waivers[0]
    assert waiver.waiver_id == "w1"
    assert waiver.severity_cap is Severity.LOW
    assert waiver.applies("fp-a") and waiver.applies("fp-b") and not waiver.applies("fp-c")


def test_tool_and_route_semantics(loan_policy):
    p = loan_policy
    assert p.tool_allowed("assess", "credit_check")
    assert not p.tool_allowed("assess", "external_data_broker")
    assert p.route_allowed("assess", "auto_approve") is True
    assert p.route_allowed("assess", "shadow_node") is False
    assert p.route_allowed("uncertified_node", "anywhere") is None  # unconstrained
