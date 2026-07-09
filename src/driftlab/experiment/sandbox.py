"""Sandboxes for micro-experiments — bounded autonomy, enforced in code.

Design principle #5: the experiment loop may probe a *disposable replay* of
the agent, never production. Isolation is not a convention here, it is a
type: every probe executor calls ``sandbox.assert_isolated()`` before
touching evidence, and any future live-clone sandbox must pass the loopback
endpoint policy below or construction fails with ProductionIsolationError.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable
from urllib.parse import urlparse

from driftlab.domain.models import DecisionEvent

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ProductionIsolationError(RuntimeError):
    """An experiment attempted to touch a non-isolated system."""


def validate_sandbox_endpoint(url: str) -> str:
    """Only loopback endpoints may ever host a live probe target."""
    host = urlparse(url).hostname or ""
    if host not in _LOOPBACK_HOSTS:
        raise ProductionIsolationError(
            f"experiment endpoint {url!r} is not loopback — probes must never touch "
            "production (design principle #5)"
        )
    return url


class Sandbox(ABC):
    """Contract every probe target must satisfy."""

    @property
    @abstractmethod
    def is_isolated(self) -> bool: ...

    @abstractmethod
    def runs(self) -> dict[str, list[DecisionEvent]]:
        """run_id -> events, ordered by seq."""

    def assert_isolated(self) -> None:
        if not self.is_isolated:
            raise ProductionIsolationError(
                f"{type(self).__name__} is not isolated; refusing to execute probe"
            )


class ReplaySandbox(Sandbox):
    """Pure in-memory replay of recorded decision traces.

    No network, no filesystem writes, no side effects — the strongest
    possible isolation. This is the v1 probe target: micro-experiments
    re-evaluate suspected drift against independent replays of the evidence.
    """

    def __init__(self, events: list[DecisionEvent]) -> None:
        by_run: dict[str, list[DecisionEvent]] = {}
        for event in sorted(events, key=lambda e: (e.run_id, e.seq)):
            by_run.setdefault(event.run_id, []).append(event)
        self._runs = by_run

    @property
    def is_isolated(self) -> bool:
        return True

    def runs(self) -> dict[str, list[DecisionEvent]]:
        return dict(sorted(self._runs.items()))

    def sample(
        self, predicate: Callable[[list[DecisionEvent]], bool] | None = None
    ) -> dict[str, list[DecisionEvent]]:
        """Deterministically select runs matching *predicate* (all, if None)."""
        selected = {
            run_id: evs
            for run_id, evs in self._runs.items()
            if predicate is None or predicate(evs)
        }
        return dict(sorted(selected.items()))


class CloneSandboxStub(Sandbox):
    """Placeholder for a v2 live-clone sandbox (disposable agent instance).

    Construction enforces the loopback policy immediately; the class exists
    now so the isolation contract is part of the public API from day one.
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = validate_sandbox_endpoint(endpoint)

    @property
    def is_isolated(self) -> bool:
        return True

    def runs(self) -> dict[str, list[DecisionEvent]]:  # pragma: no cover - v2
        raise NotImplementedError("live clone probing ships in v2; use ReplaySandbox")
