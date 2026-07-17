import re
from datetime import UTC, datetime, timedelta

EMAIL_PATTERN = re.compile(r"(?P<local>[A-Z0-9._%+-]+)@(?P<domain>[A-Z0-9.-]+)", re.IGNORECASE)
BACKOFF_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(days=1),
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def from_utc_text(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stored datetime is not timezone-aware")
    return parsed.astimezone(UTC)


def retry_at(now: datetime, attempts: int) -> datetime:
    index = min(max(attempts - 1, 0), len(BACKOFF_DELAYS) - 1)
    return now + BACKOFF_DELAYS[index]


def mask_email(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        local = match.group("local")
        visible = local[:1] if local else "*"
        return f"{visible}***@{match.group('domain')}"

    return EMAIL_PATTERN.sub(replace, value)
