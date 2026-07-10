"""LLM-optional invariant: the full compliance path succeeds with no LLM
reachable (provider=none and no endpoint). The platform must never require the
LLM to produce a verdict, score, or artifact."""

from pathlib import Path

from driftlab.config import Settings, get_settings
from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.cycle import run_cycle
from driftlab.llm import is_enabled, executive_narrative

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def test_llm_disabled_by_default(monkeypatch):
    # Force provider none regardless of env.
    monkeypatch.setenv("DRIFTLAB_LLM_PROVIDER", "none")
    # Bust the lru_cache so settings reload.
    get_settings.cache_clear()
    assert is_enabled() is False


def test_full_run_without_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTLAB_LLM_PROVIDER", "none")
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / ".driftlab"))
    get_settings.cache_clear()

    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / "loan-officer-trace.jsonl", "loan-officer")
    result = run_cycle("loan-officer", str(SEED / "baselines" / "loan-officer-baseline.json"),
                       events, run_experiments=True)
    # No LLM needed for a complete, scored result.
    assert result.score is not None
    assert len(result.anomalies) > 0
    # Narrative gracefully returns None when LLM disabled.
    assert executive_narrative(result.to_ledger()) is None


def test_llm_narrative_handles_failure(monkeypatch):
    # With provider set but endpoint unreachable, narrative must return None,
    # never raise.
    monkeypatch.setenv("DRIFTLAB_LLM_PROVIDER", "omlx")
    monkeypatch.setenv("DRIFTLAB_OMLX_BASE_URL", "http://127.0.0.1:9/v1")  # dead port
    get_settings.cache_clear()
    assert executive_narrative({"score": 10}) is None