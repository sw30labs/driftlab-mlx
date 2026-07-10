"""Content-derived, deterministic identity helpers.

Every id in DriftLab is a pure function of content, so re-running a cycle on
the same inputs yields byte-identical artifacts and idempotent upserts.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any


def sha256_bytes(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()


def short_hash(*parts: str, length: int = 12) -> str:
    return sha256_bytes(*parts)[:length]


def event_id(agent: str, seq: int, kind: str, node: str, content: str) -> str:
    """Stable id for a single decision event."""
    return short_hash(agent, str(seq), kind, node, content, length=16)


def anomaly_id(fingerprint: str) -> str:
    """uuid5 of the finding fingerprint — stable across cycles (dedup free)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "urn:driftlab:anomaly:" + fingerprint))


def cycle_id(agent: str, baseline_hash: str, trace_hash: str) -> str:
    return short_hash(agent, baseline_hash, trace_hash, length=16)


def stable_json_digest(obj: Any) -> str:
    """Deterministic digest of a JSON-serializable structure."""
    import json

    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_bytes(canon)