"""CycleService — one full compliance cycle for one agent.

ingest -> diff -> anomalies -> score -> hypotheses -> micro-experiments ->
ledger + OSCAL evidence + report -> persist. The deterministic pipeline runs
identically with or without an LLM; LLM output only decorates the report.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from driftlab.anomaly.engine import AnomalyEngine
from driftlab.baseline.model import BaselinePolicy
from driftlab.baseline.oscal_loader import load_baseline
from driftlab.config import Settings
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.diff.engine import BehavioralDiffEngine
from driftlab.domain.models import CycleResult, Severity, Verdict
from driftlab.emit.oscal_evidence import build_assessment_plan, build_assessment_results
from driftlab.emit.report import build_markdown_report
from driftlab.experiment.deep_agent import deep_annotate
from driftlab.experiment.loop import run_experiments
from driftlab.experiment.sandbox import ReplaySandbox
from driftlab.hypothesis.generator import generate_hypotheses
from driftlab.identity import deterministic_id
from driftlab.ingest.jsonl_ingestor import load_events_jsonl, trace_hash
from driftlab.store.artifacts import LocalArtifactStore
from driftlab.store.db import AnomalyRow, CycleRow, Database, ExperimentRow

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CycleService:
    def __init__(
        self,
        settings: Settings,
        database: Database | None = None,
        store: LocalArtifactStore | None = None,
        llm: Any | None = None,
    ) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.database = database or Database(settings.db_path)
        self.store = store or LocalArtifactStore(settings.artifacts_dir)
        self.llm = llm
        self.diff_engine = BehavioralDiffEngine()
        self.anomaly_engine = AnomalyEngine()

    # ------------------------------------------------------------------
    def run_cycle(
        self,
        *,
        agent_id: str,
        baseline_path: Path | str,
        traces_path: Path | str,
        trigger: str = "manual",
        run_probes: bool = True,
        persist: bool = True,
    ) -> CycleResult:
        started_at = _utcnow_iso()
        policy = load_baseline(baseline_path)
        if policy.agent_id != agent_id:
            raise ValueError(
                f"baseline {baseline_path} certifies agent {policy.agent_id!r}, not {agent_id!r}"
            )
        events, problems = load_events_jsonl(traces_path, default_agent_id=agent_id, strict=False)
        for problem in problems:
            logger.warning("trace normalization: %s", problem)
        # A trace file may be shared by several agents (e.g. one process
        # hosting two certified graphs). Each cycle judges ONLY the events
        # belonging to the agent under assessment.
        events = [e for e in events if e.agent_id == agent_id]

        graph = BehaviorGraph(events)
        deviations = self.diff_engine.compare(policy=policy, events=events)
        anomalies = self.anomaly_engine.build_anomalies(policy=policy, deviations=deviations, graph=graph)
        score, counts = self.anomaly_engine.score(anomalies)

        experiments = []
        if run_probes and anomalies:
            hypotheses = generate_hypotheses(
                anomalies,
                max_experiments=self.settings.max_experiments_per_cycle,
                min_severity=Severity.MEDIUM,
            )
            sandbox = ReplaySandbox(events)
            experiments = run_experiments(
                hypotheses,
                sandbox=sandbox,
                policy=policy,
                max_iterations=self.settings.max_experiment_iterations,
                min_probe_samples=self.settings.min_probe_samples,
                confirm_threshold=self.settings.confirm_threshold,
                refute_threshold=self.settings.refute_threshold,
            )
            if self.llm is not None:
                for record in experiments:
                    if record.verdict is Verdict.CONFIRMED:
                        record.narrative = deep_annotate(
                            record, sandbox=sandbox, policy=policy, model=self.llm
                        )

        t_hash = trace_hash(events)
        idempotency_key = f"{agent_id}:{policy.baseline_hash}:{t_hash}"
        cycle = CycleResult(
            agent_id=agent_id,
            cycle_id=deterministic_id("cyc", idempotency_key),
            baseline_id=policy.baseline_id,
            baseline_hash=policy.baseline_hash,
            trace_hash=t_hash,
            compliance_score=score,
            severity_counts=counts,
            anomalies=anomalies,
            experiments=experiments,
            runs_observed=len({e.run_id for e in events}),
            events_observed=len(events),
            started_at=started_at,
            finished_at=_utcnow_iso(),
        )

        self._write_artifacts(cycle, policy)
        if persist:
            self._persist(cycle, idempotency_key, trigger)
        return cycle

    # ------------------------------------------------------------------
    def _write_artifacts(self, cycle: CycleResult, policy: BaselinePolicy) -> None:
        base = Path(cycle.agent_id) / cycle.cycle_id
        self.store.save_json(base / "ledger.json", cycle.ledger())
        self.store.save_json(
            base / "assessment-plan.json",
            build_assessment_plan(policy, timestamp=cycle.started_at or ""),
        )
        self.store.save_json(
            base / "assessment-results.json",
            build_assessment_results(cycle, policy),
        )
        self.store.save_text(
            base / "report.md",
            build_markdown_report(cycle, policy, llm=self.llm),
        )

    def _persist(self, cycle: CycleResult, idempotency_key: str, trigger: str) -> None:
        confirmed = sum(1 for e in cycle.experiments if e.verdict is Verdict.CONFIRMED)
        with self.database.session() as session:
            session.merge(
                CycleRow(
                    cycle_id=cycle.cycle_id,
                    idempotency_key=idempotency_key,
                    agent_id=cycle.agent_id,
                    baseline_id=cycle.baseline_id,
                    baseline_hash=cycle.baseline_hash,
                    trace_hash=cycle.trace_hash,
                    compliance_score=cycle.compliance_score,
                    severity_counts=json.dumps(cycle.severity_counts, sort_keys=True),
                    runs_observed=cycle.runs_observed,
                    events_observed=cycle.events_observed,
                    anomaly_count=len(cycle.anomalies),
                    experiment_count=len(cycle.experiments),
                    confirmed_drifts=confirmed,
                    status="completed",
                    trigger=trigger,
                    started_at=datetime.fromisoformat(cycle.started_at.replace("Z", "+00:00")).replace(tzinfo=None) if cycle.started_at else None,
                    finished_at=datetime.fromisoformat(cycle.finished_at.replace("Z", "+00:00")).replace(tzinfo=None) if cycle.finished_at else None,
                )
            )
            # idempotent re-runs: replace this cycle's anomaly/experiment rows
            session.query(AnomalyRow).filter(AnomalyRow.cycle_id == cycle.cycle_id).delete()
            session.query(ExperimentRow).filter(ExperimentRow.cycle_id == cycle.cycle_id).delete()
            for anomaly in cycle.anomalies:
                session.add(
                    AnomalyRow(
                        anomaly_id=anomaly.anomaly_id,
                        cycle_id=cycle.cycle_id,
                        agent_id=cycle.agent_id,
                        fingerprint=anomaly.fingerprint,
                        control_id=anomaly.control_id,
                        kind=anomaly.kind.value,
                        severity=anomaly.severity.value,
                        title=anomaly.title,
                        description=anomaly.description,
                        waiver_status=anomaly.waiver_status,
                        payload=anomaly.model_dump_json(),
                    )
                )
            for experiment in cycle.experiments:
                session.add(
                    ExperimentRow(
                        experiment_id=experiment.experiment_id,
                        cycle_id=cycle.cycle_id,
                        agent_id=cycle.agent_id,
                        anomaly_fingerprint=experiment.hypothesis.anomaly_fingerprint,
                        verdict=experiment.verdict.value,
                        validity_score=experiment.validity_score,
                        iterations=experiment.iterations,
                        payload=experiment.model_dump_json(),
                    )
                )
