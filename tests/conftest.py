from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wca_competition_reminder.config import (
    AppConfig,
    RecipientConfig,
    SmtpConfig,
    WcaConfig,
)
from wca_competition_reminder.models import (
    CompetitionDetails,
    CompetitionSummary,
    Delivery,
    WcaCountry,
)
from wca_competition_reminder.wca import (
    parse_competition_details,
    parse_competition_summary,
)

NOW = datetime(2026, 7, 16, 2, 0, tzinfo=UTC)


def summary_document(
    competition_id: str,
    *,
    announced_at: datetime = NOW,
    event_ids: list[str] | None = None,
    latitude: float | None = 31.2304,
    longitude: float | None = 121.4737,
    country_iso2: str = "CN",
) -> dict[str, object]:
    return {
        "id": competition_id,
        "name": f"Competition {competition_id}",
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
        "announced_at": announced_at.isoformat().replace("+00:00", "Z"),
        "event_ids": event_ids if event_ids is not None else ["333", "minx"],
        "city": "Shanghai",
        "venue": "Example venue",
        "country_iso2": country_iso2,
        "latitude_degrees": latitude,
        "longitude_degrees": longitude,
    }


def details_document(
    competition_id: str,
    *,
    announced_at: datetime = NOW,
    event_ids: list[str] | None = None,
    latitude: float | None = 31.2304,
    longitude: float | None = 121.4737,
    country_iso2: str = "CN",
    cancelled_at: str | None = None,
) -> dict[str, object]:
    document = summary_document(
        competition_id,
        announced_at=announced_at,
        event_ids=event_ids,
        latitude=latitude,
        longitude=longitude,
        country_iso2=country_iso2,
    )
    document.update(
        {
            "venue_address": "100 Example Road, Shanghai",
            "venue_details": "Second floor",
            "url": f"https://www.worldcubeassociation.org/competitions/{competition_id}",
            "cancelled_at": cancelled_at,
        }
    )
    return document


def make_summary(competition_id: str, **kwargs: object) -> CompetitionSummary:
    return parse_competition_summary(summary_document(competition_id, **kwargs))


def make_details(competition_id: str, **kwargs: object) -> CompetitionDetails:
    return parse_competition_details(details_document(competition_id, **kwargs))


def make_config(
    tmp_path: Path,
    *,
    coordinate_retry_hours: int = 24,
    full_reconcile_hours: int = 168,
) -> AppConfig:
    return AppConfig(
        timezone=ZoneInfo("UTC"),
        timezone_name="UTC",
        state_path=tmp_path / "state.sqlite3",
        lock_path=tmp_path / "runner.lock",
        log_dir=tmp_path / "logs",
        coordinate_retry_hours=coordinate_retry_hours,
        full_reconcile_hours=full_reconcile_hours,
        max_emails_per_run=100,
        wca=WcaConfig(
            base_url="https://wca.test",
            user_agent="reminder-tests/1.0",
            page_size=100,
            connect_timeout_seconds=1,
            read_timeout_seconds=1,
            request_attempts=1,
            overlap_days=2,
        ),
        smtp=SmtpConfig(
            host="smtp.test",
            port=587,
            security="starttls",
            username="sender@example.com",
            from_address="sender@example.com",
            from_name="Reminder Tests",
            timeout_seconds=1,
            password_env="TEST_SMTP_PASSWORD",
        ),
        web_base_url="https://reminder.test/subscriptions",
        recipients=(
            RecipientConfig("one@example.com", 31.2304, 121.4737, "One"),
            RecipientConfig("two@example.com", 39.9042, 116.4074, "Two"),
        ),
    )


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class FakeWca:
    def __init__(
        self,
        *,
        all_future: list[CompetitionSummary] | None = None,
        recent_future: list[CompetitionSummary] | None = None,
        details: dict[str, CompetitionDetails | Exception] | None = None,
        countries: dict[str, WcaCountry] | None = None,
        all_error: Exception | None = None,
        recent_error: Exception | None = None,
        country_error: Exception | None = None,
    ) -> None:
        self.all_future = all_future or []
        self.recent_future = recent_future or []
        self.details = details or {}
        self.countries = (
            countries if countries is not None else {"CN": WcaCountry("China", "CN", "Asia")}
        )
        self.all_error = all_error
        self.recent_error = recent_error
        self.country_error = country_error
        self.detail_calls: list[str] = []
        self.country_calls: list[str] = []

    def fetch_all_future(self, current_date: date) -> list[CompetitionSummary]:
        del current_date
        if self.all_error:
            raise self.all_error
        return self.all_future

    def fetch_recent_future(
        self, current_date: date, announced_after: date
    ) -> list[CompetitionSummary]:
        del current_date, announced_after
        if self.recent_error:
            raise self.recent_error
        return self.recent_future

    def fetch_details(self, competition_id: str) -> CompetitionDetails:
        self.detail_calls.append(competition_id)
        result = self.details[competition_id]
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_country(self, country_iso2: str) -> WcaCountry:
        self.country_calls.append(country_iso2)
        if self.country_error:
            raise self.country_error
        return self.countries[country_iso2]


class FakeMailer:
    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.errors = errors or {}
        self.sent: list[Delivery] = []

    def send(self, delivery: Delivery) -> None:
        error = self.errors.pop(delivery.recipient_email, None)
        if error:
            raise error
        self.sent.append(delivery)
