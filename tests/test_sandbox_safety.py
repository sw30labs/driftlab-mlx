"""Experiment safety: probes never touch production, never use the network."""

import socket

import pytest

from driftlab.anomaly.engine import AnomalyEngine
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.diff.engine import BehavioralDiffEngine
from driftlab.domain.models import DecisionEvent
from driftlab.experiment.loop import run_experiments
from driftlab.experiment.probes import execute_probe
from driftlab.experiment.sandbox import (
    CloneSandboxStub,
    ProductionIsolationError,
    ReplaySandbox,
    Sandbox,
    validate_sandbox_endpoint,
)
from driftlab.hypothesis.generator import generate_hypotheses


def test_replay_sandbox_is_isolated(drifted_events):
    assert ReplaySandbox(drifted_events).is_isolated


def test_endpoint_policy_rejects_non_loopback():
    validate_sandbox_endpoint("http://127.0.0.1:9999/agent")
    validate_sandbox_endpoint("http://localhost:9999/agent")
    for url in ("http://prod.internal/agent", "https://api.example.com", "http://10.0.0.5:8000"):
        with pytest.raises(ProductionIsolationError):
            validate_sandbox_endpoint(url)


def test_clone_sandbox_stub_enforces_policy_at_construction():
    with pytest.raises(ProductionIsolationError):
        CloneSandboxStub("https://agents.prod.example.com")


def test_non_isolated_sandbox_is_refused(loan_policy, drifted_events):
    class LeakySandbox(Sandbox):
        @property
        def is_isolated(self) -> bool:
            return False

        def runs(self) -> dict[str, list[DecisionEvent]]:
            return {}

    anomalies = AnomalyEngine().build_anomalies(
        policy=loan_policy,
        deviations=BehavioralDiffEngine().compare(policy=loan_policy, events=drifted_events),
        graph=BehaviorGraph(drifted_events),
    )
    hypothesis = generate_hypotheses(anomalies)[0]
    with pytest.raises(ProductionIsolationError):
        execute_probe(
            sandbox=LeakySandbox(),
            hypothesis=hypothesis,
            policy=loan_policy,
            probe_spec=dict(hypothesis.probe_spec),
        )


def test_full_experiment_suite_makes_zero_network_calls(
    monkeypatch, loan_policy, drifted_events
):
    """The §7 experiment-safety test: sockets are booby-trapped; the entire
    experiment battery must still pass, proving probes are pure replay."""

    def _no_network(*args, **kwargs):
        raise AssertionError("experiment attempted a network call — isolation broken")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    anomalies = AnomalyEngine().build_anomalies(
        policy=loan_policy,
        deviations=BehavioralDiffEngine().compare(policy=loan_policy, events=drifted_events),
        graph=BehaviorGraph(drifted_events),
    )
    hypotheses = generate_hypotheses(anomalies)
    records = run_experiments(hypotheses, sandbox=ReplaySandbox(drifted_events), policy=loan_policy)
    assert len(records) == 4
    assert all(r.probes for r in records)
