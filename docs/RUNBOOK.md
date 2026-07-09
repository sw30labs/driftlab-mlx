# DriftLab Operator Runbook

Audience: whoever owns the monitoring estate day-to-day. Assumes the
CERTIFICATION-GUIDE has been followed and at least one agent is registered.

## 1. Install

```bash
cd /Users/spider/Code/REPOS/driftlab
uv sync --all-extras        # deterministic env; or pip install -e ".[llm,test]"
uv run pytest               # must be green before first use
```

Sanity check the estate end-to-end on bundled data:

```bash
uv run driftlab demo
```

## 2. Register agents

Create your own registry file and point `DRIFTLAB_REGISTRY_PATH` at it (the
default is the bundled demo estate inside the package — don't edit that one).
One entry per monitored agent; paths resolve relative to the registry file:

```yaml
agents:
  - id: loan-officer            # unique, stable
    name: Loan Officer
    priority: 1                 # 1..7 → check interval (1=daily by default)
    baseline: baselines/loan-officer-profile.json   # certified OSCAL profile
    traces: traces/loan-officer.jsonl               # file or directory of *.jsonl
```

Priorities map to intervals via `DRIFTLAB_INTERVALS_DAYS`
(default `{1:1, 2:1, 3:3, 4:7, 5:7, 6:14, 7:30}`). Verify with:

```bash
uv run driftlab agents
```

## 3. Schedule the monitor

The monitor command is idempotent — any scheduler works, and re-running early
is harmless (the staleness policy checks nothing that isn't due).

launchd (macOS, recommended):

```bash
sed -i '' "s|/usr/local/bin/driftlab|$(which driftlab)|" ops/com.driftlab.monitor.plist
cp ops/com.driftlab.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.driftlab.monitor.plist
```

cron: see `ops/crontab.txt`. Both templates pass `--scheduled` so run history
distinguishes scheduler-fired cycles from manual ones.

## 4. Email digests (optional, off by default)

```bash
export DRIFTLAB_EMAIL__ENABLED=true
export SMTP_HOST=smtp.example.com SMTP_USER=... SMTP_PASSWORD=...
export DRIFTLAB_EMAIL_TO=you@example.com
```

Digests send only when there is something to report (new criticals, confirmed
drifts, score drops, errors). A broken SMTP setup can never kill a cycle: the
error is recorded in `monitor status` and the console output.

## 5. Daily triage

Start at the dashboard (`driftlab dashboard`, default `127.0.0.1:8321`):

1. **Estate view** — scores are glass-graph coded: green ≥90, yellow ≥70,
   orange ≥40, red below. Anything not green deserves a look.
2. **Open the cycle** — anomalies table first. Severity semantics:
   * `CRITICAL` — certified control violated on a path reaching a critical
     sink (funds movement, external commitment). Treat as an incident.
   * `HIGH` — control violated, or sustained budget breach ≥10 points.
   * `MEDIUM/LOW` — degradation and evidence-quality signals.
3. **Check the experiment verdicts** before escalating:
   * `CONFIRMED` + probe evidence (`n/m violations`) — the drift is real and
     reproduced. Escalate with the OSCAL evidence attached.
   * `REFUTED` — the anomaly did not reproduce on independent replay. Rare;
     usually means the trace window was pathological. File for review.
   * `INCONCLUSIVE` — insufficient matched contexts (thin evidence). Do not
     escalate yet; widen the trace window and re-check.
4. **Evidence for auditors** — download `assessment-results.json` and
   `ledger.json` from the cycle page, or pull
   `.driftlab/artifacts/<agent>/<cycle>/` directly.

CLI equivalents: `driftlab monitor status`, `driftlab report <cycle_id>`.

## 6. Common operations

**Force a full estate check now** (e.g. after redeploying an agent):

```bash
uv run driftlab monitor run --force --no-email
```

**Check one agent immediately:**

```bash
uv run driftlab check --agent loan-officer
```

**Verify a remediation** — after fixing the agent, collect fresh traces and
re-run the check. Previously confirmed hypotheses re-tested against the new
trace should come back REFUTED (the seed suite demonstrates exactly this
pattern with the clean loan-officer trace).

**Waive an accepted finding** — add a `dl:waiver` prop to the certified
profile (see CERTIFICATION-GUIDE §5). Waivers are fingerprint-scoped,
time-boxed severity caps; the finding stays on the ledger marked `waived`.

**Baseline updated?** The compiled policy hash changes, so the next cycle gets
a new cycle id — history remains intact, and the ledger records which baseline
hash every finding was judged against.

## 7. Failure modes & recovery

| Symptom | Cause | Action |
|---|---|---|
| Digest says `[agent] error: FileNotFoundError` | trace path wrong/missing | fix registry path; other agents were unaffected (batch isolation) |
| `evidence_quality: no_trace` LOW finding | agent emitted nothing this window | check the agent's trace sink / callback wiring |
| Score dropped, all anomalies INCONCLUSIVE | thin trace window | lower check frequency or accumulate more runs before judging |
| `unknown dl: prop` at cycle start | typo in the certified profile | fix the profile — this is deliberately fatal (fail closed) |
| Email failures in `monitor status` | SMTP creds | fix env; cycles were unaffected |
| Need a clean slate | — | delete `$DRIFTLAB_DATA_DIR` (artifacts + SQLite); baselines and traces are inputs, never touched |

## 8. What DriftLab will never do

No outbound action on production agents: probes run only against in-memory
replays; the endpoint policy hard-fails anything non-loopback. No LLM in the
compliance path: unplug OMLX and every finding, score, and verdict is
unchanged (this invariant is part of the test suite).
