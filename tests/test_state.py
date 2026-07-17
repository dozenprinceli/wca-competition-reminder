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
    MIGRATABLE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    StateError,
    StateStore,
)


def downgrade_current_database_to_v3(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE subscribers DROP COLUMN max_distance_km")
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


def test_current_schema_has_distance_filter_and_allows_empty_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path):
        pass

    with sqlite3.connect(path) as connection:
        subscriber_columns = {
            str(row[1]): int(row[3])
            for row in connection.execute("PRAGMA table_info(subscribers)").fetchall()
        }
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])

    assert "token_hash" not in subscriber_columns
    assert subscriber_columns["latitude"] == 0
    assert subscriber_columns["longitude"] == 0
    assert subscriber_columns["max_distance_km"] == 0
    assert version == SCHEMA_VERSION


def test_v3_schema_is_migrated_without_losing_state(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path) as state:
        state.register_subscriber(
            RecipientConfig("legacy@example.com", 31.2304, 121.4737, "Legacy"),
            NOW,
        )
        state.initialize_baseline([make_summary("LegacyCompetition2026")], NOW)
    downgrade_current_database_to_v3(path)

    with StateStore(path) as state:
        subscriber = state.find_subscriber("legacy@example.com")
        assert subscriber is not None
        assert subscriber.name == "Legacy"
        assert subscriber.max_distance_km is None
        assert state.counts() == {"competitions": 1}

    with sqlite3.connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(subscribers)")}
    assert version == SCHEMA_VERSION
    assert "max_distance_km" in columns


def test_concurrent_v3_open_only_migrates_once(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with StateStore(path):
        pass
    downgrade_current_database_to_v3(path)
    barrier = Barrier(2)

    def open_store() -> int:
        barrier.wait()
        with StateStore(path) as state:
            return state.subscriber_count()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _index: open_store(), range(2))) == [0, 0]


def test_malformed_v3_schema_is_rejected_without_partial_migration(tmp_path: Path) -> None:
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
