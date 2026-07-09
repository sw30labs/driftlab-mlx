"""Observed behavior graph: DecisionEvents -> weighted transition DiGraph.

NetworkX carries reachability and blast-radius analysis (glass-graph
path_analysis), re-aimed at runtime transitions instead of static topology.
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise

import networkx as nx

from driftlab.domain.models import DecisionEvent, EventType, PathImpact


class BehaviorGraph:
    """Directed transition graph observed across all runs of one agent."""

    def __init__(self, events: list[DecisionEvent]) -> None:
        self.events = sorted(events, key=lambda e: (e.run_id, e.seq))
        self.graph = nx.DiGraph()
        self.transition_counts: Counter[tuple[str, str]] = Counter()
        self._build()

    def _build(self) -> None:
        for event in self.events:
            self.graph.add_node(event.node)
            if event.event_type is EventType.ROUTE and event.target:
                self.transition_counts[(event.node, event.target)] += 1

        # Fallback: derive transitions from consecutive node entries when the
        # trace contains no explicit ROUTE events.
        if not self.transition_counts:
            by_run: dict[str, list[str]] = {}
            for event in self.events:
                if event.event_type is EventType.NODE_ENTER:
                    by_run.setdefault(event.run_id, []).append(event.node)
            for run_nodes in by_run.values():
                for a, b in pairwise(run_nodes):
                    if a != b:
                        self.transition_counts[(a, b)] += 1

        for (a, b), count in sorted(self.transition_counts.items()):
            self.graph.add_edge(a, b, count=count)

    # -- analyses ------------------------------------------------------------
    def reaches(self, node: str, targets: list[str]) -> bool:
        """Can *node* reach any of *targets* in the observed graph?"""
        if node not in self.graph:
            return False
        for target in targets:
            if target == node:
                return True
            if target in self.graph and nx.has_path(self.graph, node, target):
                return True
        return False

    def path_to_nearest(self, node: str, targets: list[str]) -> list[str]:
        best: list[str] = []
        for target in sorted(targets):
            if node in self.graph and target in self.graph and nx.has_path(self.graph, node, target):
                path = nx.shortest_path(self.graph, node, target)
                if not best or len(path) < len(best):
                    best = list(path)
        return best

    def blast_radius(self, node: str) -> list[str]:
        if node not in self.graph:
            return [node]
        return sorted(nx.descendants(self.graph, node) | nx.ancestors(self.graph, node) | {node})

    def path_impact(self, node: str, critical_sinks: list[str]) -> PathImpact:
        return PathImpact(
            node_path=self.path_to_nearest(node, critical_sinks),
            reaches_critical_sink=self.reaches(node, critical_sinks),
            blast_radius_nodes=self.blast_radius(node),
        )
