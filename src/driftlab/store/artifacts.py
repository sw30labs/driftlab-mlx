"""Local artifact store — ported from glass-graph src/services/storage.py.

Path-containment guarded, deterministic JSON (sort_keys), local-first."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactPathError(ValueError):
    """Attempted write/read outside the artifact root."""


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root):
            raise ArtifactPathError(f"path {relative!r} escapes artifact root")
        return candidate

    def save_json(self, relative: str | Path, payload: Any) -> Path:
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return path

    def read_json(self, relative: str | Path) -> Any:
        return json.loads(self._resolve(relative).read_text(encoding="utf-8"))

    def save_text(self, relative: str | Path, text: str) -> Path:
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def exists(self, relative: str | Path) -> bool:
        try:
            return self._resolve(relative).exists()
        except ArtifactPathError:
            return False

    def list_dir(self, relative: str | Path) -> list[str]:
        path = self._resolve(relative)
        if not path.is_dir():
            return []
        return sorted(p.name for p in path.iterdir() if p.is_file())
