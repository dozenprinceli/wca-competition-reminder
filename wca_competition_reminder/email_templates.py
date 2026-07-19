from __future__ import annotations

import string
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from wca_competition_reminder.models import (
    DEFAULT_NOTIFICATION_LANGUAGE,
    SUPPORTED_NOTIFICATION_LANGUAGES,
    normalize_notification_language,
)

DEFAULT_EMAIL_TEMPLATES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "email_templates.toml"
)


class EmailTemplateError(ValueError):
    """Raised when the local email template configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text_body: str
    html_body: str


@dataclass(frozen=True, slots=True)
class EmailTemplate:
    subject: str
    text_body: str
    html_body: str

    @staticmethod
    def _format(template: str, values: Mapping[str, object], field_name: str) -> str:
        try:
            return template.format_map(values)
        except (KeyError, IndexError, ValueError) as exc:
            raise EmailTemplateError(f"invalid placeholder in {field_name}") from exc

    def render(
        self,
        *,
        subject_values: Mapping[str, object],
        text_values: Mapping[str, object],
        html_values: Mapping[str, object],
    ) -> RenderedEmail:
        return RenderedEmail(
            subject=self._format(self.subject, subject_values, "subject"),
            text_body=self._format(self.text_body, text_values, "text_body"),
            html_body=self._format(self.html_body, html_values, "html_body"),
        )


class EmailTemplateCatalog:
    """Validated notification and verification templates loaded from local TOML."""

    def __init__(
        self,
        notifications: Mapping[str, EmailTemplate],
        verifications: Mapping[str, EmailTemplate],
        *,
        source: Path,
    ) -> None:
        self._notifications = dict(notifications)
        self._verifications = dict(verifications)
        self.source = source

    @classmethod
    def load(cls, path: Path) -> EmailTemplateCatalog:
        try:
            with path.open("rb") as template_file:
                document = tomllib.load(template_file)
        except (OSError, tomllib.TOMLDecodeError, UnicodeError) as exc:
            raise EmailTemplateError(f"cannot read email templates {path}: {exc}") from exc

        notifications = cls._load_group(document, "notification", path)
        verifications = cls._load_group(document, "verification", path)
        return cls(notifications, verifications, source=path)

    @classmethod
    def _load_group(
        cls,
        document: dict[str, object],
        group_name: str,
        path: Path,
    ) -> dict[str, EmailTemplate]:
        group = document.get(group_name)
        if not isinstance(group, dict):
            raise EmailTemplateError(f"{path} is missing [{group_name}] templates")
        templates: dict[str, EmailTemplate] = {}
        for language in sorted(SUPPORTED_NOTIFICATION_LANGUAGES):
            language_document = group.get(language)
            if not isinstance(language_document, dict):
                raise EmailTemplateError(
                    f"{path} is missing [{group_name}.{language}] template"
                )
            values: list[str] = []
            for field_name in ("subject", "text_body", "html_body"):
                value = language_document.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise EmailTemplateError(
                        f"{path} [{group_name}.{language}].{field_name} must be a non-empty string"
                    )
                cls._validate_placeholders(value, f"{group_name}.{language}.{field_name}", path)
                values.append(value.strip())
            templates[language] = EmailTemplate(*values)
        return templates

    @staticmethod
    def _validate_placeholders(template: str, field_name: str, path: Path) -> None:
        try:
            parsed = string.Formatter().parse(template)
            for _literal, field, _format_spec, _conversion in parsed:
                if field is not None and not field.isidentifier():
                    raise ValueError(f"unsupported placeholder {field!r}")
        except ValueError as exc:
            raise EmailTemplateError(f"invalid placeholder in {path} [{field_name}]") from exc

    def _template(self, language: object, *, verification: bool = False) -> EmailTemplate:
        try:
            normalized = normalize_notification_language(language)
        except ValueError as exc:
            raise EmailTemplateError(str(exc)) from exc
        templates = self._verifications if verification else self._notifications
        return templates.get(normalized) or templates[DEFAULT_NOTIFICATION_LANGUAGE]

    def render_notification(
        self,
        language: object,
        *,
        subject_values: Mapping[str, object],
        text_values: Mapping[str, object],
        html_values: Mapping[str, object],
    ) -> RenderedEmail:
        return self._template(language).render(
            subject_values=subject_values,
            text_values=text_values,
            html_values=html_values,
        )

    def render_verification(
        self,
        language: object,
        *,
        subject_values: Mapping[str, object],
        text_values: Mapping[str, object],
        html_values: Mapping[str, object],
    ) -> RenderedEmail:
        return self._template(language, verification=True).render(
            subject_values=subject_values,
            text_values=text_values,
            html_values=html_values,
        )


def load_email_templates(path: Path) -> EmailTemplateCatalog:
    return EmailTemplateCatalog.load(path)
