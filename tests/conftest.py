"""Shared fixtures. Tests inject Settings pointed at tmp_path (glass-graph
pattern) and run against the bundled seed estate — no network, no LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from driftlab.baseline.oscal_loader import load_baseline
from driftlab.config import Settings
from driftlab.ingest.jsonl_ingestor import load_events_jsonl

import driftlab

SEED = Path(driftlab.__file__).resolve().parent / "seed"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "workspace",
        registry_path=SEED / "agents.yaml",
        llm_provider="none",
    )


@pytest.fixture(scope="session")
def loan_policy():
    return load_baseline(SEED / "baselines" / "loan-officer-profile.json")


@pytest.fixture(scope="session")
def triage_policy():
    return load_baseline(SEED / "baselines" / "support-triage-profile.json")


@pytest.fixture(scope="session")
def drifted_events():
    events, problems = load_events_jsonl(SEED / "traces" / "loan-officer-drifted.jsonl")
    assert not problems
    return events


@pytest.fixture(scope="session")
def clean_events():
    events, problems = load_events_jsonl(SEED / "traces" / "loan-officer-clean.jsonl")
    assert not problems
    return events


@pytest.fixture(scope="session")
def triage_events():
    events, problems = load_events_jsonl(SEED / "traces" / "support-triage-clean.jsonl")
    assert not problems
    return events
