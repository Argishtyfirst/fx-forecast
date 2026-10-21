"""Failure alerts (NFR-04): Slack webhook, email, and always the structured log."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

import httpx

from fxf.config import get_settings
from fxf.logging_setup import get_logger

log = get_logger(__name__)

# Tests replace this list to capture alerts without network calls.
SENT: list[dict[str, str]] = []


def send_alert(title: str, text: str) -> None:
    s = get_settings()
    SENT.append({"title": title, "text": text})
    log.error("alert", extra={"alert_title": title, "alert_text": text})
    if s.slack_webhook_url:
        try:
            httpx.post(s.slack_webhook_url, json={"text": f"*{title}*\n{text}"}, timeout=10)
        except Exception as exc:  # an alert failure must never mask the original error
            log.warning("slack alert failed", extra={"error": str(exc)})
    if s.alert_email_to and s.smtp_url:
        try:
            _send_email(s.smtp_url, s.alert_email_to, title, text)
        except Exception as exc:
            log.warning("email alert failed", extra={"error": str(exc)})


def _send_email(smtp_url: str, to: str, title: str, text: str) -> None:
    # smtp_url form: smtp://user:pass@host:port
    u = urlparse(smtp_url)
    msg = EmailMessage()
    msg["Subject"] = f"[fxf] {title}"
    msg["From"] = u.username or "fxf@localhost"
    msg["To"] = to
    msg.set_content(text)
    with smtplib.SMTP(u.hostname or "localhost", u.port or 587, timeout=10) as smtp:
        smtp.starttls()
        if u.username and u.password:
            smtp.login(u.username, u.password)
        smtp.send_message(msg)
