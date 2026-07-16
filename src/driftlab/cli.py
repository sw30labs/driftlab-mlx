"""DriftLab Typer CLI.

Commands:
  driftlab agents                 estate + staleness status
  driftlab check --agent NAME     one compliance cycle, now
  driftlab monitor run            staleness-weighted estate cycle
  driftlab monitor status         recent runs
  driftlab report <cycle_id>      print a cycle's markdown report
  driftlab dashboard              serve the estate UI
  driftlab demo                  E2E on the bundled seed estate
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .monitor.registry import load_registry
from .monitor.runner import run_estate

app = typer.Typer(help="DriftLab — continuous compliance observer for agentic systems")
console = Console()


def _seed_root() -> Path:
    return Path(__file__).resolve().parent / "seed"


def _registry_path() -> Path:
    s = get_settings()
    return Path(s.registry_path) if s.registry_path else _seed_root() / "agents.yaml"


@app.command()
def agents() -> None:
    """Show the monitored estate and staleness status."""
    regs = load_registry(_registry_path())
    table = Table(title="DriftLab Estate")
    table.add_column("Agent")
    table.add_column("Priority")
    table.add_column("Owner")
    table.add_column("Baseline")
    for a in regs:
        table.add_row(a.id, str(a.priority), a.owner, a.baseline)
    console.print(table)


@app.command()
def check(
    agent: str = typer.Option(..., "--agent", help="agent id from the registry"),
    no_experiments: bool = typer.Option(False, "--no-experiments"),
) -> None:
    """Run one compliance cycle for an agent, now."""
    from .baseline import BaselineCompiler, load_profile
    from .cycle import run_cycle
    from .ingest import load_jsonl
    from .emit import emit_report
    from .config import get_settings

    seed = _seed_root()
    regs = {a.id: a for a in load_registry(_registry_path())}
    if agent not in regs:
        console.print(f"[red]unknown agent {agent!r}[/red]")
        raise typer.Exit(1)
    a = regs[agent]
    settings = get_settings()
    events = load_jsonl(seed / a.trace, agent)
    from .monitor.runner import load_agent_resources
    resource_records = load_agent_resources(a, seed, settings)
    result = run_cycle(agent, str(seed / a.baseline), events,
                       run_experiments=not no_experiments,
                       resource_records=resource_records)
    settings.ensure_dirs()
    out_dir = settings.artifacts_dir / agent / result.cycle_id
    emit_report(agent, result, out_dir)
    console.print(f"Cycle [bold]{result.cycle_id}[/bold] — score "
                  f"[bold]{result.score}/100[/bold] — "
                  f"{len([x for x in result.anomalies if not x.waived])} active anomalies")
    for an in result.anomalies:
        if not an.waived:
            console.print(f"  [{_sev_color(an.severity.value)}]{an.severity.value.upper()}[/{_sev_color(an.severity.value)}] "
                          f"{an.control}: {an.title}")
    for e in result.experiments:
        console.print(f"  experiment {e['control']} -> [cyan]{e['verdict']}[/cyan]")


@app.command()
def monitor() -> None:
    """Staleness-weighted estate monitor. Use `driftlab monitor --help`."""


monitor_app = typer.Typer(help="Staleness-weighted estate monitor")
app.add_typer(monitor_app, name="monitor")


@monitor_app.command("run")
def monitor_run(
    force: bool = typer.Option(False, "--force", help="ignore staleness, run all"),
    no_email: bool = typer.Option(False, "--no-email", help="skip SMTP digest"),
    scheduled: bool = typer.Option(False, "--scheduled", help="mark as scheduled run"),
) -> None:
    """Run a staleness-weighted estate cycle."""
    summary = run_estate(force=force, no_email=no_email, scheduled=scheduled)
    console.print(f"[green]ran {len(summary['ran'])}[/green], "
                  f"skipped {len(summary['skipped'])}, "
                  f"errors {len(summary['errors'])}")
    for r in summary["ran"]:
        console.print(f"  {r['agent']}: {r['score']}/100")


@monitor_app.command("status")
def monitor_status_cmd() -> None:
    """Show recent monitor runs."""
    _monitor_status()


def _monitor_status() -> None:
    from .store import AgentRecord, init_db
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from .store import _engine
    init_db()
    with Session(_engine()) as s:
        rows = s.execute(select(AgentRecord)).scalars().all()
    table = Table(title="Recent monitor runs")
    table.add_column("Agent")
    table.add_column("Priority")
    table.add_column("Last cycle")
    for r in rows:
        table.add_row(r.id, str(r.priority), r.last_cycle or "—")
    console.print(table)


@app.command()
def report(cycle_id: str) -> None:
    """Print a cycle's markdown report from the store."""
    from .store import CycleRecord, init_db
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from .store import _engine
    init_db()
    with Session(_engine()) as s:
        rec = s.get(CycleRecord, cycle_id)
        if not rec:
            console.print(f"[red]no cycle {cycle_id!r}[/red]")
            raise typer.Exit(1)
        import json
        ledger = json.loads(rec.ledger)
    console.print(f"# {ledger['agent']} — score {ledger['score']}/100")
    for a in ledger["anomalies"]:
        if not a["waived"]:
            console.print(f"  {a['severity'].upper()} {a['control']}: {a['title']}")


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8321, "--port"),
) -> None:
    """Serve the estate dashboard (air-gapped; no CDN)."""
    import uvicorn
    from .dashboard.app import app as fastapi_app
    console.print(f"[green]DriftLab dashboard at http://{host}:{port}[/green]")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


@app.command()
def demo() -> None:
    """Run the full E2E on the bundled seed estate (loan-officer + support-triage)."""
    console.print("[bold]DriftLab demo — full estate cycle[/bold]")
    summary = run_estate(force=True, no_email=True)
    for r in summary["ran"]:
        console.print(f"  {r['agent']}: score [bold]{r['score']}/100[/bold]")
    console.print("\nloan-officer should be low (drifts detected + proven); "
                  "support-triage should be 100 (clean).")
    console.print("Artifacts in: " + str(get_settings().artifacts_dir))


def _sev_color(sev: str) -> str:
    return {"critical": "red", "high": "yellow", "medium": "yellow",
            "low": "blue", "info": "blue"}.get(sev, "white")


def main() -> None:
    app()


if __name__ == "__main__":
    main()