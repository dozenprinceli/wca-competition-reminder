from __future__ import annotations

import smtplib
import ssl
from contextlib import suppress
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from wca_competition_reminder.config import SmtpConfig
from wca_competition_reminder.email_templates import (
    DEFAULT_EMAIL_TEMPLATES_PATH,
    EmailTemplateCatalog,
    load_email_templates,
)
from wca_competition_reminder.models import DEFAULT_NOTIFICATION_LANGUAGE, Delivery
from wca_competition_reminder.utils import mask_email


class DeliverySendError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool, stop_run: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.stop_run = stop_run


class SmtpMailer:
    def __init__(
        self,
        config: SmtpConfig,
        password: str | None,
        *,
        template_catalog: EmailTemplateCatalog | None = None,
        templates_path: Path | None = None,
    ) -> None:
        self._config = config
        self._password = password
        self._connection: smtplib.SMTP | smtplib.SMTP_SSL | None = None
        self._template_catalog = template_catalog
        self._templates_path = templates_path or DEFAULT_EMAIL_TEMPLATES_PATH

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.quit()
        except (OSError, smtplib.SMTPException):
            with suppress(OSError):
                self._connection.close()
        finally:
            self._connection = None

    def __enter__(self) -> SmtpMailer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def send(self, delivery: Delivery) -> None:
        message = EmailMessage()
        message["Subject"] = delivery.subject
        message["From"] = Address(
            display_name=self._config.from_name,
            addr_spec=self._config.from_address,
        )
        message["To"] = Address(
            display_name=delivery.recipient_name or "",
            addr_spec=delivery.recipient_email,
        )
        message["Message-ID"] = delivery.message_id
        message["Date"] = format_datetime(delivery.created_at)
        message.set_content(delivery.text_body)
        message.add_alternative(delivery.html_body, subtype="html")
        self._send_message(message, delivery.recipient_email)

    def send_verification_code(
        self,
        recipient_email: str,
        code: str,
        created_at: datetime,
        notification_language: str = DEFAULT_NOTIFICATION_LANGUAGE,
    ) -> None:
        domain = self._config.from_address.rpartition("@")[2] or "wca-reminder.local"
        templates = self._template_catalog or load_email_templates(self._templates_path)
        rendered = templates.render_verification(
            notification_language,
            subject_values={"code": code, "validity_minutes": 5},
            text_values={"code": code, "validity_minutes": 5},
            html_values={"code": code, "validity_minutes": 5},
        )
        message = EmailMessage()
        message["Subject"] = rendered.subject
        message["From"] = Address(
            display_name=self._config.from_name,
            addr_spec=self._config.from_address,
        )
        message["To"] = Address(addr_spec=recipient_email)
        message["Message-ID"] = make_msgid(domain=domain)
        message["Date"] = format_datetime(created_at)
        message.set_content(rendered.text_body)
        message.add_alternative(rendered.html_body, subtype="html")
        self._send_message(message, recipient_email)

    def _send_message(self, message: EmailMessage, recipient_email: str) -> None:
        try:
            connection = self._connection or self._connect()
            refused = connection.send_message(
                message,
                from_addr=self._config.from_address,
                to_addrs=[recipient_email],
            )
            if refused:
                raise DeliverySendError("SMTP server rejected the recipient", permanent=True)
        except DeliverySendError:
            self._discard_connection()
            raise
        except smtplib.SMTPAuthenticationError as exc:
            self._discard_connection()
            raise DeliverySendError(
                f"SMTP authentication failed with code {exc.smtp_code}",
                permanent=True,
                stop_run=True,
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            self._discard_connection()
            raise DeliverySendError("SMTP server rejected the recipient", permanent=True) from exc
        except smtplib.SMTPResponseException as exc:
            self._discard_connection()
            raise DeliverySendError(
                f"SMTP returned code {exc.smtp_code}",
                permanent=exc.smtp_code >= 500,
            ) from exc
        except smtplib.SMTPNotSupportedError as exc:
            self._discard_connection()
            raise DeliverySendError(
                f"SMTP server lacks a required feature: {mask_email(str(exc))}",
                permanent=True,
                stop_run=True,
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            self._discard_connection()
            raise DeliverySendError(
                f"SMTP transport failed: {mask_email(str(exc))}",
                permanent=False,
            ) from exc

    def _connect(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        context = ssl.create_default_context()
        connection: smtplib.SMTP | smtplib.SMTP_SSL | None = None
        try:
            if self._config.security == "tls":
                connection = smtplib.SMTP_SSL(
                    self._config.host,
                    self._config.port,
                    timeout=self._config.timeout_seconds,
                    context=context,
                )
            else:
                connection = smtplib.SMTP(
                    self._config.host,
                    self._config.port,
                    timeout=self._config.timeout_seconds,
                )
                connection.ehlo()
                connection.starttls(context=context)
                connection.ehlo()

            if self._config.username:
                if self._password is None:
                    raise DeliverySendError(
                        "SMTP password is missing",
                        permanent=True,
                        stop_run=True,
                    )
                connection.login(self._config.username, self._password)
        except BaseException:
            if connection is not None:
                with suppress(OSError):
                    connection.close()
            raise
        self._connection = connection
        return connection

    def _discard_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            finally:
                self._connection = None
