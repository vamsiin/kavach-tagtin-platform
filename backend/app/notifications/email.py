"""
Email notifications for workflow events (assignment, check/reject, approve/reject).

Uses only the standard library (smtplib, email.message) -- no SendGrid/Mailgun/SES
SDK dependency, since the actual requirement is "send an email", not any particular
provider's API. If a real provider's API is preferred later (for delivery tracking,
templates, etc.), only this module needs to change -- callers just call send_email().

Honest limitation, same pattern as the password-reset flow: if SMTP is not
configured via environment variables, this does NOT silently fail and does NOT
pretend to send -- it logs the email that *would* have been sent to the console,
clearly labeled, so local/dev use (and this platform's own test suite) works
without requiring a real mail server, while making it obvious in production that
configuration is missing rather than emails silently vanishing.

Required environment variables for real sending:
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS
Optional:
    SMTP_USE_TLS (default "true")
"""
from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class EmailResult:
    sent: bool
    mode: str  # "smtp" | "console-fallback"
    to: list[str]
    subject: str
    error: str | None = None


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM_ADDRESS"))


def send_email(to: list[str], subject: str, body: str) -> EmailResult:
    """Sends an email if SMTP_* environment variables are configured; otherwise
    prints the email to the console and returns sent=False with mode="console-
    fallback" so callers/tests can distinguish "really sent" from "logged only"
    without needing to parse stdout."""
    to = [addr for addr in to if addr]  # drop empty/None addresses silently
    if not to:
        return EmailResult(sent=False, mode="console-fallback", to=[], subject=subject,
                            error="No recipient addresses provided (user(s) may have no email on file)")

    if not _smtp_configured():
        print(
            f"\n{'='*70}\n"
            f"EMAIL (SMTP not configured -- printed instead of sent)\n"
            f"To: {', '.join(to)}\n"
            f"Subject: {subject}\n"
            f"{'-'*70}\n{body}\n{'='*70}\n"
        )
        return EmailResult(sent=False, mode="console-fallback", to=to, subject=subject)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ["SMTP_FROM_ADDRESS"]
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() != "false"

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
        return EmailResult(sent=True, mode="smtp", to=to, subject=subject)
    except Exception as e:
        # A failed notification should never break the workflow action that
        # triggered it (e.g. a checker approving a station shouldn't fail just
        # because the mail server is down) -- callers should log this, not raise.
        return EmailResult(sent=False, mode="smtp", to=to, subject=subject, error=str(e))


# ---------------------------------------------------------------------------
# Workflow-specific message builders -- kept here (not inline in the router) so
# the wording is consistent and independently testable.
# ---------------------------------------------------------------------------
def notify_checker_assigned(checker_email: str, station_name: str, designer_name: str) -> EmailResult:
    return send_email(
        [checker_email],
        f"[KAVACH RFID Platform] {station_name} assigned to you for checking",
        f"{designer_name} has submitted the RFID Tag/TIN layout for '{station_name}' "
        f"and assigned it to you for checking.\n\n"
        f"Please log in to the platform to review it.",
    )


def notify_designer_of_check_result(designer_email: str, station_name: str, checker_name: str,
                                     approved: bool, comment: str = "") -> EmailResult:
    if approved:
        subject = f"[KAVACH RFID Platform] {station_name}: checked, forwarded to Approver"
        body = (f"{checker_name} has checked and approved the layout for '{station_name}'. "
                f"It has been forwarded to an Approver for final approval.")
    else:
        subject = f"[KAVACH RFID Platform] {station_name}: changes requested by Checker"
        body = (f"{checker_name} has requested changes to the layout for '{station_name}'.\n\n"
                f"Comment: {comment}\n\nThe layout is back in Draft for you to revise and resubmit.")
    return send_email([designer_email], subject, body)


def notify_of_approval_result(recipient_emails: list[str], station_name: str, approver_name: str,
                               approved: bool, comment: str = "") -> EmailResult:
    if approved:
        subject = f"[KAVACH RFID Platform] {station_name}: APPROVED"
        body = f"{approver_name} has approved the RFID Tag/TIN layout for '{station_name}'."
    else:
        subject = f"[KAVACH RFID Platform] {station_name}: changes requested by Approver"
        body = (f"{approver_name} has requested changes to the layout for '{station_name}'.\n\n"
                f"Comment: {comment}\n\nThe layout is back in Draft for the Designer to revise.")
    return send_email(recipient_emails, subject, body)
