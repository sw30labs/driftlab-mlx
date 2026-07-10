"""SMTP digest notifier.

Sends a plain-text digest of a monitor run. Never raises: any SMTP failure is
swallowed and printed so a notification problem can never abort a compliance
cycle (regitel-style resilience).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from ..config import get_settings


def build_digest_text(summary: dict[str, Any]) -> str:
    lines = ["DriftLab monitor digest", "=" * 24, ""]
    lines.append(f"Ran: {len(summary.get('ran', []))} agent(s)")
    for r in summary.get("ran", []):
        lines.append(f"  - {r['agent']}: score {r['score']}/100  cycle {r['cycle_id']}")
    if summary.get("skipped"):
        lines.append(f"Skipped (not due): {', '.join(summary['skipped'])}")
    if summary.get("errors"):
        lines.append("Errors:")
        for e in summary["errors"]:
            lines.append(f"  - {e['agent']}: {e['error']}")
    return "\n".join(lines)


def send_digest(summary: dict[str, Any]) -> bool:
    settings = get_settings()
    if not settings.email__enabled:
        return False
    msg = EmailMessage()
    msg["Subject"] = "DriftLab monitor digest"
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg.set_content(build_digest_text(summary))
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            if settings.smtp_user:
                s.starttls()
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except Exception as exc:  # never raise from a notifier
        print(f"[driftlab] digest send failed (non-fatal): {exc}")
        return False