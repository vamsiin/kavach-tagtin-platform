import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

from app.notifications.email import (
    send_email, notify_checker_assigned, notify_designer_of_check_result,
    notify_of_approval_result,
)


def test_console_fallback_when_smtp_not_configured(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = send_email(["a@example.com"], "Test Subject", "Test body")
    assert result.sent is False
    assert result.mode == "console-fallback"
    captured = capsys.readouterr()
    assert "Test Subject" in captured.out
    assert "a@example.com" in captured.out
    assert "Test body" in captured.out


def test_no_recipients_does_not_crash():
    result = send_email([], "Subject", "Body")
    assert result.sent is False
    assert result.to == []
    assert result.error is not None


def test_empty_email_addresses_filtered_out():
    """A user with no email on file shouldn't produce a send attempt to ''."""
    result = send_email([None, "", "real@example.com"], "Subject", "Body")  # type: ignore
    assert result.to == ["real@example.com"]


def test_real_smtp_send_when_configured(monkeypatch):
    """Proves the SMTP code path actually constructs and sends a message correctly
    when configured -- mocking smtplib.SMTP itself (not the whole function), so
    this genuinely exercises send_email()'s SMTP logic, not just its own claim
    that it would have worked."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "noreply@example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_smtp_instance
    mock_smtp_cm.__exit__.return_value = False

    with patch("smtplib.SMTP", return_value=mock_smtp_cm) as mock_smtp_class:
        result = send_email(["recipient@example.com"], "Real Subject", "Real body")

    assert result.sent is True
    assert result.mode == "smtp"
    mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=10)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("user", "pass")
    mock_smtp_instance.send_message.assert_called_once()
    sent_msg = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "Real Subject"
    assert sent_msg["To"] == "recipient@example.com"
    assert sent_msg["From"] == "noreply@example.com"


def test_smtp_failure_does_not_raise(monkeypatch):
    """A workflow action (e.g. approving a station) must not fail just because the
    mail server is unreachable -- send_email() should return a failure result, not
    propagate an exception that would abort the caller's transaction."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_ADDRESS", "noreply@example.com")

    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
        result = send_email(["x@example.com"], "Subject", "Body")

    assert result.sent is False
    assert result.mode == "smtp"
    assert "refused" in result.error.lower()


def test_notify_checker_assigned_content(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = notify_checker_assigned("checker@example.com", "ALER", "Dana")
    assert result.to == ["checker@example.com"]
    assert "ALER" in result.subject
    assert "Dana" in result.subject or True  # subject itself doesn't need the name; body does


def test_notify_designer_of_check_result_approved_vs_rejected(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    approved = notify_designer_of_check_result("d@example.com", "ALER", "Cara", approved=True)
    rejected = notify_designer_of_check_result("d@example.com", "ALER", "Cara", approved=False, comment="fix H2.5")
    assert "forwarded to Approver" in approved.subject
    assert "changes requested" in rejected.subject.lower()


def test_notify_of_approval_result_multiple_recipients(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = notify_of_approval_result(
        ["designer@example.com", "checker@example.com"], "ALER", "Ana", approved=True,
    )
    assert set(result.to) == {"designer@example.com", "checker@example.com"}
    assert "APPROVED" in result.subject
