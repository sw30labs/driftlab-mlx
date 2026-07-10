"""JSONL replay ingestor — load recorded traces for testing without a live agent."""

from __future__ import annotations

from pathlib import Path

from . import load_jsonl


def ingest_jsonl(path: str | Path, agent: str | None = None):
    return load_jsonl(path, agent)