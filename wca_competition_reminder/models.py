from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


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
