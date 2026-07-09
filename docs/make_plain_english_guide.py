"""Generate docs/DriftLab-Plain-English-Guide.pdf (reportlab).

Re-run after significant product changes:  python docs/make_plain_english_guide.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent / "DriftLab-Plain-English-Guide.pdf"

INK = colors.HexColor("#1f2328")
MUTED = colors.HexColor("#5b6472")
GREEN = colors.HexColor("#2f9e44")
RED = colors.HexColor("#c92a2a")
AMBER = colors.HexColor("#b8860b")
LINE = colors.HexColor("#d9dee5")
PANEL = colors.HexColor("#f4f6f8")
NAVY = colors.HexColor("#0b1220")

base = getSampleStyleSheet()

def st(name, **kw):
    defaults = dict(fontName="Helvetica", fontSize=10.5, leading=15.5, textColor=INK, alignment=TA_LEFT, spaceAfter=7)
    defaults.update(kw)
    return ParagraphStyle(name, parent=base["Normal"], **defaults)

S = {
    "title": st("t", fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=NAVY, spaceAfter=2),
    "subtitle": st("sub", fontSize=13, leading=18, textColor=MUTED, spaceAfter=14),
    "kicker": st("k", fontName="Helvetica-Bold", fontSize=9, textColor=MUTED, spaceAfter=4),
    "h1": st("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceBefore=16, spaceAfter=6),
    "h2": st("h2", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=4),
    "body": st("b"),
    "quote": st("q", leftIndent=10, textColor=MUTED, fontSize=10, leading=14.5),
    "code": st("c", fontName="Courier", fontSize=9.5, leading=13.5, backColor=PANEL, borderPadding=6, leftIndent=4, spaceBefore=4, spaceAfter=8),
    "small": st("s", fontSize=9, leading=12.5, textColor=MUTED),
}


def para(text, style="body"):
    return Paragraph(text, S[style])


def rule():
    return HRFlowable(width="100%", thickness=0.7, color=LINE, spaceBefore=6, spaceAfter=10)


def tbl(data, widths, header=True, fontsize=9.5):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), fontsize),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, MUTED),
        ]
    t.setStyle(TableStyle(style))
    return t


def cell(text, bold=False, color=None, size=9.5):
    face = "Helvetica-Bold" if bold else "Helvetica"
    c = f' color="{color}"' if color else ""
    return Paragraph(f'<font face="{face}" size="{size}"{c}>{text}</font>', S["body"])


story = []

# ---------------------------------------------------------------- title
story += [
    para("SW30LABS · JULY 2026 · FOR NON-SPECIALIST READERS", "kicker"),
    para("DriftLab", "title"),
    para("A plain-English guide to what it does and how to run it", "subtitle"),
    rule(),
    para(
        "This guide explains DriftLab without assuming you write software for a living. "
        "It covers the problem it solves, how it works, what its results mean, how to run it "
        "on your own machine, and what every important word means. The technical companion "
        "documents (README, RUNBOOK, CERTIFICATION-GUIDE) live in the same folder."
    ),
]

# ---------------------------------------------------------------- 1
story += [
    para("1. The problem, in one minute", "h1"),
    para(
        "Companies increasingly use <b>AI agents</b> — software that doesn't just answer questions "
        "but makes decisions and takes actions on its own: approving a loan, routing a customer "
        "complaint, moving a case forward. Before such an agent goes live, someone writes down the "
        "rules it must follow: <i>loans above 50,000 need a human reviewer; it may only use these "
        "five tools; after an error it must escalate to a person.</i>"
    ),
    para(
        "The problem is what happens <b>after</b> launch. Agents change quietly — a model gets "
        "upgraded, a prompt gets tweaked, a new tool gets added — and their behavior drifts away "
        "from the agreed rules without anyone noticing. There's no crash and no alarm. Weeks later, "
        "an auditor or regulator asks: <i>“Can you prove your AI followed your rules last "
        "quarter?”</i> — and today, almost nobody can. Monitoring tools show <i>what the agent did</i> "
        "(useful for debugging), but nothing checks it against <i>what it was allowed to do</i>."
    ),
]

# ---------------------------------------------------------------- 2
story += [
    para("2. What DriftLab does", "h1"),
    para(
        "DriftLab is a <b>compliance observer for running AI agents</b>. Think of it as three things "
        "in one: a <b>security camera</b> that records every decision the agent makes, an "
        "<b>inspector</b> that regularly compares those recordings against the certified rulebook, "
        "and a <b>small laboratory</b> that double-checks every suspected violation before anyone "
        "gets alarmed. At the end of each check it prints the paperwork an auditor would ask for."
    ),
    para("The whole cycle, step by step:", "h2"),
]
flow = [
    ("1", "Record", "The agent keeps a diary. Every decision — which tool it used, where it sent a case, whether it asked a human — is written down as one line in a log file. Nothing leaves your machine."),
    ("2", "Compare", "On a schedule, DriftLab reads the diary and compares it, rule by rule, against the certified rulebook. This step is pure arithmetic — no AI judgment involved. The same diary and the same rulebook always give exactly the same answer."),
    ("3", "Double-check", "For every suspected violation, DriftLab forms a precise claim (“high-value cases are skipping human review”) and re-tests it against a replay of the recordings. Only claims that reproduce are labelled CONFIRMED."),
    ("4", "Report", "Each check produces a compliance score (0–100), a findings list with the evidence attached, and standard audit documents. A dashboard shows the whole fleet at a glance; an optional email digest arrives only when something actually needs attention."),
]
story.append(tbl(
    [[cell("", bold=True), cell("STEP", bold=True), cell("WHAT HAPPENS", bold=True)]] +
    [[cell(n, bold=True, color="#2f9e44"), cell(t, bold=True), cell(d)] for n, t, d in flow],
    [10 * mm, 28 * mm, 122 * mm],
))

# ---------------------------------------------------------------- 3
story += [
    para("3. The rulebook: seven kinds of rules", "h1"),
    para(
        "The rulebook (DriftLab calls it a <b>certified baseline</b>) is a file your compliance team "
        "signs off. It answers seven questions about the agent. You don't have to answer all seven "
        "on day one — anything you leave out simply isn't monitored yet."
    ),
]
rules = [
    ("Tools", "Which tools may the agent use, and where? Like a staff badge that only opens certain doors."),
    ("Routes", "Which paths may a case take through the agent? A loan may go from “assess” to “human review”, but never straight from “intake” to “payout”."),
    ("Human review", "Which decisions must a person see before they count? E.g. any loan above 50,000, or any angry customer."),
    ("After errors", "When something fails, what must happen next? Usually: hand the case to a human, don't just carry on."),
    ("Points of no return", "Which actions can't be undone (paying out money, sending a customer a commitment)? Any rule broken on the way to one of these is treated as far more serious."),
    ("Autonomy budget", "What share of decisions may the agent take fully on its own? E.g. at most 40% — the rest must involve a person somewhere."),
    ("Mandatory steps", "Which steps must happen in every single case (e.g. the risk assessment), and the duty to keep recording the diary at all."),
]
story.append(tbl(
    [[cell("RULE FAMILY", bold=True), cell("PLAIN-ENGLISH MEANING", bold=True)]] +
    [[cell(a, bold=True), cell(b)] for a, b in rules],
    [34 * mm, 126 * mm],
))
story += [
    Spacer(1, 4),
    para(
        "Technically, the rulebook is stored in <b>OSCAL</b> — a machine-readable compliance format "
        "published by NIST (the US standards institute). That matters for one reason: the reports "
        "DriftLab produces are in the same standard format, so they slot directly into audit "
        "processes for SOC 2, ISO/IEC 42001 and the EU AI Act instead of being yet another "
        "proprietary export.", "body",
    ),
]

# ---------------------------------------------------------------- 4
story += [
    PageBreak(),
    para("4. What a result looks like", "h1"),
    para(
        "DriftLab ships with a built-in demonstration: a fictional <b>loan-officer</b> agent whose "
        "recordings contain four planted rule violations, and a well-behaved <b>support-triage</b> "
        "agent as a control. Running the demo takes a few seconds and finds exactly this:"
    ),
]
demo = [
    ("Human review skipped", "5 of the 8 high-value loans went through without a person seeing them.", "CRITICAL — the skipped review sits on the path to paying out money", "CONFIRMED (reproduced on 5 of 8 matching cases)"),
    ("Too much autonomy", "65% of decisions were fully automatic; the certified budget is 40%.", "HIGH", "CONFIRMED (the excess holds in every time window — it's sustained, not a blip)"),
    ("Unapproved tool", "The agent started using a data source that was never certified.", "HIGH", "CONFIRMED (2 uses reproduced)"),
    ("Error handled wrongly", "After a failure, the agent carried on instead of escalating to a person.", "HIGH", "CONFIRMED (1 of 2 errors mishandled)"),
]
story.append(tbl(
    [[cell("FINDING", bold=True), cell("WHAT HAPPENED", bold=True), cell("SEVERITY", bold=True), cell("DOUBLE-CHECK VERDICT", bold=True)]] +
    [[cell(a, bold=True), cell(b), cell(c, color="#c92a2a" if c.startswith("CRITICAL") else "#b8860b"), cell(d)] for a, b, c, d in demo],
    [30 * mm, 46 * mm, 42 * mm, 42 * mm],
    fontsize=9,
))
story += [
    Spacer(1, 4),
    para(
        "The drifted agent scores <b><font color='#c92a2a'>5 / 100</font></b>. Its well-behaved twin "
        "scores <b><font color='#2f9e44'>100 / 100</font></b> with zero findings — DriftLab does not "
        "invent problems where there are none. Severity levels read as follows: <b>CRITICAL</b> "
        "means a certified rule was broken on a path that reaches a point of no return — treat it "
        "like an incident. <b>HIGH</b> means a rule was clearly broken. <b>MEDIUM/LOW</b> are "
        "degradations and data-quality warnings. The score starts at 100 and loses points per "
        "finding, weighted by severity."
    ),
    para("The three double-check verdicts", "h2"),
    para(
        "<b><font color='#c92a2a'>CONFIRMED</font></b> — the violation reproduced when re-tested "
        "against the recordings; the report includes the exact cases and counts. Escalate with "
        "confidence. &nbsp;&nbsp;<b><font color='#1c6fd4'>REFUTED</font></b> — the claim did not "
        "reproduce. Either the problem was fixed (re-testing after a fix is free), or a false alarm "
        "was caught before it wasted anyone's time. &nbsp;&nbsp;<b><font color='#b8860b'>"
        "INCONCLUSIVE</font></b> — not enough matching cases to say either way; collect more "
        "recordings first. DriftLab deliberately refuses to cry wolf on thin evidence."
    ),
]

# ---------------------------------------------------------------- 5
story += [
    para("5. How to run it", "h1"),
    para("You need a Mac or Linux machine with Python 3.11 or newer and the <b>uv</b> tool. Everything runs locally; no account, no cloud, no data leaves the machine.", "body"),
    para("First contact (five minutes)", "h2"),
    para("cd /Users/spider/Code/REPOS/driftlab<br/>uv sync --all-extras&nbsp;&nbsp;&nbsp;&nbsp;# installs everything into a local environment<br/>uv run driftlab demo&nbsp;&nbsp;&nbsp;&nbsp;# runs the built-in demonstration above<br/>uv run driftlab dashboard&nbsp;&nbsp;# then open http://127.0.0.1:8321 in a browser", "code"),
    para(
        "The dashboard shows every monitored agent with its score, its findings, its double-check "
        "verdicts, and download links for the audit documents. Green means compliant; red means look "
        "now."
    ),
    para("Watching your own agent (three steps)", "h2"),
]
steps = [
    ("A. Record the diary", "Have your agent write its decisions to a log file (one JSON line per decision). If it's built with LangGraph/LangChain, DriftLab ships a ready-made recorder you attach with two lines of code. Otherwise any process that emits the simple diary format works."),
    ("B. Write the rulebook", "Copy the demo rulebook and adapt it: your tools, your routes, your review thresholds. The CERTIFICATION-GUIDE walks through this line by line. Typos fail loudly on purpose — a misspelled rule must never silently certify less than you meant."),
    ("C. Register the agent", "Add one entry (name, priority 1–7, rulebook file, diary file) to a small list called the registry, and point DriftLab at it. Priority 1 means “check daily”; 7 means “monthly”."),
]
story.append(tbl([[cell(a, bold=True), cell(b)] for a, b in steps], [40 * mm, 120 * mm], header=False))
story += [
    para("Making it automatic", "h2"),
    para(
        "One command — <font face='Courier'>driftlab monitor run --scheduled</font> — checks whatever "
        "is due and goes back to sleep. Put it on a daily timer (ready-made macOS and cron templates "
        "are in the <font face='Courier'>ops/</font> folder) and DriftLab decides internally which "
        "agents actually need checking, based on their priority and how long ago they were last "
        "seen. Running it twice does no harm. If you configure email, a digest is sent <i>only</i> "
        "when there is something worth reading: a new critical finding, a confirmed drift, a score "
        "drop, or an error. A broken mail server never stops the checks themselves."
    ),
    para("What each check leaves behind", "h2"),
    para(
        "Four files per agent per check, saved locally: <b>report.md</b> — the human-readable "
        "summary; <b>ledger.json</b> — the findings with evidence, written so that re-running the "
        "same check produces a byte-for-byte identical file (an auditor can verify it themselves); "
        "and <b>assessment-plan.json / assessment-results.json</b> — the standard OSCAL audit "
        "documents, including positive attestations for every rule that was checked and held."
    ),
]

# ---------------------------------------------------------------- 6
story += [
    PageBreak(),
    para("6. What DriftLab will never do", "h1"),
    para(
        "<b>It never touches your live agent.</b> All double-checks run against replays of the "
        "recordings, in memory. The code physically refuses to probe anything that isn't an isolated "
        "copy, and the test suite proves the entire double-check machinery runs with networking "
        "disabled."
    ),
    para(
        "<b>It never sends your data anywhere.</b> Diaries, rulebooks, findings, and reports all stay "
        "on your machine. Even the dashboard works with no internet connection."
    ),
    para(
        "<b>AI never decides a finding.</b> DriftLab can optionally use a local language model to add "
        "readable summaries to reports — prose only. Every finding, severity, score, and verdict "
        "comes from the deterministic comparison and the replayed evidence. Unplug the language "
        "model and every number stays identical (this is tested, not promised)."
    ),
    para(
        "<b>It never buries a decision you made.</b> If you formally accept a known issue (a "
        "“waiver”), the finding stays visible on every report, marked as waived, with an expiry date "
        "— acceptance lowers the alarm level, never the visibility."
    ),
]

# ---------------------------------------------------------------- 7
story += [
    para("7. Command cheat-sheet", "h1"),
]
cmds = [
    ("driftlab demo", "Run the built-in demonstration end to end"),
    ("driftlab agents", "List monitored agents and when each is next due"),
    ("driftlab check --agent NAME", "Check one agent right now"),
    ("driftlab monitor run", "Check whatever is due (add --force to check everything)"),
    ("driftlab monitor status", "History of recent monitoring runs"),
    ("driftlab report CYCLE-ID", "Print the human-readable report of one check"),
    ("driftlab dashboard", "Serve the web dashboard on http://127.0.0.1:8321"),
]
story.append(tbl(
    [[cell("COMMAND", bold=True), cell("WHAT IT DOES", bold=True)]] +
    [[Paragraph(f'<font face="Courier" size="9">{a}</font>', S["body"]), cell(b)] for a, b in cmds],
    [62 * mm, 98 * mm],
))
story += [
    Spacer(1, 2),
    para("Prefix with <font face='Courier'>uv run</font> when working inside the project folder.", "small"),
]

# ---------------------------------------------------------------- 8
story += [
    para("8. Glossary", "h1"),
]
glossary = [
    ("Agent", "Software that makes decisions and takes actions on its own, usually powered by an AI model."),
    ("Trace / diary", "The chronological record of every decision an agent made, one line per decision."),
    ("Baseline / rulebook", "The certified, machine-readable statement of how the agent is allowed to behave."),
    ("Drift", "The gap between what the agent was certified to do and what it actually does, appearing gradually and silently."),
    ("Human-in-the-loop (HITL)", "A rule that certain decisions must be reviewed by a person before they take effect."),
    ("Critical sink / point of no return", "A step whose effects can't be taken back — paying out funds, sending a binding reply."),
    ("Micro-experiment / probe", "A controlled re-test of one suspected violation against a replay of the recordings; produces CONFIRMED, REFUTED, or INCONCLUSIVE."),
    ("Sandbox / replay", "The isolated, in-memory copy of the recordings that experiments run against — never the live system."),
    ("Deterministic", "Same inputs, same outputs, every single time. No randomness, no AI judgment. The property that makes results auditable."),
    ("Compliance score", "0–100 summary per check: starts at 100, loses points per finding, weighted by severity."),
    ("OSCAL", "The NIST-published machine-readable format for compliance documents; what auditors' tooling can ingest directly."),
    ("Waiver", "A formally accepted, time-boxed exception to a finding — visible on every report until it expires."),
]
story.append(tbl([[cell(a, bold=True), cell(b)] for a, b in glossary], [44 * mm, 116 * mm], header=False, fontsize=9.5))

story += [
    Spacer(1, 10),
    rule(),
    para(
        "DriftLab v0.1 · sw30labs · Nicolas Cravino · ncravino@mac.com — Companion documents: "
        "README.md (technical overview), docs/RUNBOOK.md (day-to-day operations), "
        "docs/CERTIFICATION-GUIDE.md (writing a rulebook), ROADMAP.md (what's next).",
        "small",
    ),
]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, "DriftLab — Plain-English Guide")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
    title="DriftLab — A Plain-English Guide", author="sw30labs",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(f"wrote {OUT}")
