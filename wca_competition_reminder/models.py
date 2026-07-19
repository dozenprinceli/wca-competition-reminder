from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from wca_competition_reminder.distance import coordinates_are_valid, haversine_km

MAX_FOLLOW_CONDITIONS = 10


class NotificationLanguage(StrEnum):
    """Languages available for competition notification emails."""

    ZH = "zh"
    EN = "en"
    JA = "ja"


SUPPORTED_NOTIFICATION_LANGUAGES = frozenset(language.value for language in NotificationLanguage)
DEFAULT_NOTIFICATION_LANGUAGE = NotificationLanguage.ZH.value


def normalize_notification_language(
    value: object,
    *,
    default: str = DEFAULT_NOTIFICATION_LANGUAGE,
) -> str:
    """Return a supported language code from a UI/API locale value."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if not isinstance(value, str):
        raise ValueError("notification language must be a string")
    normalized = value.strip().lower().replace("_", "-")
    language = normalized.split("-", 1)[0]
    if language not in SUPPORTED_NOTIFICATION_LANGUAGES:
        raise ValueError("notification language must be one of: zh, en, ja")
    return language


class CompetitionStatus(StrEnum):
    BASELINE = "baseline"
    # Retained so state databases created by the Megaminx-only release remain readable.
    IGNORED_NO_MINX = "ignored_no_minx"
    IGNORED_NO_OFFICIAL_EVENTS = "ignored_no_official_events"
    IGNORED_CANCELLED = "ignored_cancelled"
    PENDING_DETAILS = "pending_details"
    PENDING_COORDINATES = "pending_coordinates"
    QUEUED = "queued"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class WcaCountry:
    name: str
    iso2: str
    continent_name: str


@dataclass(frozen=True, slots=True)
class FollowCondition:
    latitude: float | None = None
    longitude: float | None = None
    max_distance_km: float | None = None
    event_ids: frozenset[str] | None = None
    country_names: frozenset[str] | None = None
    continent_names: frozenset[str] | None = None

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

    def matches(
        self,
        event_ids: Iterable[str],
        *,
        country_name: str,
        continent_name: str,
        competition_latitude: float | None,
        competition_longitude: float | None,
    ) -> bool:
        return (
            self.follows_any(event_ids)
            and self.follows_region(country_name, continent_name)
            and self.follows_distance(competition_latitude, competition_longitude)
        )


@dataclass(frozen=True, slots=True)
class SubscriberRecord:
    email: str
    latitude: float | None
    longitude: float | None
    max_distance_km: float | None
    name: str | None
    event_ids: frozenset[str] | None
    country_names: frozenset[str] | None
    continent_names: frozenset[str] | None
    active: bool
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None
    additional_conditions: tuple[FollowCondition, ...] = ()
    notification_language: str = DEFAULT_NOTIFICATION_LANGUAGE

    @property
    def conditions(self) -> tuple[FollowCondition, ...]:
        return (
            FollowCondition(
                latitude=self.latitude,
                longitude=self.longitude,
                max_distance_km=self.max_distance_km,
                event_ids=self.event_ids,
                country_names=self.country_names,
                continent_names=self.continent_names,
            ),
            *self.additional_conditions,
        )


@dataclass(frozen=True, slots=True)
class CompetitionSummary:
    competition_id: str
    name: str
    start_date: date
    end_date: date
    announced_at: datetime
    event_ids: tuple[str, ...]
    city: str
    venue: str
    country_iso2: str
    latitude: float | None
    longitude: float | None
    raw_json: str


@dataclass(frozen=True, slots=True)
class CompetitionDetails:
    competition_id: str
    name: str
    start_date: date
    end_date: date
    announced_at: datetime
    event_ids: tuple[str, ...]
    city: str
    venue: str
    venue_address: str
    venue_details: str
    country_iso2: str
    latitude: float | None
    longitude: float | None
    url: str
    cancelled_at: datetime | None
    raw_json: str


@dataclass(frozen=True, slots=True)
class PendingCompetition:
    summary: CompetitionSummary
    status: CompetitionStatus
    enrichment_attempts: int
    coordinate_deadline_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeliveryDraft:
    recipient_email: str
    recipient_name: str | None
    recipient_latitude: float | None
    recipient_longitude: float | None
    message_id: str
    subject: str
    text_body: str
    html_body: str


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: int
    claim_token: str
    competition_id: str
    recipient_email: str
    recipient_name: str | None
    message_id: str
    subject: str
    text_body: str
    html_body: str
    created_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class DiscoveryStats:
    discovered: int = 0
    queued_for_details: int = 0
    ignored: int = 0
    silently_recorded: int = 0
