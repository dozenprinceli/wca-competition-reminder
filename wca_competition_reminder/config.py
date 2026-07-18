import math
import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from email.headerregistry import Address
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wca_competition_reminder.distance import coordinates_are_valid, haversine_km
from wca_competition_reminder.events import OFFICIAL_EVENT_IDS


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecipientConfig:
    email: str
    latitude: float | None
    longitude: float | None
    name: str | None = None
    event_ids: frozenset[str] | None = None
    country_names: frozenset[str] | None = None
    continent_names: frozenset[str] | None = None
    max_distance_km: float | None = None

    def follows_any(self, event_ids: Iterable[str]) -> bool:
        return self.event_ids is None or not self.event_ids.isdisjoint(event_ids)

    @property
    def has_region_filter(self) -> bool:
        return self.country_names is not None or self.continent_names is not None

    def follows_region(self, country_name: str, continent_name: str) -> bool:
        return not self.has_region_filter or (
            (self.country_names is not None and country_name in self.country_names)
            or (self.continent_names is not None and continent_name in self.continent_names)
        )

    def follows_distance(
        self,
        competition_latitude: float | None,
        competition_longitude: float | None,
    ) -> bool:
        if self.max_distance_km is None:
            return True
        if not coordinates_are_valid(self.latitude, self.longitude) or not coordinates_are_valid(
            competition_latitude, competition_longitude
        ):
            return False
        assert self.latitude is not None and self.longitude is not None
        assert competition_latitude is not None and competition_longitude is not None
        return (
            haversine_km(
                self.latitude,
                self.longitude,
                competition_latitude,
                competition_longitude,
            )
            <= self.max_distance_km
        )


@dataclass(frozen=True, slots=True)
class WcaConfig:
    base_url: str
    user_agent: str
    page_size: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    request_attempts: int
    overlap_days: int


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    security: str
    username: str | None
    from_address: str
    from_name: str
    timeout_seconds: float
    password_env: str


@dataclass(frozen=True, slots=True)
class AdminConfig:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    timezone: ZoneInfo
    timezone_name: str
    state_path: Path
    lock_path: Path
    log_dir: Path
    coordinate_retry_hours: int
    full_reconcile_hours: int
    max_emails_per_run: int
    wca: WcaConfig
    smtp: SmtpConfig
    recipients: tuple[RecipientConfig, ...]
    admins: tuple[AdminConfig, ...] = ()
    google_maps_api_key: str | None = None


def _table(document: dict[str, object], name: str) -> dict[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"missing or invalid [{name}] table")
    return value


def _required_string(document: dict[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _string(document: dict[str, object], name: str, default: str) -> str:
    value = document.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(document: dict[str, object], name: str) -> str | None:
    value = document.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string")
    return value.strip() or None


def _integer(
    document: dict[str, object],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = document.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _number(
    document: dict[str, object],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    value = document.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ConfigurationError(f"{name} must be from {minimum} to {maximum}")
    return number


def _email(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field_name} must be a non-empty email address")
    normalized = value.strip().lower()
    try:
        address = Address(addr_spec=normalized)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} is not a valid email address") from exc
    if not address.domain or not address.username or address.addr_spec != normalized:
        raise ConfigurationError(f"{field_name} is not a valid email address")
    return normalized


def _path(value: object, field_name: str, base_directory: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field_name} must be a non-empty path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_directory / path).resolve()


def _recipient_event_ids(value: object, field_name: str) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{field_name} must be a comma-separated string")
    if not value.strip():
        return None

    event_ids = [event_id.strip() for event_id in value.split(",")]
    if any(not event_id for event_id in event_ids):
        raise ConfigurationError(f"{field_name} contains an empty event ID")

    unknown = sorted(set(event_ids) - OFFICIAL_EVENT_IDS)
    if unknown:
        valid = ",".join(sorted(OFFICIAL_EVENT_IDS))
        raise ConfigurationError(
            f"{field_name} contains unknown WCA event IDs: {','.join(unknown)}; valid IDs: {valid}"
        )
    return frozenset(event_ids)


def _recipient_region_names(value: object, field_name: str) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigurationError(f"{field_name} must be an array of strings")

    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(f"{field_name} must contain only non-empty strings")
        names.append(item.strip())
    return frozenset(names) or None


def _recipient_coordinates(
    document: dict[str, object],
    field_name: str,
) -> tuple[float | None, float | None]:
    has_latitude = "latitude" in document
    has_longitude = "longitude" in document
    if not has_latitude and not has_longitude:
        return None, None
    if has_latitude != has_longitude:
        raise ConfigurationError(
            f"{field_name}.latitude and {field_name}.longitude must be provided together"
        )
    return (
        _number(document, "latitude", 0, minimum=-90, maximum=90),
        _number(document, "longitude", 0, minimum=-180, maximum=180),
    )


def _optional_positive_number(
    document: dict[str, object],
    name: str,
    field_name: str,
) -> float | None:
    value = document.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ConfigurationError(f"{field_name} must be greater than 0")
    return number


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as config_file:
            document = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"cannot read configuration {path}: {exc}") from exc

    base_directory = path.resolve().parent
    timezone_name = _string(document, "timezone", "UTC")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"unknown timezone: {timezone_name}") from exc

    state_path = _path(document.get("state_path", "state.sqlite3"), "state_path", base_directory)
    lock_path = _path(document.get("lock_path", "runner.lock"), "lock_path", base_directory)
    log_dir = _path(document.get("log_dir", "logs"), "log_dir", base_directory)
    coordinate_retry_hours = _integer(
        document, "coordinate_retry_hours", 24, minimum=1, maximum=168
    )
    full_reconcile_hours = _integer(document, "full_reconcile_hours", 24, minimum=1, maximum=168)
    max_emails_per_run = _integer(document, "max_emails_per_run", 100, minimum=1, maximum=1000)

    web_document = document.get("web", {})
    if not isinstance(web_document, dict):
        raise ConfigurationError("invalid [web] table")
    google_maps_api_key = _optional_string(web_document, "google_maps_api_key")

    wca_document = _table(document, "wca")
    base_url = _string(wca_document, "base_url", "https://www.worldcubeassociation.org").rstrip("/")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
        raise ConfigurationError("wca.base_url must be an HTTPS URL")
    wca = WcaConfig(
        base_url=base_url,
        user_agent=_string(
            wca_document,
            "user_agent",
            "wca-competition-reminder/0.1",
        ),
        page_size=_integer(wca_document, "page_size", 100, minimum=25, maximum=500),
        connect_timeout_seconds=_number(
            wca_document, "connect_timeout_seconds", 5, minimum=1, maximum=60
        ),
        read_timeout_seconds=_number(
            wca_document, "read_timeout_seconds", 20, minimum=1, maximum=120
        ),
        request_attempts=_integer(wca_document, "request_attempts", 3, minimum=1, maximum=5),
        overlap_days=_integer(wca_document, "overlap_days", 2, minimum=1, maximum=14),
    )

    smtp_document = _table(document, "smtp")
    security = _string(smtp_document, "security", "starttls").lower()
    if security not in {"starttls", "tls"}:
        raise ConfigurationError("smtp.security must be 'starttls' or 'tls'")
    username_value = smtp_document.get("username")
    if username_value is not None and not isinstance(username_value, str):
        raise ConfigurationError("smtp.username must be a string")
    username = username_value.strip() if isinstance(username_value, str) else None
    username = username or None
    smtp = SmtpConfig(
        host=_required_string(smtp_document, "host"),
        port=_integer(smtp_document, "port", 587, minimum=1, maximum=65535),
        security=security,
        username=username,
        from_address=_email(smtp_document.get("from_address"), "smtp.from_address"),
        from_name=_string(smtp_document, "from_name", "WCA Competition Reminder"),
        timeout_seconds=_number(smtp_document, "timeout_seconds", 30, minimum=1, maximum=120),
        password_env=_string(smtp_document, "password_env", "WCA_REMINDER_SMTP_PASSWORD"),
    )

    admins_document = document.get("admins", [])
    if not isinstance(admins_document, list):
        raise ConfigurationError("admins must be an array of tables")
    admins: list[AdminConfig] = []
    seen_admin_usernames: set[str] = set()
    for index, admin_document in enumerate(admins_document, start=1):
        if not isinstance(admin_document, dict):
            raise ConfigurationError(f"admins entry {index} must be a table")
        username = _required_string(admin_document, "username")
        password = _required_string(admin_document, "password")
        if username in seen_admin_usernames:
            raise ConfigurationError(f"duplicate admin username: {username}")
        seen_admin_usernames.add(username)
        admins.append(AdminConfig(username=username, password=password))

    recipients_document = document.get("recipients")
    if recipients_document is None:
        recipients_document = []
    if not isinstance(recipients_document, list):
        raise ConfigurationError("recipients must be an array of tables")
    recipients: list[RecipientConfig] = []
    seen_emails: set[str] = set()
    for index, recipient_document in enumerate(recipients_document, start=1):
        if not isinstance(recipient_document, dict):
            raise ConfigurationError(f"recipients entry {index} must be a table")
        email = _email(recipient_document.get("email"), f"recipients[{index}].email")
        if email in seen_emails:
            raise ConfigurationError(f"duplicate recipient email: {email}")
        seen_emails.add(email)
        name_value = recipient_document.get("name")
        if name_value is not None and not isinstance(name_value, str):
            raise ConfigurationError(f"recipients[{index}].name must be a string")
        name = name_value.strip() if isinstance(name_value, str) else None
        latitude, longitude = _recipient_coordinates(
            recipient_document,
            f"recipients[{index}]",
        )
        max_distance_km = _optional_positive_number(
            recipient_document,
            "max_distance_km",
            f"recipients[{index}].max_distance_km",
        )
        if max_distance_km is not None and latitude is None:
            raise ConfigurationError(
                f"recipients[{index}].latitude and recipients[{index}].longitude "
                "are required when max_distance_km is set"
            )
        recipients.append(
            RecipientConfig(
                email=email,
                latitude=latitude,
                longitude=longitude,
                name=name or None,
                event_ids=_recipient_event_ids(
                    recipient_document.get("events"),
                    f"recipients[{index}].events",
                ),
                country_names=_recipient_region_names(
                    recipient_document.get("countries"),
                    f"recipients[{index}].countries",
                ),
                continent_names=_recipient_region_names(
                    recipient_document.get("continents"),
                    f"recipients[{index}].continents",
                ),
                max_distance_km=max_distance_km,
            )
        )

    return AppConfig(
        timezone=timezone,
        timezone_name=timezone_name,
        state_path=state_path,
        lock_path=lock_path,
        log_dir=log_dir,
        coordinate_retry_hours=coordinate_retry_hours,
        full_reconcile_hours=full_reconcile_hours,
        max_emails_per_run=max_emails_per_run,
        wca=wca,
        smtp=smtp,
        recipients=tuple(recipients),
        admins=tuple(admins),
        google_maps_api_key=google_maps_api_key,
    )


def load_smtp_password(
    smtp: SmtpConfig,
    *,
    password_file: Path | None = None,
) -> str | None:
    if smtp.username is None:
        return None

    if password_file is not None:
        try:
            password = password_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(f"cannot read SMTP password file: {exc}") from exc
        if password:
            return password
        raise ConfigurationError("SMTP password file is empty")

    password = os.environ.get(smtp.password_env, "").strip()
    if password:
        return password

    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_directory:
        credential_path = Path(credentials_directory) / "smtp_password"
        if credential_path.is_file():
            password = credential_path.read_text(encoding="utf-8").strip()
            if password:
                return password

    raise ConfigurationError(
        f"SMTP password is required in {smtp.password_env}, an explicit password file, "
        "or the smtp_password systemd credential"
    )
