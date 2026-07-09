---
marp: true
paginate: true
size: 16:9
style: |
  :root {
    --bg: #0b1220;
    --panel: #111a2e;
    --line: #22304d;
    --ink: #e6edf7;
    --muted: #8ea0bd;
    --ok: #4ade80;
    --drift: #f87171;
    --amber: #fbbf24;
    --blue: #60a5fa;
  }
  section {
    background: var(--bg);
    color: var(--ink);
    font-family: "Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 21px;
    padding: 56px 64px;
    line-height: 1.45;
  }
  h1 { color: #ffffff; font-size: 40px; margin: 0 0 6px 0; letter-spacing: -0.5px; }
  h2 { color: #ffffff; font-size: 26px; margin: 0 0 10px 0; }
  h6 { color: var(--muted); text-transform: uppercase; letter-spacing: 2.5px; font-size: 13px; margin: 0 0 14px 0; font-weight: 600; }
  strong { color: var(--ok); font-weight: 700; }
  em { color: var(--amber); font-style: normal; }
  a { color: var(--blue); }
  section::after { color: var(--muted); font-size: 14px; }
  section table { font-size: 18px; border-collapse: collapse; width: 100%; background: transparent !important; }
  section table th { color: var(--muted) !important; background: transparent !important; text-transform: uppercase; font-size: 13px; letter-spacing: 1px; border: none !important; border-bottom: 1px solid var(--line) !important; padding: 8px 10px; text-align: left; }
  section table td { border: none !important; border-bottom: 1px solid var(--line) !important; padding: 8px 10px; background: transparent !important; color: var(--ink) !important; }
  section table tbody tr, section table thead tr,
  section table tbody tr:nth-child(even), section table tbody tr:nth-child(odd) { background: transparent !important; }
  code { background: #1c2942; color: #e6edf7; padding: 1px 7px; border-radius: 5px; font-size: 0.85em; }
  .cols { display: flex; gap: 28px; align-items: stretch; }
  .col { flex: 1; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 18px 22px; }
  .kpi { font-size: 44px; font-weight: 800; color: var(--ok); line-height: 1.1; }
  .kpi.bad { color: var(--drift); }
  .kpi-label { color: var(--muted); font-size: 15px; margin-top: 2px; }
  .foot { position: absolute; bottom: 28px; left: 64px; right: 64px; color: var(--muted); font-size: 13px; }
  ul { margin: 6px 0; }
  li { margin: 5px 0; }
  .tag { display: inline-block; border: 1px solid var(--line); background: var(--panel); border-radius: 20px; padding: 2px 12px; font-size: 14px; color: var(--muted); margin-right: 6px; }
  section.lead { display: flex; flex-direction: column; justify-content: center; }
  section.lead h1 { font-size: 58px; }
---

<!-- _class: lead -->
<!-- _paginate: false -->

###### sw30labs · July 2026

# DriftLab

## Prove what your agents *actually* do.

Continuous, machine-readable compliance for running agentic systems — behavioral drift detection against certified OSCAL baselines, with **experimental proof**.

<span class="tag">local-first</span><span class="tag">deterministic</span><span class="tag">OSCAL-native</span><span class="tag">EU AI Act · SOC 2 · ISO 42001</span>

---

###### Problem

# Agents drifted. Nobody can prove it.

<div class="cols">
<div class="col">

Enterprises are pushing autonomous agents into **regulated decisions** — credit, claims, support, treasury.

The governance stack never left the design phase:

- Policy documents & governance canvases — *written once*
- Model risk registries — *inventories, not behavior*
- Build-time graph diffs — *structure, not runtime*

The question a regulator actually asks — *"did the agent route high-value decisions past the human gate last quarter?"* — is **unanswerable with evidence** today.

</div>
<div class="col panel">

**A quarter of real agent behavior:**

<svg viewBox="0 0 420 220" width="100%">
  <line x1="40" y1="180" x2="400" y2="180" stroke="#22304d" stroke-width="1"/>
  <line x1="40" y1="20" x2="40" y2="180" stroke="#22304d" stroke-width="1"/>
  <line x1="40" y1="76" x2="400" y2="76" stroke="#fbbf24" stroke-width="1.5" stroke-dasharray="6 4"/>
  <text x="46" y="70" fill="#fbbf24" font-size="12">certified autonomy budget · 40%</text>
  <polyline points="40,115 90,112 140,108 190,100 240,88 290,72 340,58 400,47"
            fill="none" stroke="#f87171" stroke-width="3"/>
  <circle cx="400" cy="47" r="5" fill="#f87171"/>
  <text x="398" y="34" fill="#f87171" font-size="14" font-weight="bold" text-anchor="end">65% observed</text>
  <text x="40" y="205" fill="#8ea0bd" font-size="12">April</text>
  <text x="370" y="205" fill="#8ea0bd" font-size="12">June</text>
</svg>

Silent autonomy creep: no incident, no alert, no evidence trail — until the audit.

</div>
</div>

---

###### Why now

# The compliance clock is running.

<div class="cols">
<div class="col panel">
<div class="kpi">2 Dec 2027</div>
<div class="kpi-label">EU AI Act high-risk (Annex III) obligations — credit scoring, hiring, education. Digital Omnibus (June 2026) fixed the runway; Art. 9 demands <em>continuous</em> risk management, Art. 14 demonstrable human oversight.</div>
</div>
<div class="col panel">
<div class="kpi">83%</div>
<div class="kpi-label">of Fortune 500 procurement teams plan to require <em>ISO/IEC 42001</em> alignment from vendors by 2027 (Gartner 2026). Insurers already discount AI liability 15–25% for aligned firms.</div>
</div>
<div class="col panel">
<div class="kpi">~15×</div>
<div class="kpi-label">AI-governance spend growth projected: ~$0.4–0.9B (2025) → $6–7B by 2034-35, 23–35% CAGR. Financial services is the dominant segment.</div>
</div>
</div>

<br>

**The fastest-growing risk surface — agent runtime behavior — has no shipping control-monitor product.**

<div class="foot">Sources: Gibson Dunn & Covington on the EU Digital Omnibus (2026) · aigovernancetoday.com · TrendX Insights / Global Insight Services market reports. Details in docs/PITCH.md</div>

---

###### Market gap

# Telemetry isn't attestation. Documents aren't behavior.

<div style="display:flex; justify-content:center;">
<svg viewBox="0 0 760 340" width="88%">
  <line x1="380" y1="20" x2="380" y2="320" stroke="#22304d" stroke-width="1.5"/>
  <line x1="40" y1="170" x2="720" y2="170" stroke="#22304d" stroke-width="1.5"/>
  <text x="385" y="34" fill="#8ea0bd" font-size="13">RUNTIME ▲</text>
  <text x="385" y="312" fill="#8ea0bd" font-size="13">DESIGN-TIME ▼</text>
  <text x="46" y="163" fill="#8ea0bd" font-size="13">◀ TELEMETRY</text>
  <text x="600" y="163" fill="#8ea0bd" font-size="13">ATTESTATION ▶</text>

  <rect x="80" y="52" width="240" height="74" rx="10" fill="#111a2e" stroke="#22304d"/>
  <text x="100" y="80" fill="#e6edf7" font-size="16" font-weight="bold">Agent observability</text>
  <text x="100" y="100" fill="#8ea0bd" font-size="12">LangSmith · Langfuse · Arize —</text>
  <text x="100" y="116" fill="#8ea0bd" font-size="12">traces only, nothing attested</text>

  <rect x="80" y="216" width="240" height="74" rx="10" fill="#111a2e" stroke="#22304d"/>
  <text x="100" y="246" fill="#e6edf7" font-size="16" font-weight="bold">Eval / testing suites</text>
  <text x="100" y="270" fill="#8ea0bd" font-size="13">pre-deploy scores, blind in production</text>

  <rect x="440" y="216" width="240" height="74" rx="10" fill="#111a2e" stroke="#22304d"/>
  <text x="460" y="246" fill="#e6edf7" font-size="16" font-weight="bold">GRC / AI governance</text>
  <text x="460" y="270" fill="#8ea0bd" font-size="13">policy editors, registries — never touch a live trace</text>

  <rect x="440" y="44" width="240" height="90" rx="10" fill="#0d2818" stroke="#4ade80" stroke-width="2"/>
  <text x="460" y="76" fill="#4ade80" font-size="19" font-weight="bold">DriftLab</text>
  <text x="460" y="100" fill="#e6edf7" font-size="13">runtime behavior, diffed against a certified</text>
  <text x="460" y="118" fill="#e6edf7" font-size="13">baseline, proven by experiment, emitted as OSCAL</text>
</svg>
</div>

Infra drift detection (Terraform) proved this category works. **The agent-behavior quadrant is empty.**

---

###### How it works

# Certify once. Observe continuously. Prove on demand.

<div style="display:flex; justify-content:center; margin-top:10px;">
<svg viewBox="0 0 880 300" width="96%">
  <defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8ea0bd"/></marker></defs>

  <rect x="10" y="30" width="190" height="64" rx="10" fill="#111a2e" stroke="#22304d"/>
  <text x="24" y="56" fill="#e6edf7" font-size="15" font-weight="bold">Agent runtime</text>
  <text x="24" y="78" fill="#8ea0bd" font-size="12">LangGraph hook · JSONL · OTel</text>

  <rect x="10" y="190" width="190" height="64" rx="10" fill="#111a2e" stroke="#fbbf24"/>
  <text x="24" y="216" fill="#fbbf24" font-size="15" font-weight="bold">Certified baseline</text>
  <text x="24" y="238" fill="#8ea0bd" font-size="12">OSCAL profile · DL-1..7 · signed</text>

  <rect x="280" y="110" width="200" height="72" rx="10" fill="#111a2e" stroke="#60a5fa"/>
  <text x="296" y="138" fill="#60a5fa" font-size="15" font-weight="bold">Behavioral diff</text>
  <text x="296" y="160" fill="#8ea0bd" font-size="12">deterministic · 7 control checks</text>

  <rect x="560" y="30" width="200" height="72" rx="10" fill="#2b1220" stroke="#f87171"/>
  <text x="576" y="58" fill="#f87171" font-size="15" font-weight="bold">Micro-experiment</text>
  <text x="576" y="80" fill="#8ea0bd" font-size="12">sandboxed probe → verdict</text>

  <rect x="560" y="190" width="200" height="72" rx="10" fill="#0d2818" stroke="#4ade80"/>
  <text x="576" y="218" fill="#4ade80" font-size="15" font-weight="bold">Evidence</text>
  <text x="576" y="240" fill="#8ea0bd" font-size="12">score · ledger · OSCAL results</text>

  <line x1="200" y1="62" x2="280" y2="130" stroke="#8ea0bd" stroke-width="1.5" marker-end="url(#a)"/>
  <line x1="200" y1="222" x2="280" y2="160" stroke="#8ea0bd" stroke-width="1.5" marker-end="url(#a)"/>
  <line x1="480" y1="128" x2="560" y2="72" stroke="#8ea0bd" stroke-width="1.5" marker-end="url(#a)"/>
  <line x1="480" y1="160" x2="560" y2="218" stroke="#8ea0bd" stroke-width="1.5" marker-end="url(#a)"/>
  <line x1="660" y1="102" x2="660" y2="190" stroke="#8ea0bd" stroke-width="1.5" marker-end="url(#a)"/>
  <text x="672" y="152" fill="#8ea0bd" font-size="12">confirmed / refuted</text>
</svg>
</div>

**Seven certified controls (DL-1..7):** tool decision rights · routing rules · HITL triggers · fallback protocols · critical sinks · autonomy budget · required steps — each crosswalked to SP 800-53r5, anchored on **CA-7 continuous monitoring**. A staleness-weighted monitor runs the estate on cron/launchd.

---

###### The differentiator

# Alerts get argued with. **Proof doesn't.**

<div class="cols">
<div class="col">

Every finding becomes a **falsifiable hypothesis** with a probe spec. A LangGraph loop — *design → execute → evaluate → reflect* — re-tests it against a **sandboxed replay** of the full matching population.

- **Existence claims** — unauthorized tool, route, HITL bypass: one independently **reproduced violation is proof**; zero across sufficient samples refutes.
- **Rate claims** — autonomy budget: ordered windows must *sustain* the breach. A one-off burst stays inconclusive.

Verdicts are **computed from probe evidence — never LLM opinion**. Probes are replay-only; isolation is enforced in code and tested with booby-trapped sockets.

</div>
<div class="col panel" style="flex:0.9">

**Verdict semantics**

| Verdict | Meaning |
|---|---|
| <strong>CONFIRMED</strong> | violation reproduced on independent replay — escalate with evidence |
| <span style="color:#60a5fa">REFUTED</span> | did not reproduce — remediation verified, or false alarm caught |
| <span style="color:#fbbf24">INCONCLUSIVE</span> | thin evidence — widen the window, don't cry wolf |

Re-testing last cycle's confirmed drift against fresh traces gives you **remediation verification for free**.

</div>
</div>

---

###### Live demo (ships in the repo)

# One drifted agent. Four proofs. Score: 5/100.

<div class="cols">
<div class="col" style="flex:0.62">
<div class="panel" style="text-align:center">
<svg viewBox="0 0 300 150" width="82%">
  <path d="M 30 140 A 120 120 0 0 1 270 140" fill="none" stroke="#22304d" stroke-width="16" stroke-linecap="round"/>
  <path d="M 30 140 A 120 120 0 0 1 42 88" fill="none" stroke="#f87171" stroke-width="16" stroke-linecap="round"/>
  <text x="150" y="112" text-anchor="middle" fill="#f87171" font-size="44" font-weight="800">5</text>
  <text x="150" y="138" text-anchor="middle" fill="#8ea0bd" font-size="12">loan-officer · drifted</text>
</svg>
<svg viewBox="0 0 300 150" width="82%">
  <path d="M 30 140 A 120 120 0 0 1 270 140" fill="none" stroke="#22304d" stroke-width="16" stroke-linecap="round"/>
  <path d="M 30 140 A 120 120 0 0 1 270 140" fill="none" stroke="#4ade80" stroke-width="16" stroke-linecap="round"/>
  <text x="150" y="112" text-anchor="middle" fill="#4ade80" font-size="44" font-weight="800">100</text>
  <text x="150" y="138" text-anchor="middle" fill="#8ea0bd" font-size="12">support-triage · zero false positives</text>
</svg>
</div>
</div>
<div class="col">

**All four seeded drifts detected — and experimentally confirmed:**

| Drift | Probe evidence |
|---|---|
| HITL gate bypassed <em>(CRITICAL — reaches funds)</em> | **5/8** high-value runs, rate 0.625 |
| Autonomy 65% vs 40% budget | **3/3** windows sustain breach |
| Unvetted tool `external_data_broker` | **2** reproduced invocations |
| Error fallback skipped | **1/2** errors unhandled |

`driftlab demo` → detects, scores, proves, and writes the audit evidence in ~4 seconds. **88-test suite, fully offline.**

</div>
</div>

---

###### Evidence

# The output *is* the audit artifact.

<div class="cols">
<div class="col">

Per agent, per cycle:

- **`assessment-results.json`** — OSCAL 1.1.2: observations with trace evidence, per-control `satisfied` / `not-satisfied` findings, experiment verdicts with reproduction counts
- **`assessment-plan.json`** — generated from the certified baseline (CA-7 cadence)
- **`ledger.json`** — deterministic anomaly ledger: same inputs → **byte-identical bytes**. An auditor can re-run the diff.
- **`report.md`** — human-readable summary

Maps onto **EU AI Act Art. 9 / 12 / 14 · ISO 42001 §8 · SOC 2 monitoring criteria**.

</div>
<div class="col panel" style="font-family: ui-monospace, Menlo, monospace; font-size:14px; line-height:1.7;">
<span style="color:#8ea0bd">// cycle finding, loan-officer</span><br>
"target": { "target-id": "<b style="color:#e6edf7">dl-3_smt</b>",<br>
&nbsp;&nbsp;"status": { "state": "<span style="color:#f87171">not-satisfied</span>" }}<br>
<span style="color:#8ea0bd">// linked micro-experiment</span><br>
"title": "micro-experiment: <span style="color:#f87171">CONFIRMED</span> — missing_hitl",<br>
"props": [<br>
&nbsp;&nbsp;{ "name": "dl:verdict", "value": "confirmed" },<br>
&nbsp;&nbsp;{ "name": "dl:probe-violations", "value": "<b style="color:#4ade80">5</b>" },<br>
&nbsp;&nbsp;{ "name": "dl:probe-samples", "value": "<b style="color:#4ade80">8</b>" },<br>
&nbsp;&nbsp;{ "name": "dl:sandbox", "value": "replay" }]<br>
<span style="color:#8ea0bd">// clean agents attest positively</span><br>
"target-id": "dl-5_smt" → "<span style="color:#4ade80">satisfied</span>"
</div>
</div>

---

###### Moat

# Built where SaaS can't follow.

<div class="cols">
<div class="col panel">

**Local-first**
Traces never leave the host. Deploys inside bank change-control, air-gapped dashboards included. No SaaS observability vendor can sit here.

</div>
<div class="col panel">

**Deterministic**
Pure-Python compliance path. Byte-identical ledgers, content-derived IDs. *Reproducibility is the audit feature.*

</div>
<div class="col panel">

**Experimental proof**
The only system that closes the loop from "flagged" to "reproduced." Collapses triage debates into evidence.

</div>
<div class="col panel">

**OSCAL-native**
Output drops into NIST-standard evidence pipelines. First mover on **CA-7 for agent behavior**.

</div>
</div>

<br>

Four of five engines are proven sw30labs systems — **glass-graph** (deterministic diff), **regitel** (staleness monitor), **governance-oscal** (compliance schemas), **setpoint** (experiment pattern). *The integration is the product, and it exists today.*

---

###### Competition

# Nobody occupies the intersection.

| Capability | LangSmith / Langfuse / Arize | GRC & AI-gov platforms | Infra drift (Terraform et al.) | **DriftLab** |
|---|---|---|---|---|
| Sees runtime agent decisions | ✔ traces | ✖ | ✖ | **✔ canonical events** |
| Diffs against certified baseline | ✖ | ✖ documents only | ✔ for infra | **✔ behavioral, 7 controls** |
| Proves drift experimentally | ✖ | ✖ | ✖ | **✔ sandboxed probes** |
| Emits audit-grade OSCAL | ✖ | partial, manual | ✖ | **✔ per cycle, CA-7** |
| Runs fully on-prem / air-gapped | partial | partial | ✔ | **✔ local-first by design** |

<br>

Observability players *could* add attestation — but their architecture (cloud telemetry, no baseline semantics, LLM-scored evals) points the other way. **DriftLab starts where they stop.**

---

###### Go-to-market

# Land on one agent. Expand to the estate.

<div class="cols">
<div class="col">

**Beachhead** — Tier-1/2 financial services running agents in **Annex III workflows**. Credit decisioning is the canonical named high-risk case — and our shipped demo.

**Wedge deal** — one agent, one certified baseline, one regulator conversation. 90-day pilot; success = an audit finding closed with DriftLab evidence.

**Then** — insurers, EU-regulated SaaS, government suppliers chasing ISO 42001 procurement requirements.

</div>
<div class="col panel">

**Business model**

| Motion | Revenue |
|---|---|
| Self-host license | per monitored estate / yr — a *compliance* budget line, not tooling |
| Certification advisory | fixed-fee baseline certification per agent archetype |
| Audit-as-a-service | evidence packs per assessment window |

**Compliance spend survives tooling winters.**

</div>
</div>

---

###### Roadmap

# From evidence engine to regulatory autopilot.

<div style="display:flex; justify-content:center; margin-top:6px;">
<svg viewBox="0 0 880 120" width="98%">
  <line x1="60" y1="60" x2="820" y2="60" stroke="#22304d" stroke-width="2"/>
  <circle cx="130" cy="60" r="9" fill="#4ade80"/>
  <text x="130" y="34" text-anchor="middle" fill="#4ade80" font-size="15" font-weight="bold">v0.1 — today</text>
  <text x="130" y="92" text-anchor="middle" fill="#8ea0bd" font-size="12">7 controls · proof loop · 88 tests</text>
  <circle cx="340" cy="60" r="9" fill="#60a5fa"/>
  <text x="340" y="34" text-anchor="middle" fill="#60a5fa" font-size="15" font-weight="bold">v0.2 — +6 wks</text>
  <text x="340" y="92" text-anchor="middle" fill="#8ea0bd" font-size="12">OTel ingest · strict OSCAL CI</text>
  <circle cx="550" cy="60" r="9" fill="#fbbf24"/>
  <text x="550" y="34" text-anchor="middle" fill="#fbbf24" font-size="15" font-weight="bold">v0.3 — quarter</text>
  <text x="550" y="92" text-anchor="middle" fill="#8ea0bd" font-size="12">live-clone probes · 3-way diff</text>
  <circle cx="750" cy="60" r="9" fill="#f87171"/>
  <text x="750" y="34" text-anchor="middle" fill="#f87171" font-size="15" font-weight="bold">v2 / v3</text>
  <text x="750" y="92" text-anchor="middle" fill="#8ea0bd" font-size="12">estate intel · reg auto-mapping</text>
</svg>
</div>

<br>

**v2**: estate intelligence — cross-agent drift correlation, drift-to-change attribution, one-click evidence packs.
**v3**: EU AI Act / ISO 42001 text auto-mapped to DL-control parameterizations; continuous authorization with drift SLOs.

---

<!-- _class: lead -->

###### The ask

# 2–3 design partners. 90 days each.

Regulated teams running agents in production. Success is binary: **one audit finding closed with DriftLab evidence.**

<br>

**Nicolas Cravino** · sw30labs · ncravino@mac.com
`github: sw30labs/driftlab` — working demo: `uv run driftlab demo`

<span class="tag">deterministic compliance path</span><span class="tag">traces never leave the host</span><span class="tag">verdicts from evidence, never LLM opinion</span>
