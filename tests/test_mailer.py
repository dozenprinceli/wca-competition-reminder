from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import ClassVar

import pytest

from tests.conftest import NOW, make_config
from wca_competition_reminder.mailer import DeliverySendError, SmtpMailer
from wca_competition_reminder.models import Delivery


class FakeSmtp:
    instances: ClassVar[list[FakeSmtp]] = []
    reject_authentication: ClassVar[bool] = False

    def __init__(self, host: str, port: int, *, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlo_calls = 0
        self.starttls_called = False
        self.login_credentials: tuple[str, str] | None = None
        self.sent: list[tuple[EmailMessage, str, list[str]]] = []
        self.closed = False
        self.quit_called = False
        self.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()
        cls.reject_authentication = False

    def ehlo(self) -> None:
        self.ehlo_calls += 1

    def starttls(self, *, context: ssl.SSLContext) -> None:
        assert isinstance(context, ssl.SSLContext)
        self.starttls_called = True

    def login(self, username: str, password: str) -> None:
        if self.reject_authentication:
            raise smtplib.SMTPAuthenticationError(535, b"authentication rejected")
        self.login_credentials = (username, password)

    def send_message(
        self,
        message: EmailMessage,
        from_addr: str,
        to_addrs: list[str],
    ) -> dict[str, object]:
        self.sent.append((message, from_addr, to_addrs))
        return {}

    def quit(self) -> None:
        self.quit_called = True

    def close(self) -> None:
        self.closed = True


def make_delivery() -> Delivery:
    return Delivery(
        delivery_id=1,
        claim_token="claim",
        competition_id="Mailer2026",
        recipient_email="one@example.com",
        recipient_name="One",
        message_id="<stable@example.com>",
        subject="SMTP test",
        text_body="Plain body",
        html_body="<p>HTML body</p>",
        created_at=NOW,
        attempts=1,
    )


def test_starttls_sends_one_recipient_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    FakeSmtp.reset()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    with SmtpMailer(config.smtp, "secret") as mailer:
        mailer.send(make_delivery())

    connection = FakeSmtp.instances[0]
    assert connection.starttls_called
    assert connection.ehlo_calls == 2
    assert connection.login_credentials == ("sender@example.com", "secret")
    assert connection.quit_called
    message, from_address, recipients = connection.sent[0]
    assert from_address == "sender@example.com"
    assert recipients == ["one@example.com"]
    assert message["Message-ID"] == "<stable@example.com>"
    assert message["To"] == "One <one@example.com>"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Plain body"


def test_authentication_failure_is_permanent_and_stops_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    FakeSmtp.reset()
    FakeSmtp.reject_authentication = True
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    with (
        SmtpMailer(config.smtp, "wrong") as mailer,
        pytest.raises(DeliverySendError, match="authentication failed") as captured,
    ):
        mailer.send(make_delivery())

    assert captured.value.permanent
    assert captured.value.stop_run
    assert FakeSmtp.instances[0].closed


def test_verification_code_uses_existing_smtp_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    FakeSmtp.reset()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    with SmtpMailer(config.smtp, "secret") as mailer:
        mailer.send_verification_code("new@example.com", "123456", NOW)

    message, from_address, recipients = FakeSmtp.instances[0].sent[0]
    assert from_address == "sender@example.com"
    assert recipients == ["new@example.com"]
    assert message["Subject"] == "[WCA 比赛提醒] 注册验证码"
    assert "123456" in message.get_body(preferencelist=("plain",)).get_content()
    assert "5 分钟" in message.get_body(preferencelist=("plain",)).get_content()


def test_verification_code_uses_selected_notification_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(tmp_path)
    FakeSmtp.reset()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    with SmtpMailer(config.smtp, "secret") as mailer:
        mailer.send_verification_code("new@example.com", "123456", NOW, "en")

    message = FakeSmtp.instances[0].sent[0][0]
    assert message["Subject"] == "[WCA competition alert] Verification code"
    assert "Verification code: 123456" in message.get_body(preferencelist=("plain",)).get_content()
