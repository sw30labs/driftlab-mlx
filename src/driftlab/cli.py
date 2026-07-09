"""DriftLab CLI — Typer + Rich.

    driftlab agents                    # estate + staleness status
    driftlab check --agent loan-officer
    driftlab monitor run [--force] [--scheduled] [--no-email]
    driftlab monitor status
    driftlab demo                      # full E2E on the bundled seed estate
    driftlab report <cycle_id>
    driftlab dashboard
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from driftlab import __version__
from driftlab.config import Settings, get_settings
from driftlab.domain.rendering import score_class
from driftlab.llm import build_chat_model
from driftlab.monitor.policy import select_due_agents
from driftlab.monitor.registry import load_registry, sync_registry
from driftlab.monitor.runner import run_monitor
from driftlab.store.db import CycleRow, Database, MonitorRunRow

app = typer.Typer(help="DriftLab — continuous compliance observer for running agentic systems.")
monitor_app = typer.Typer(help="Staleness-weighted estate monitor.")
app.add_typer(monitor_app, name="monitor")
console = Console()

_SCORE_STYLE = {"ok": "green", "warning": "yellow", "medium": "dark_orange", "critical": "red"}


def _settings(registry: Path | None = None, data_dir: Path | None = None) -> Settings:
    settings = get_settings()
    if registry or data_dir:
        overrides = {}
        if registry:
            overrides["registry_path"] = registry
        if data_dir:
            overrides["data_dir"] = data_dir
        settings = settings.model_copy(update=overrides)
    return settings


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"driftlab {__version__}")


@app.command()
def agents(
    registry: Path | None = typer.Option(None, help="agents.yaml path (default: seed registry)"),
    data_dir: Path | None = typer.Option(None, help="workspace dir (default: ./.driftlab)"),
) -> None:
    """List the monitored estate with staleness status."""
    settings = _settings(registry, data_dir)
    settings.ensure_dirs()
    database = Database(settings.db_path)
    specs = load_registry(settings.registry_path)
    sync_registry(database, specs)
    due = {d.id: d for d in select_due_agents(database, settings.intervals_days, settings.default_interval_days, include_all=True)}

    table = Table(title="DriftLab estate")
    for col in ("agent", "priority", "interval", "last checked", "overdue", "baseline"):
        table.add_column(col)
    for spec in specs:
        d = due.get(spec.id)
        overdue = "-" if d is None else ("never checked" if d.days_overdue == float("inf") else f"{d.days_overdue:+.1f}d")
        last = "-" if d is None or d.last_checked_at is None else str(d.last_checked_at)
        table.add_row(spec.id, f"P{spec.priority}", f"{d.interval_days}d" if d else "-", last, overdue, str(spec.baseline.name))
    console.print(table)


@app.command()
def check(
    agent: str = typer.Option(..., help="agent id from the registry"),
    registry: Path | None = typer.Option(None),
    data_dir: Path | None = typer.Option(None),
    probes: bool = typer.Option(True, help="run micro-experiments on findings"),
) -> None:
    """Run one compliance cycle for one agent, now."""
    from driftlab.cycle import CycleService

    settings = _settings(registry, data_dir)
    specs = {s.id: s for s in load_registry(settings.registry_path)}
    if agent not in specs:
        console.print(f"[red]unknown agent {agent!r}[/red] — known: {', '.join(sorted(specs))}")
        raise typer.Exit(1)
    spec = specs[agent]
    service = CycleService(settings, llm=build_chat_model(settings))
    cycle = service.run_cycle(agent_id=agent, baseline_path=spec.baseline, traces_path=spec.traces, run_probes=probes)
    _print_cycle(cycle)
    console.print(f"\nartifacts: [cyan]{settings.artifacts_dir / agent / cycle.cycle_id}[/cyan]")


def _print_cycle(cycle) -> None:
    style = _SCORE_STYLE[score_class(cycle.compliance_score)]
    console.print(f"\n[bold]{cycle.agent_id}[/bold] cycle [cyan]{cycle.cycle_id}[/cyan]")
    console.print(f"compliance score: [{style} bold]{cycle.compliance_score}[/{style} bold] / 100  {cycle.severity_counts or ''}")
    if cycle.anomalies:
        table = Table(show_lines=False)
        for col in ("severity", "control", "finding", "waiver"):
            table.add_column(col)
        for a in cycle.anomalies:
            sev_style = "red" if a.severity.value in ("critical", "high") else ("dark_orange" if a.severity.value == "medium" else "yellow")
            table.add_row(f"[{sev_style}]{a.severity.value}[/{sev_style}]", (a.control_id or "-").upper(), a.title, a.waiver_status)
        console.print(table)
    else:
        console.print("[green]clean — all certified controls satisfied[/green]")
    for e in cycle.experiments:
        v = e.verdict.value
        v_style = {"confirmed": "red", "refuted": "green", "inconclusive": "yellow"}[v]
        console.print(f"  experiment [{v_style}]{v.upper()}[/{v_style}] (validity {e.validity_score}): {escape(e.hypothesis.statement)}")


@monitor_app.command("run")
def monitor_run(
    agent: list[str] = typer.Option(None, "--agent", help="explicit agent id(s); overrides staleness policy"),
    limit: int | None = typer.Option(None, help="max agents this run"),
    force: bool = typer.Option(False, help="ignore staleness — check everything"),
    email: bool = typer.Option(True, "--email/--no-email"),
    scheduled: bool = typer.Option(False, "--scheduled", help="stamp run as scheduler-triggered"),
    registry: Path | None = typer.Option(None),
    data_dir: Path | None = typer.Option(None),
) -> None:
    """Run one estate monitor cycle (idempotent; safe under cron/launchd)."""
    settings = _settings(registry, data_dir)
    digest, meta = run_monitor(
        settings,
        agents=list(agent) if agent else None,
        limit=limit,
        force=force,
        send_email=email,
        trigger="scheduled" if scheduled else "manual",
        llm=build_chat_model(settings),
    )
    from driftlab.monitor.digest import render_text

    console.print(render_text(digest))
    if meta["email_sent"]:
        console.print("[green]digest emailed[/green]")
    elif meta["email_error"]:
        console.print(f"[yellow]email failed (cycle unaffected): {meta['email_error']}[/yellow]")
    elif meta["email_skipped_reason"]:
        console.print(f"[dim]email skipped: {meta['email_skipped_reason']}[/dim]")


@monitor_app.command("status")
def monitor_status(data_dir: Path | None = typer.Option(None)) -> None:
    """Recent monitor runs."""
    settings = _settings(None, data_dir)
    settings.ensure_dirs()
    database = Database(settings.db_path)
    with database.session() as session:
        runs = session.query(MonitorRunRow).order_by(MonitorRunRow.started_at.desc()).limit(15).all()
    table = Table(title="monitor runs")
    for col in ("run", "started", "trigger", "cycles", "new critical", "confirmed", "email"):
        table.add_column(col)
    for run in runs:
        table.add_row(run.id, str(run.started_at), run.trigger, str(run.cycles_run),
                      str(run.new_critical), str(run.confirmed_drifts), "sent" if run.email_sent else "-")
    console.print(table)


@app.command()
def report(
    cycle_id: str = typer.Argument(..., help="cycle id (see `driftlab agents` / dashboard)"),
    data_dir: Path | None = typer.Option(None),
) -> None:
    """Print the markdown report of a cycle."""
    settings = _settings(None, data_dir)
    database = Database(settings.db_path)
    with database.session() as session:
        cycle = session.get(CycleRow, cycle_id)
    if cycle is None:
        console.print(f"[red]unknown cycle {cycle_id}[/red]")
        raise typer.Exit(1)
    path = settings.artifacts_dir / cycle.agent_id / cycle_id / "report.md"
    console.print(path.read_text(encoding="utf-8"))


@app.command()
def dashboard(
    host: str | None = typer.Option(None),
    port: int | None = typer.Option(None),
    data_dir: Path | None = typer.Option(None),
) -> None:
    """Serve the estate dashboard."""
    import uvicorn

    from driftlab.dashboard.app import create_app

    settings = _settings(None, data_dir)
    application = create_app(settings)
    uvicorn.run(application, host=host or settings.dashboard_host, port=port or settings.dashboard_port)


@app.command()
def demo(data_dir: Path | None = typer.Option(None, help="workspace (default ./.driftlab)")) -> None:
    """Full E2E on the bundled seed estate: known-drifted loan-officer agent
    plus a clean support-triage agent. Detects, scores, and *proves* drift."""
    settings = _settings(None, data_dir)
    console.rule("[bold]DriftLab demo — seed estate")
    digest, _meta = run_monitor(settings, force=True, send_email=False, llm=build_chat_model(settings))
    database = Database(settings.db_path)
    with database.session() as session:
        cycles = {c.cycle_id: c for c in session.query(CycleRow).all()}
    for item in digest.agents_checked:
        cycle = cycles.get(item["cycle_id"])
        style = _SCORE_STYLE[score_class(item["score"])]
        console.print(
            f"  [bold]{item['id']}[/bold]: score [{style}]{item['score']}[/{style}], "
            f"{item['anomalies']} anomalie(s), {item['confirmed']} experimentally confirmed"
            + (f" -> [cyan]{cycle.cycle_id}[/cyan]" if cycle else "")
        )
    for drift in digest.confirmed_drifts:
        console.print(f"    [red]PROVEN[/red] [bold]{drift['agent_id']}[/bold]: {escape(drift['statement'])}")
    console.print(
        "\nEvidence (OSCAL assessment-results, deterministic ledger, report.md): "
        f"[cyan]{settings.artifacts_dir}[/cyan]"
    )
    console.print("Next: [bold]driftlab dashboard[/bold] then open "
                  f"http://{settings.dashboard_host}:{settings.dashboard_port}")


def main() -> None:  # console_scripts entry point
    app()


if __name__ == "__main__":
    main()
