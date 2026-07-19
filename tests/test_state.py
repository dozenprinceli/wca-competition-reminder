import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest

from tests.conftest import NOW, make_summary
from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.models import CompetitionSummary
from wca_competition_reminder.state import (
    ACTIVITY_LOG_RETENTION_DAYS,
    MIGRATABLE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    StateError,
    StateStore,
)


def downgrade_current_database_to_v4(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE subscriber_conditions")
        connection.execute(f"PRAGMA user_version = {MIGRATABLE_SCHEMA_VERSION}")


def test_failed_transaction_rolls_back_and_connection_remains_reusable(
    tmp_path: Path,
) -> None:
    def interrupted_baseline() -> Iterator[CompetitionSummary]:
        yield make_summary("PartiallyRead2026")
        raise RuntimeError("source interrupted")

    with StateStore(tmp_path / "state.sqlite3") as state:
        with pytest.raises(RuntimeError, match="source interrupted"):
            state.initialize_baseline(interrupted_baseline(), NOW)

        assert not state.is_baseline_initialized()
        assert state.counts() == {"competitions": 0}

        state.initialize_baseline([], NOW)
        stats = state.record_scan(
            [make_summary("Recovered2026", announced_at=NOW + timedelta(seconds=1))],
            NOW + timedelta(minutes=1),
            full_reconciliation=False,
        )

        assert stats.discovered == 1
        assert state.counts() == {"competitions": 1}


def test_current_schema_has_ordered_subscriber_conditions(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path):
        pass

    with sqlite3.connect(path) as connection:
        subscriber_columns = {
            str(row[1]): int(row[3])
            for row in connection.execute("PRAGMA table_info(subscribers)").fetchall()
        }
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        condition_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(subscriber_conditions)").fetchall()
        }

    assert "token_hash" not in subscriber_columns
    assert subscriber_columns["latitude"] == 0
    assert subscriber_columns["longitude"] == 0
    assert subscriber_columns["max_distance_km"] == 0
    assert {
        "subscriber_email",
        "position",
        "latitude",
        "longitude",
        "max_distance_km",
        "event_ids_json",
        "country_names_json",
        "continent_names_json",
    } <= condition_columns
    assert version == SCHEMA_VERSION


def test_v4_schema_is_fully_migrated_to_one_condition_without_losing_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path) as state:
        state.register_subscriber(
            RecipientConfig(
                "legacy@example.com",
                31.2304,
                121.4737,
                "Legacy",
                event_ids=frozenset({"333"}),
                country_names=frozenset({"China"}),
                max_distance_km=300,
            ),
            NOW,
        )
        state.initialize_baseline([make_summary("LegacyCompetition2026")], NOW)
    downgrade_current_database_to_v4(path)

    with StateStore(path) as state:
        subscriber = state.find_subscriber("legacy@example.com")
        assert subscriber is not None
        assert subscriber.name == "Legacy"
        assert len(subscriber.conditions) == 1
        assert subscriber.conditions[0].latitude == 31.2304
        assert subscriber.conditions[0].max_distance_km == 300
        assert subscriber.conditions[0].event_ids == frozenset({"333"})
        assert subscriber.conditions[0].country_names == frozenset({"China"})
        assert state.counts() == {"competitions": 1}

    with sqlite3.connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        condition_count = int(
            connection.execute("SELECT COUNT(*) FROM subscriber_conditions").fetchone()[0]
        )
    assert version == SCHEMA_VERSION
    assert condition_count == 1


def test_v5_schema_without_notification_language_defaults_existing_rows_to_chinese(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path) as state:
        state.register_subscriber(
            RecipientConfig("legacy-language@example.com", None, None, "Legacy"),
            NOW,
        )

    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE subscribers DROP COLUMN notification_language")
        connection.execute(f"PRAGMA user_version = {MIGRATABLE_SCHEMA_VERSION}")

    with StateStore(path) as state:
        subscriber = state.find_subscriber("legacy-language@example.com")
        assert subscriber is not None
        assert subscriber.notification_language == "zh"

    with sqlite3.connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        language = connection.execute(
            "SELECT notification_language FROM subscribers WHERE email = ?",
            ("legacy-language@example.com",),
        ).fetchone()[0]
    assert version == SCHEMA_VERSION
    assert language == "zh"


def test_concurrent_v4_open_only_migrates_once(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path):
        pass
    downgrade_current_database_to_v4(path)
    barrier = Barrier(2)

    def open_store() -> int:
        barrier.wait()
        with StateStore(path) as state:
            return state.subscriber_count()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _index: open_store(), range(2))) == [0, 0]


def test_malformed_v4_schema_is_rejected_without_partial_migration(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE subscribers (email TEXT PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {MIGRATABLE_SCHEMA_VERSION}")

    with pytest.raises(StateError, match="cannot migrate it safely"):
        StateStore(path)


def test_older_state_schema_is_rejected_without_migration(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE subscribers (email TEXT PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {MIGRATABLE_SCHEMA_VERSION - 1}")

    with pytest.raises(StateError, match="no longer supported"):
        StateStore(path)


def test_newer_state_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(StateError, match="newer than supported"):
        StateStore(path)


def test_admin_snapshot_returns_counts_checkpoints_and_recent_data(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        state.register_subscriber(
            RecipientConfig("active@example.com", 31.2, 121.4, "Active"),
            NOW,
        )
        state.register_subscriber(
            RecipientConfig("cancelled@example.com", None, None, "Cancelled"),
            NOW,
        )
        state.cancel_subscriber("cancelled@example.com", NOW + timedelta(minutes=1))
        state.initialize_baseline([make_summary("Snapshot2026")], NOW)

        snapshot = state.admin_snapshot()

    assert snapshot["counts"]["subscribers"] == {"total": 2, "active": 1, "inactive": 1}
    assert snapshot["counts"]["competitions"] == {"baseline": 1, "total": 1}
    assert snapshot["counts"]["deliveries"] == {"total": 0}
    assert snapshot["checkpoints"]["baseline_completed_at"] is not None
    assert [item["email"] for item in snapshot["subscribers"]] == [
        "cancelled@example.com",
        "active@example.com",
    ]
    assert snapshot["competitions"][0]["name"] == "Competition Snapshot2026"


@pytest.mark.parametrize("limit", (0, 501))
def test_admin_snapshot_rejects_invalid_limits(tmp_path: Path, limit: int) -> None:
    with (
        StateStore(tmp_path / "state.sqlite3") as state,
        pytest.raises(ValueError, match="between 1 and 500"),
    ):
        state.admin_snapshot(limit=limit)


def test_activity_logs_roll_over_after_seven_days_and_support_pagination(
    tmp_path: Path,
) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        state.record_activity_log(
            created_at=NOW - timedelta(days=ACTIVITY_LOG_RETENTION_DAYS + 1),
            actor_type="user",
            action="subscription_page_view",
            outcome="success",
            email=None,
            client_ip="192.0.2.1",
            method="GET",
            path="/",
        )
        boundary_id = state.record_activity_log(
            created_at=NOW - timedelta(days=ACTIVITY_LOG_RETENTION_DAYS),
            actor_type="user",
            action="subscription_lookup",
            outcome="not_found",
            email="boundary@example.com",
            client_ip="192.0.2.2",
            method="GET",
            path="/api/subscriptions",
        )
        user_id = state.record_activity_log(
            created_at=NOW,
            actor_type="user",
            action="subscription_register",
            outcome="success",
            email="new@example.com",
            client_ip="192.0.2.3",
            method="POST",
            path="/api/subscriptions",
            user_agent="test-browser/1.0",
            details={"subscription": {"events": ["333", "minx"]}},
        )
        admin_id = state.record_activity_log(
            created_at=NOW,
            actor_type="admin",
            action="admin_login",
            outcome="success",
            email=None,
            client_ip="192.0.2.4",
            method="POST",
            path="/api/admin/login",
            details={"username": "operator"},
        )

        first_page = state.activity_logs(now=NOW, limit=2)
        second_page = state.activity_logs(
            now=NOW,
            limit=2,
            before_id=first_page["next_before_id"],
        )
        searched = state.activity_logs(
            now=NOW,
            actor_type="user",
            action="subscription_register",
            outcome="success",
            search="new@example.com",
        )
        snapshot = state.admin_snapshot(now=NOW)

    assert first_page["total"] == 3
    assert first_page["has_more"] is True
    assert [item["id"] for item in first_page["items"]] == [admin_id, user_id]
    assert first_page["next_before_id"] == user_id
    assert [item["id"] for item in second_page["items"]] == [boundary_id]
    assert second_page["has_more"] is False
    assert searched["total"] == 1
    assert searched["items"][0]["email"] == "new@example.com"
    assert searched["items"][0]["details"] == {
        "subscription": {"events": ["333", "minx"]}
    }
    assert searched["retention_days"] == 7
    assert snapshot["counts"]["activity_logs"] == {
        "total": 3,
        "users": 2,
        "admins": 1,
        "retention_days": 7,
    }
