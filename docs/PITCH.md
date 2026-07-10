# DriftLab — the control monitor for the agentic economy

*One-pager · sw30labs · July 2026*

## Problem

Enterprises are deploying autonomous agents into regulated workflows — credit
decisioning, claims, support, treasury — faster than they can govern them. All
current governance is **design-time** (policy documents, canvases, one-shot
audits) or **static** (build-time graph diffs). Meanwhile the thing regulators
actually care about is **runtime behavior**: did the agent route high-value
decisions past the human gate? Did it quietly acquire a new tool? Did its
autonomy rate creep from 40% to 65%? Today nobody can answer with evidence.
Agent observability tools (LangSmith, Langfuse, Arize) record telemetry but
attest nothing; GRC platforms hold documents but never touch a live trace.

## Solution

**DriftLab** is a continuous, machine-readable compliance observer for running
agents. Teams certify intended behavior as an **OSCAL baseline** (decision
rights, routing rules, human-in-the-loop triggers, autonomy budgets, fallback
protocols, critical sinks). DriftLab taps the agent's decision traces, diffs
observed behavior against the baseline every cycle, and — uniquely — **proves
suspected drift with a micro-experiment**: a controlled probe against a
sandboxed replay that reproduces the violation or refutes it. Output per
cycle: a compliance score, a deterministic anomaly ledger, and OSCAL
1.1.2-shaped assessment artifacts designed to support SOC 2 / EU AI Act / ISO
42001 evidence workflows (anchored on SP 800-53 **CA-7**, continuous
monitoring). v0.1 documents one assessment-plan deviation and does not yet
claim strict OSCAL schema conformance.

Working v1 today: 7-control behavioral catalog, deterministic diff + scoring
engine, experiment loop with sandboxed replay (verdicts are evidence-computed,
never LLM opinion), staleness-weighted estate monitor, estate dashboard,
92-test suite. Demo: a drifted loan-officer agent scores 5/100 with all four
seeded drifts detected *and experimentally confirmed*; its compliant twin
scores 100 with zero false positives.

## Why now

* **EU AI Act**: the June 2026 Digital Omnibus fixed the high-risk (Annex III —
  credit scoring, recruitment, education) compliance deadline at **2 December
  2027**.¹ Risk management must be a "continuous iterative process" (Art. 9),
  human oversight demonstrable (Art. 14), logging mandatory (Art. 12). The
  build-out window for continuous evidence is *now*.
* **Auditable AI governance is standardizing**: ISO/IEC 42001 is the first
  international AI management-system standard; ISO/IEC 42006 adds requirements
  for bodies that audit and certify those systems, creating a consistent,
  credible certification path.²
* **AI governance spend** is projected to grow from ~$0.4–0.9B (2025) to
  $6–7B by 2034–35 (23–35% CAGR)³ — while the fastest-growing risk surface,
  *agent runtime behavior*, has no shipping control-monitor product.

## White-space proof

Observability vendors trace, they don't attest: none diff against a certified
baseline, none emit OSCAL, none prove drift. GRC/model-risk platforms are
document-time. Infrastructure drift detection (Terraform et al.) proves the
category works — the agent-behavior equivalent is simply absent. The
combination (runtime decision capture) × (deterministic baseline diff) ×
(OSCAL evidence) × (experimental proof) is unoccupied.

## Moat

**Local-first + deterministic + evidence-grade.** Trace files and artifacts
stay on operator-controlled systems; the optional analyst talks only to the
operator-configured OMLX endpoint, never a third-party OpenAI service. That is
deployable inside bank change-control, where SaaS observability can't go. The
compliance path is pure deterministic Python: same inputs,
byte-identical ledger — an auditor can re-run it. The experiment engine turns
alerts into *reproduced evidence*, collapsing the triage debate. The
OSCAL-shaped design structures output for evidence workflows while explicitly
documenting v0.1's schema deviation; strict validation is the next hardening
milestone.
Four of the five engines are proven in sw30labs production-shaped systems
(glass-graph, regitel, governance-oscal, setpoint); the integration is the
product.

## Beachhead & model

Tier-1/2 financial services deploying agents into Annex III workflows (credit
decisioning is literally the canonical high-risk use case), then insurers and
EU-regulated SaaS. Land: self-host license per monitored estate (compliance
budget line, not tooling). Expand: certification advisory ("certify your
agent baselines") and audit-as-a-service (evidence packs per assessment
window). Wedge deal: one agent, one baseline, one regulator conversation.

## Ask

Design-partner pilots: 2–3 regulated teams running agents in production, 90
days each, success = one audit finding closed with DriftLab evidence.

---
¹ [Gibson Dunn — EU AI Act Omnibus Agreement](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/) · [Inside Global Tech, May 2026](https://www.insideglobaltech.com/2026/05/28/eu-ai-act-update-timeline-relief-targeted-simplification-and-new-prohibitions/)
² [ISO — ISO/IEC 42001:2023](https://www.iso.org/standard/42001) · [ISO — ISO/IEC 42006:2025](https://www.iso.org/standard/42006)
³ [TrendX Insights — AI Governance Market](https://trendxinsights.com/syndicated-market-research-reports/ai-governance-market/) · [Global Insight Services](https://www.globalinsightservices.com/press-releases/ai-governance-market/)
