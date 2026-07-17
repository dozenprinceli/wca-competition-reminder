from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.events import OFFICIAL_EVENT_IDS
from wca_competition_reminder.models import (
    CompetitionStatus,
    CompetitionSummary,
    Delivery,
    DeliveryDraft,
    DeliveryStatus,
    DiscoveryStats,
    PendingCompetition,
    SubscriberRecord,
)
from wca_competition_reminder.utils import from_utc_text, retry_at, to_utc_text
from wca_competition_reminder.wca import summary_from_json

SCHEMA_VERSION = 4
MIGRATABLE_SCHEMA_VERSION = 3

_STATE_TABLES = {"app_state", "subscribers", "competitions", "deliveries"}
_V3_REQUIRED_COLUMNS = {
    "app_state": {"key", "value"},
    "subscribers": {
        "email",
        "name",
        "latitude",
        "longitude",
        "event_ids_json",
        "country_names_json",
        "continent_names_json",
        "active",
        "created_at",
        "updated_at",
        "cancelled_at",
    },
    "competitions": {
        "id",
        "announced_at",
        "discovered_at",
        "processed_at",
        "status",
        "summary_json",
        "detail_json",
        "enrichment_attempts",
        "next_enrichment_at",
        "coordinate_deadline_at",
        "last_error",
    },
    "deliveries": {
        "id",
        "competition_id",
        "recipient_email",
        "recipient_name",
        "recipient_latitude",
        "recipient_longitude",
        "message_id",
        "subject",
        "text_body",
        "html_body",
        "status",
        "attempts",
        "next_attempt_at",
        "lease_until",
        "claim_token",
        "last_error",
        "created_at",
        "sent_at",
    },
}


class StateError(RuntimeError):
    pass


def _encode_filter(values: frozenset[str] | None) -> str | None:
    if values is None:
        return None
    return json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))


def _decode_filter(value: object, field_name: str) -> frozenset[str] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise StateError(f"stored subscriber {field_name} is invalid JSON") from exc
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise StateError(f"stored subscriber {field_name} must be a string array")
    return frozenset(decoded) or None


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, timeout=5, autocommit=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        try:
            self._create_schema()
        except BaseException:
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _existing_tables(self) -> set[str]:
        return {
            str(row["name"])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    def _table_columns(self, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in self._connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }

    def _migrate_schema(self) -> None:
        # The version is intentionally re-read after taking the write lock. The poller and
        # Web service can start together, and only one of them should execute the migration.
        with self._transaction():
            schema_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if schema_version > SCHEMA_VERSION:
                raise StateError(
                    f"state database schema version {schema_version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if schema_version == SCHEMA_VERSION:
                return

            existing_tables = self._existing_tables()
            if not existing_tables.intersection(_STATE_TABLES):
                return
            if schema_version != MIGRATABLE_SCHEMA_VERSION:
                raise StateError(
                    f"state database schema version {schema_version} is no longer supported; "
                    "recreate the state database"
                )

            missing_tables = _STATE_TABLES - existing_tables
            missing_columns = {
                table: required - self._table_columns(table)
                for table, required in _V3_REQUIRED_COLUMNS.items()
                if table in existing_tables and required - self._table_columns(table)
            }
            if missing_tables or missing_columns:
                raise StateError(
                    "state database schema version 3 does not match the expected layout; "
                    "cannot migrate it safely"
                )
            if "max_distance_km" in self._table_columns("subscribers"):
                raise StateError(
                    "state database schema version 3 already contains max_distance_km; "
                    "cannot migrate it safely"
                )

            self._connection.execute(
                """
                ALTER TABLE subscribers
                ADD COLUMN max_distance_km REAL
                    CHECK (max_distance_km IS NULL OR max_distance_km > 0)
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _create_schema(self) -> None:
        schema_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version > SCHEMA_VERSION:
            raise StateError(
                f"state database schema version {schema_version} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if schema_version < SCHEMA_VERSION:
            self._migrate_schema()

        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                email TEXT PRIMARY KEY,
                name TEXT,
                latitude REAL,
                longitude REAL,
                max_distance_km REAL
                    CHECK (max_distance_km IS NULL OR max_distance_km > 0),
                event_ids_json TEXT,
                country_names_json TEXT,
                continent_names_json TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                cancelled_at TEXT
            );

            CREATE INDEX IF NOT EXISTS subscribers_active
                ON subscribers(active, updated_at);

            CREATE TABLE IF NOT EXISTS competitions (
                id TEXT PRIMARY KEY,
                announced_at TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                processed_at TEXT,
                status TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                detail_json TEXT,
                enrichment_attempts INTEGER NOT NULL DEFAULT 0,
                next_enrichment_at TEXT,
                coordinate_deadline_at TEXT,
                last_error TEXT
            );

            CREATE INDEX IF NOT EXISTS competitions_enrichment_due
                ON competitions(status, next_enrichment_at);

            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition_id TEXT NOT NULL REFERENCES competitions(id),
                recipient_email TEXT NOT NULL,
                recipient_name TEXT,
                recipient_latitude REAL,
                recipient_longitude REAL,
                message_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                text_body TEXT NOT NULL,
                html_body TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                claim_token TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                UNIQUE(competition_id, recipient_email)
            );

            CREATE INDEX IF NOT EXISTS deliveries_due
                ON deliveries(status, next_attempt_at, lease_until);
            """
        )

        with self._transaction():
            self._connection.execute(
                """
                UPDATE deliveries
                SET status = ?, next_attempt_at = COALESCE(next_attempt_at, created_at),
                    lease_until = NULL, claim_token = NULL
                WHERE status = ? AND lease_until IS NULL
                """,
                (DeliveryStatus.PENDING, DeliveryStatus.SENDING),
            )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _set_state(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO app_state(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _get_state(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row is not None else None

    @staticmethod
    def _subscriber_from_row(row: sqlite3.Row) -> SubscriberRecord:
        created_at = from_utc_text(str(row["created_at"]))
        updated_at = from_utc_text(str(row["updated_at"]))
        if created_at is None or updated_at is None:
            raise StateError("stored subscriber timestamps are invalid")
        return SubscriberRecord(
            email=str(row["email"]),
            latitude=float(row["latitude"]) if row["latitude"] is not None else None,
            longitude=float(row["longitude"]) if row["longitude"] is not None else None,
            max_distance_km=(
                float(row["max_distance_km"]) if row["max_distance_km"] is not None else None
            ),
            name=str(row["name"]) if row["name"] is not None else None,
            event_ids=_decode_filter(row["event_ids_json"], "event_ids"),
            country_names=_decode_filter(row["country_names_json"], "country_names"),
            continent_names=_decode_filter(row["continent_names_json"], "continent_names"),
            active=bool(row["active"]),
            created_at=created_at,
            updated_at=updated_at,
            cancelled_at=from_utc_text(row["cancelled_at"]),
        )

    def find_subscriber(self, email: str) -> SubscriberRecord | None:
        row = self._connection.execute(
            "SELECT * FROM subscribers WHERE email = ?", (email,)
        ).fetchone()
        return self._subscriber_from_row(row) if row is not None else None

    def list_subscribers(self) -> list[SubscriberRecord]:
        rows = self._connection.execute("SELECT * FROM subscribers ORDER BY email").fetchall()
        return [self._subscriber_from_row(row) for row in rows]

    def subscriber_count(self, *, active_only: bool = True) -> int:
        if active_only:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM subscribers WHERE active = 1"
            ).fetchone()
        else:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM subscribers").fetchone()
        return int(row["count"])

    def register_subscriber(
        self,
        recipient: RecipientConfig,
        now: datetime,
    ) -> bool:
        timestamp = to_utc_text(now)
        with self._transaction():
            row = self._connection.execute(
                "SELECT active FROM subscribers WHERE email = ?", (recipient.email,)
            ).fetchone()
            values = (
                recipient.email,
                recipient.name,
                recipient.latitude,
                recipient.longitude,
                recipient.max_distance_km,
                _encode_filter(recipient.event_ids),
                _encode_filter(recipient.country_names),
                _encode_filter(recipient.continent_names),
                timestamp,
            )
            if row is not None and bool(row["active"]):
                return False
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO subscribers(
                        email, name, latitude, longitude, max_distance_km,
                        event_ids_json, country_names_json, continent_names_json,
                        active, created_at, updated_at, cancelled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
                    """,
                    (*values, timestamp),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE subscribers
                    SET name = ?, latitude = ?, longitude = ?, max_distance_km = ?,
                        event_ids_json = ?, country_names_json = ?,
                        continent_names_json = ?, active = 1, updated_at = ?,
                        cancelled_at = NULL
                    WHERE email = ?
                    """,
                    (
                        recipient.name,
                        recipient.latitude,
                        recipient.longitude,
                        recipient.max_distance_km,
                        _encode_filter(recipient.event_ids),
                        _encode_filter(recipient.country_names),
                        _encode_filter(recipient.continent_names),
                        timestamp,
                        recipient.email,
                    ),
                )
        return True

    def update_subscriber(
        self,
        recipient: RecipientConfig,
        now: datetime,
    ) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE subscribers
            SET name = ?, latitude = ?, longitude = ?, max_distance_km = ?, event_ids_json = ?,
                country_names_json = ?, continent_names_json = ?, updated_at = ?
            WHERE email = ? AND active = 1
            """,
            (
                recipient.name,
                recipient.latitude,
                recipient.longitude,
                recipient.max_distance_km,
                _encode_filter(recipient.event_ids),
                _encode_filter(recipient.country_names),
                _encode_filter(recipient.continent_names),
                to_utc_text(now),
                recipient.email,
            ),
        )
        return cursor.rowcount == 1

    def cancel_subscriber(self, email: str, now: datetime) -> bool:
        timestamp = to_utc_text(now)
        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE subscribers
                SET active = 0, updated_at = ?, cancelled_at = ?
                WHERE email = ? AND active = 1
                """,
                (timestamp, timestamp, email),
            )
            if cursor.rowcount != 1:
                return False
            self._connection.execute(
                """
                UPDATE deliveries
                SET status = ?, lease_until = NULL, claim_token = NULL,
                    last_error = ?
                WHERE recipient_email = ? AND status = ?
                """,
                (
                    DeliveryStatus.BLOCKED,
                    "subscription cancelled before delivery",
                    email,
                    DeliveryStatus.PENDING,
                ),
            )
        return True

    def is_baseline_initialized(self) -> bool:
        return self._get_state("baseline_completed_at") is not None

    def baseline_completed_at(self) -> datetime:
        value = from_utc_text(self._get_state("baseline_completed_at"))
        if value is None:
            raise StateError("baseline has not been initialized")
        return value

    def baseline_cutoff_at(self) -> datetime:
        value = from_utc_text(self._get_state("baseline_cutoff_at"))
        return value or self.baseline_completed_at()

    def incremental_checkpoint_at(self) -> datetime:
        value = from_utc_text(self._get_state("incremental_checkpoint_at"))
        return value or self.baseline_completed_at()

    def full_reconciliation_due(self, now: datetime, interval: timedelta) -> bool:
        last_full = from_utc_text(self._get_state("last_full_success_at"))
        return last_full is None or now >= last_full + interval

    def initialize_baseline(
        self,
        summaries: Iterable[CompetitionSummary],
        completed_at: datetime,
        *,
        snapshot_started_at: datetime | None = None,
    ) -> int:
        if self.is_baseline_initialized():
            raise StateError("baseline is already initialized")
        timestamp = to_utc_text(completed_at)
        cutoff = to_utc_text(snapshot_started_at or completed_at)
        count = 0
        with self._transaction():
            for summary in summaries:
                self._connection.execute(
                    """
                    INSERT INTO competitions(
                        id, announced_at, discovered_at, processed_at, status, summary_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary.competition_id,
                        to_utc_text(summary.announced_at),
                        timestamp,
                        timestamp,
                        CompetitionStatus.BASELINE,
                        summary.raw_json,
                    ),
                )
                count += 1
            self._set_state("baseline_cutoff_at", cutoff)
            self._set_state("baseline_completed_at", timestamp)
            self._set_state("incremental_checkpoint_at", timestamp)
            self._set_state("last_full_success_at", timestamp)
        return count

    def record_scan(
        self,
        summaries: Iterable[CompetitionSummary],
        completed_at: datetime,
        *,
        full_reconciliation: bool,
    ) -> DiscoveryStats:
        cutoff = self.baseline_cutoff_at()
        timestamp = to_utc_text(completed_at)
        discovered = queued_for_details = ignored = silently_recorded = 0

        with self._transaction():
            for summary in summaries:
                exists = self._connection.execute(
                    "SELECT 1 FROM competitions WHERE id = ?", (summary.competition_id,)
                ).fetchone()
                if exists is not None:
                    continue

                discovered += 1
                if summary.announced_at <= cutoff:
                    status = CompetitionStatus.BASELINE
                    processed_at = timestamp
                    silently_recorded += 1
                elif not OFFICIAL_EVENT_IDS.isdisjoint(summary.event_ids):
                    status = CompetitionStatus.PENDING_DETAILS
                    processed_at = None
                    queued_for_details += 1
                else:
                    status = CompetitionStatus.IGNORED_NO_OFFICIAL_EVENTS
                    processed_at = timestamp
                    ignored += 1

                self._connection.execute(
                    """
                    INSERT INTO competitions(
                        id, announced_at, discovered_at, processed_at, status,
                        summary_json, next_enrichment_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary.competition_id,
                        to_utc_text(summary.announced_at),
                        timestamp,
                        processed_at,
                        status,
                        summary.raw_json,
                        timestamp if status == CompetitionStatus.PENDING_DETAILS else None,
                    ),
                )

            if full_reconciliation:
                self._set_state("last_full_success_at", timestamp)
            else:
                self._set_state("incremental_checkpoint_at", timestamp)

        return DiscoveryStats(discovered, queued_for_details, ignored, silently_recorded)

    def due_enrichments(self, now: datetime, *, limit: int = 100) -> list[PendingCompetition]:
        rows = self._connection.execute(
            """
            SELECT summary_json, status, enrichment_attempts, coordinate_deadline_at
            FROM competitions
            WHERE status IN (?, ?)
              AND next_enrichment_at <= ?
            ORDER BY announced_at, id
            LIMIT ?
            """,
            (
                CompetitionStatus.PENDING_DETAILS,
                CompetitionStatus.PENDING_COORDINATES,
                to_utc_text(now),
                limit,
            ),
        ).fetchall()
        return [
            PendingCompetition(
                summary=summary_from_json(str(row["summary_json"])),
                status=CompetitionStatus(str(row["status"])),
                enrichment_attempts=int(row["enrichment_attempts"]),
                coordinate_deadline_at=from_utc_text(row["coordinate_deadline_at"]),
            )
            for row in rows
        ]

    def mark_ignored(
        self,
        competition_id: str,
        status: CompetitionStatus,
        details_json: str,
        now: datetime,
    ) -> None:
        if status not in {
            CompetitionStatus.IGNORED_CANCELLED,
            CompetitionStatus.IGNORED_NO_MINX,
            CompetitionStatus.IGNORED_NO_OFFICIAL_EVENTS,
        }:
            raise ValueError("invalid ignored competition status")
        self._connection.execute(
            """
            UPDATE competitions
            SET status = ?, detail_json = ?, processed_at = ?, next_enrichment_at = NULL,
                last_error = NULL
            WHERE id = ?
            """,
            (status, details_json, to_utc_text(now), competition_id),
        )

    def mark_enrichment_retry(
        self,
        competition_id: str,
        now: datetime,
        error: str,
        *,
        status: CompetitionStatus | None = None,
        coordinate_deadline_at: datetime | None = None,
    ) -> None:
        row = self._connection.execute(
            "SELECT enrichment_attempts, status FROM competitions WHERE id = ?",
            (competition_id,),
        ).fetchone()
        if row is None:
            raise StateError(f"unknown competition {competition_id}")
        attempts = int(row["enrichment_attempts"]) + 1
        next_status = status or CompetitionStatus(str(row["status"]))
        self._connection.execute(
            """
            UPDATE competitions
            SET status = ?, enrichment_attempts = ?, next_enrichment_at = ?,
                coordinate_deadline_at = COALESCE(?, coordinate_deadline_at), last_error = ?
            WHERE id = ?
            """,
            (
                next_status,
                attempts,
                to_utc_text(retry_at(now, attempts)),
                to_utc_text(coordinate_deadline_at) if coordinate_deadline_at else None,
                error[:1000],
                competition_id,
            ),
        )

    def queue_deliveries(
        self,
        competition_id: str,
        details_json: str,
        drafts: Iterable[DeliveryDraft],
        now: datetime,
    ) -> int:
        timestamp = to_utc_text(now)
        queued = 0
        with self._transaction():
            for draft in drafts:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO deliveries(
                        competition_id, recipient_email, recipient_name,
                        recipient_latitude, recipient_longitude, message_id,
                        subject, text_body, html_body, status, next_attempt_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        competition_id,
                        draft.recipient_email,
                        draft.recipient_name,
                        draft.recipient_latitude,
                        draft.recipient_longitude,
                        draft.message_id,
                        draft.subject,
                        draft.text_body,
                        draft.html_body,
                        DeliveryStatus.PENDING,
                        timestamp,
                        timestamp,
                    ),
                )
                queued += cursor.rowcount
            self._connection.execute(
                """
                UPDATE competitions
                SET status = ?, detail_json = ?, processed_at = ?, next_enrichment_at = NULL,
                    last_error = NULL
                WHERE id = ?
                """,
                (CompetitionStatus.QUEUED, details_json, timestamp, competition_id),
            )
        return queued

    def claim_delivery(self, now: datetime, *, lease: timedelta) -> Delivery | None:
        now_text = to_utc_text(now)
        with self._transaction():
            row = self._connection.execute(
                """
                SELECT * FROM deliveries
                WHERE ((status = ? AND next_attempt_at <= ?)
                   OR (status = ? AND lease_until <= ?))
                  AND NOT EXISTS (
                      SELECT 1 FROM subscribers
                      WHERE subscribers.email = deliveries.recipient_email
                        AND subscribers.active = 0
                  )
                ORDER BY created_at, id
                LIMIT 1
                """,
                (
                    DeliveryStatus.PENDING,
                    now_text,
                    DeliveryStatus.SENDING,
                    now_text,
                ),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"]) + 1
            claim_token = secrets.token_hex(16)
            self._connection.execute(
                """
                UPDATE deliveries
                SET status = ?, attempts = ?, lease_until = ?, claim_token = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    DeliveryStatus.SENDING,
                    attempts,
                    to_utc_text(now + lease),
                    claim_token,
                    int(row["id"]),
                ),
            )
            created_at = from_utc_text(str(row["created_at"]))
            assert created_at is not None
            return Delivery(
                delivery_id=int(row["id"]),
                claim_token=claim_token,
                competition_id=str(row["competition_id"]),
                recipient_email=str(row["recipient_email"]),
                recipient_name=(
                    str(row["recipient_name"]) if row["recipient_name"] is not None else None
                ),
                message_id=str(row["message_id"]),
                subject=str(row["subject"]),
                text_body=str(row["text_body"]),
                html_body=str(row["html_body"]),
                created_at=created_at,
                attempts=attempts,
            )

    def mark_delivery_sent(self, delivery: Delivery, now: datetime) -> None:
        cursor = self._connection.execute(
            """
            UPDATE deliveries
            SET status = ?, sent_at = ?, lease_until = NULL, claim_token = NULL,
                last_error = NULL
            WHERE id = ? AND status = ? AND claim_token = ?
            """,
            (
                DeliveryStatus.SENT,
                to_utc_text(now),
                delivery.delivery_id,
                DeliveryStatus.SENDING,
                delivery.claim_token,
            ),
        )
        self._require_claim(cursor, delivery)

    def mark_delivery_retry(
        self,
        delivery: Delivery,
        now: datetime,
        error: str,
        *,
        immediate: bool = False,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE deliveries
            SET status = ?, next_attempt_at = ?, lease_until = NULL, claim_token = NULL,
                last_error = ?
            WHERE id = ? AND status = ? AND claim_token = ?
            """,
            (
                DeliveryStatus.PENDING,
                to_utc_text(now if immediate else retry_at(now, delivery.attempts)),
                error[:1000],
                delivery.delivery_id,
                DeliveryStatus.SENDING,
                delivery.claim_token,
            ),
        )
        self._require_claim(cursor, delivery)

    def mark_delivery_blocked(self, delivery: Delivery, error: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE deliveries
            SET status = ?, lease_until = NULL, claim_token = NULL, last_error = ?
            WHERE id = ? AND status = ? AND claim_token = ?
            """,
            (
                DeliveryStatus.BLOCKED,
                error[:1000],
                delivery.delivery_id,
                DeliveryStatus.SENDING,
                delivery.claim_token,
            ),
        )
        self._require_claim(cursor, delivery)

    def retry_blocked_deliveries(self, now: datetime) -> int:
        cursor = self._connection.execute(
            """
            UPDATE deliveries
            SET status = ?, next_attempt_at = ?, lease_until = NULL, claim_token = NULL,
                last_error = NULL
            WHERE status = ?
            """,
            (DeliveryStatus.PENDING, to_utc_text(now), DeliveryStatus.BLOCKED),
        )
        return cursor.rowcount

    def clear_all(self) -> dict[str, int]:
        with self._transaction():
            competition_count = int(
                self._connection.execute("SELECT COUNT(*) FROM competitions").fetchone()[0]
            )
            delivery_count = int(
                self._connection.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
            )
            self._connection.execute("DELETE FROM deliveries")
            self._connection.execute("DELETE FROM competitions")
            self._connection.execute("DELETE FROM subscribers")
            self._connection.execute("DELETE FROM app_state")
            self._connection.execute("DELETE FROM sqlite_sequence WHERE name = 'deliveries'")
        return {"competitions": competition_count, "deliveries": delivery_count}

    def counts(self) -> dict[str, int]:
        competition_count = self._connection.execute(
            "SELECT COUNT(*) AS count FROM competitions"
        ).fetchone()
        rows = self._connection.execute(
            "SELECT status, COUNT(*) AS count FROM deliveries GROUP BY status"
        ).fetchall()
        counts = {f"deliveries_{row['status']}": int(row["count"]) for row in rows}
        counts["competitions"] = int(competition_count["count"])
        return counts

    def admin_snapshot(self, *, limit: int = 200) -> dict[str, object]:
        if not 1 <= limit <= 500:
            raise ValueError("admin snapshot limit must be between 1 and 500")

        subscriber_counts = self._connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active
            FROM subscribers
            """
        ).fetchone()
        competition_counts = self._status_counts("competitions")
        delivery_counts = self._status_counts("deliveries")
        app_state = {
            str(row["key"]): str(row["value"])
            for row in self._connection.execute(
                "SELECT key, value FROM app_state ORDER BY key"
            ).fetchall()
        }

        subscribers = [
            {
                "email": record.email,
                "name": record.name,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "max_distance_km": record.max_distance_km,
                "events": sorted(record.event_ids) if record.event_ids is not None else None,
                "countries": (
                    sorted(record.country_names) if record.country_names is not None else None
                ),
                "continents": (
                    sorted(record.continent_names)
                    if record.continent_names is not None
                    else None
                ),
                "active": record.active,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
                "cancelled_at": (
                    record.cancelled_at.isoformat() if record.cancelled_at is not None else None
                ),
            }
            for record in (
                self._subscriber_from_row(row)
                for row in self._connection.execute(
                    "SELECT * FROM subscribers ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            )
        ]

        competition_rows = self._connection.execute(
            """
            SELECT id, announced_at, discovered_at, processed_at, status, summary_json,
                   enrichment_attempts, next_enrichment_at, coordinate_deadline_at, last_error
            FROM competitions
            ORDER BY discovered_at DESC, id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        competitions: list[dict[str, object]] = []
        for row in competition_rows:
            try:
                summary = json.loads(str(row["summary_json"]))
            except json.JSONDecodeError as exc:
                raise StateError(f"stored competition {row['id']} summary is invalid JSON") from exc
            if not isinstance(summary, dict):
                raise StateError(f"stored competition {row['id']} summary must be an object")
            competitions.append(
                {
                    "id": str(row["id"]),
                    "name": summary.get("name"),
                    "start_date": summary.get("start_date"),
                    "end_date": summary.get("end_date"),
                    "city": summary.get("city"),
                    "country_iso2": summary.get("country_iso2"),
                    "events": summary.get("event_ids"),
                    "status": str(row["status"]),
                    "announced_at": str(row["announced_at"]),
                    "discovered_at": str(row["discovered_at"]),
                    "processed_at": (
                        str(row["processed_at"]) if row["processed_at"] is not None else None
                    ),
                    "enrichment_attempts": int(row["enrichment_attempts"]),
                    "next_enrichment_at": (
                        str(row["next_enrichment_at"])
                        if row["next_enrichment_at"] is not None
                        else None
                    ),
                    "coordinate_deadline_at": (
                        str(row["coordinate_deadline_at"])
                        if row["coordinate_deadline_at"] is not None
                        else None
                    ),
                    "last_error": (
                        str(row["last_error"]) if row["last_error"] is not None else None
                    ),
                }
            )

        delivery_rows = self._connection.execute(
            """
            SELECT deliveries.id, deliveries.competition_id, deliveries.recipient_email,
                   deliveries.recipient_name, deliveries.subject, deliveries.status,
                   deliveries.attempts, deliveries.next_attempt_at, deliveries.lease_until,
                   deliveries.last_error, deliveries.created_at, deliveries.sent_at,
                   competitions.summary_json
            FROM deliveries
            JOIN competitions ON competitions.id = deliveries.competition_id
            ORDER BY deliveries.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        deliveries: list[dict[str, object]] = []
        for row in delivery_rows:
            try:
                summary = json.loads(str(row["summary_json"]))
            except json.JSONDecodeError as exc:
                raise StateError(
                    f"stored competition {row['competition_id']} summary is invalid JSON"
                ) from exc
            competition_name = summary.get("name") if isinstance(summary, dict) else None
            deliveries.append(
                {
                    "id": int(row["id"]),
                    "competition_id": str(row["competition_id"]),
                    "competition_name": competition_name,
                    "recipient_email": str(row["recipient_email"]),
                    "recipient_name": (
                        str(row["recipient_name"])
                        if row["recipient_name"] is not None
                        else None
                    ),
                    "subject": str(row["subject"]),
                    "status": str(row["status"]),
                    "attempts": int(row["attempts"]),
                    "next_attempt_at": str(row["next_attempt_at"]),
                    "lease_until": (
                        str(row["lease_until"]) if row["lease_until"] is not None else None
                    ),
                    "last_error": (
                        str(row["last_error"]) if row["last_error"] is not None else None
                    ),
                    "created_at": str(row["created_at"]),
                    "sent_at": str(row["sent_at"]) if row["sent_at"] is not None else None,
                }
            )

        subscriber_total = int(subscriber_counts["total"])
        subscriber_active = int(subscriber_counts["active"] or 0)
        return {
            "counts": {
                "subscribers": {
                    "total": subscriber_total,
                    "active": subscriber_active,
                    "inactive": subscriber_total - subscriber_active,
                },
                "competitions": competition_counts,
                "deliveries": delivery_counts,
            },
            "checkpoints": {
                "baseline_completed_at": app_state.get("baseline_completed_at"),
                "incremental_checkpoint_at": app_state.get("incremental_checkpoint_at"),
                "last_full_success_at": app_state.get("last_full_success_at"),
            },
            "subscribers": subscribers,
            "competitions": competitions,
            "deliveries": deliveries,
            "limit": limit,
        }

    def _status_counts(self, table: str) -> dict[str, int]:
        if table not in {"competitions", "deliveries"}:
            raise ValueError("unsupported status count table")
        rows = self._connection.execute(
            f'SELECT status, COUNT(*) AS count FROM "{table}" GROUP BY status'
        ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    @staticmethod
    def _require_claim(cursor: sqlite3.Cursor, delivery: Delivery) -> None:
        if cursor.rowcount != 1:
            raise StateError(f"delivery claim {delivery.delivery_id} is no longer owned")
