"""Deterministic identity: canonical JSON, content hashes, uuid5 IDs.

Every ID in driftlab is a pure function of content, never of wall-clock or
randomness (twinops principle: idempotent by construction). Re-running any
stage on the same inputs yields byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

#: Root namespace for all driftlab uuid5 identifiers.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://sw30labs.com/driftlab")

_HEX_LEN = 16


def canonical_json(payload: Any) -> str:
    """Serialize deterministically: sorted keys, compact separators."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(payload: Any) -> str:
    """sha256 hex digest of the canonical JSON form of *payload*."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def short_hash(key: str, length: int = _HEX_LEN) -> str:
    """Stable short hex id from an arbitrary string key (twinops ids.py pattern)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


def deterministic_id(kind: str, key: str) -> str:
    """Type-prefixed deterministic identifier, e.g. ``evt_3fa9c2...``."""
    return f"{kind}_{short_hash(key)}"


def deterministic_uuid(key: str) -> str:
    """uuid5 within the driftlab namespace — stable across runs and hosts."""
    return str(uuid.uuid5(NAMESPACE, key))
