"""Sandbox isolation: the micro-experiment loop must never reach the network
or touch production. We booby-trap the socket layer before running the entire
experiment battery — any outbound attempt raises and fails the test.
"""

import socket
from pathlib import Path

import pytest

from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.experiment.hypothesis import generate
from driftlab.experiment.loop import run_experiment

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


class _BoobySocket:
    def __init__(self, *a, **k):
        raise RuntimeError("NETWORK ACCESS DENIED in experiment sandbox")

    def __getattr__(self, name):
        raise RuntimeError("NETWORK ACCESS DENIED in experiment sandbox")


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _BoobySocket)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("NETWORK ACCESS DENIED")))


def _anoms(agent: str):
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    diff = BehavioralDiff(policy, events)
    anoms = AnomalyEngine().build(diff.run(), diff=diff)
    return policy, events, anoms


def test_experiment_runs_with_sockets_boobytrapped(no_network):
    policy, events, anoms = _anoms("loan-officer")
    for a in anoms:
        if a.waived or a.severity.value in ("info", "low"):
            continue
        outcome = run_experiment(generate(a, policy), events)
        assert outcome.verdict.value in ("confirmed", "refuted", "inconclusive")


def test_sandbox_is_readonly():
    from driftlab.experiment.sandbox import ReplaySandbox
    events = load_jsonl(SEED / "traces" / "support-triage-trace.jsonl", "support-triage")
    sb = ReplaySandbox("support-triage", events)
    assert hasattr(sb, "matching") and hasattr(sb, "query") and hasattr(sb, "count")
    forbidden = {"write", "send", "post", "execute_live", "call_agent"}
    assert forbidden.isdisjoint(set(dir(sb)))