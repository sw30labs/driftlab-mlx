"""SMTP digest delivery — regitel monitor/notifier.py, ported.

Config-first, env-fallback (DRIFTLAB_* names). Raises NotifierError with the
exact missing keys; the runner catches it — a broken mail setup must never
kill a monitoring cycle."""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from driftlab.config import EmailSettings


class NotifierError(RuntimeError):
    pass


def resolve_smtp_settings(cfg: EmailSettings) -> dict:
    host = cfg.smtp_host or os.environ.get("SMTP_HOST")
    port = cfg.smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = cfg.smtp_user or os.environ.get("SMTP_USER")
    password = cfg.smtp_password or os.environ.get("SMTP_PASSWORD")
    to = cfg.to or os.environ.get("DRIFTLAB_EMAIL_TO")
    sender = cfg.sender or os.environ.get("DRIFTLAB_EMAIL_FROM") or user

    missing = [
        key
        for key, value in {
            "smtp_host/SMTP_HOST": host,
            "smtp_user/SMTP_USER": user,
            "smtp_password/SMTP_PASSWORD": password,
            "to/DRIFTLAB_EMAIL_TO": to,
        }.items()
        if not value
    ]
    if missing:
        raise NotifierError("Email delivery not configured — missing: " + ", ".join(missing))
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "to": to,
        "sender": sender,
        "use_tls": cfg.use_tls,
    }


def send_digest_email(cfg: EmailSettings, *, subject: str, text_body: str, html_body: str) -> str:
    settings = resolve_smtp_settings(cfg)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{cfg.subject_prefix} {subject}"
    msg["From"] = settings["sender"]
    msg["To"] = settings["to"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings["port"] == 465:
            server = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=30)
        else:
            server = smtplib.SMTP(settings["host"], settings["port"], timeout=30)
            if settings["use_tls"]:
                server.starttls()
        with server:
            server.login(settings["user"], settings["password"])
            server.sendmail(settings["sender"], [settings["to"]], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifierError(f"SMTP delivery failed: {exc}") from exc
    return str(settings["to"])
