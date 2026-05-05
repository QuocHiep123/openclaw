"""
SMTP utilities for sending reports via Gmail.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


class EmailConfigError(ValueError):
    """Raised when required email configuration is missing."""


def send_email_with_attachment(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str | Path,
    sender_email: str | None = None,
    app_password: str | None = None,
) -> None:
    """
    Send a single email with one attachment using Gmail SMTP over SSL.
    """
    sender = sender_email or os.getenv("GMAIL_ADDRESS", "").strip()
    password = app_password or os.getenv("GMAIL_APP_PASSWORD", "").strip()

    if not sender:
        raise EmailConfigError("Missing GMAIL_ADDRESS")
    if not password:
        raise EmailConfigError("Missing GMAIL_APP_PASSWORD")

    file_path = Path(attachment_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Attachment not found: {file_path}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)

    data = file_path.read_bytes()
    msg.add_attachment(
        data,
        maintype="application",
        subtype="pdf",
        filename=file_path.name,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
