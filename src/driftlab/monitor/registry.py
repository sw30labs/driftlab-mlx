"""Monitored-agent registry loader (agents.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AgentSpec:
    id: str
    name: str
    baseline: str
    trace: str
    priority: int = 4
    owner: str = ""
    # Optional recorded resource stream (DL-8 telemetry plane). When absent,
    # the runner falls back to the live sensor path under the data dir.
    resource: str | None = None


def load_registry(path: str | Path) -> list[AgentSpec]:
    data = yaml.safe_load(Path(path).read_text())
    out = []
    for a in data.get("agents", []):
        out.append(AgentSpec(
            id=a["id"], name=a.get("name", a["id"]),
            baseline=a["baseline"], trace=a["trace"],
            priority=int(a.get("priority", 4)), owner=a.get("owner", ""),
            resource=a.get("resource"),
        ))
    return out