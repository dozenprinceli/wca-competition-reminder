from pathlib import Path

import clear_database
from tests.conftest import NOW, make_config, make_details, make_summary
from wca_competition_reminder.email_content import build_delivery_drafts
from wca_competition_reminder.locking import ProcessLock
from wca_competition_reminder.state import StateStore


def populate_database(tmp_path: Path):
    config = make_config(tmp_path)
    summary = make_summary("Stored2026")
    details = make_details("Stored2026")
    drafts = build_delivery_drafts(
        details,
        config.recipients[:1],
        from_address=config.smtp.from_address,
        distance_available=True,
    )
    with StateStore(config.state_path) as state:
        state.initialize_baseline([summary], NOW)
        state.queue_deliveries(summary.competition_id, details.raw_json, drafts, NOW)
    return config


def test_clear_all_removes_state_and_deliveries(tmp_path: Path) -> None:
    config = populate_database(tmp_path)

    with StateStore(config.state_path) as state:
        assert state.clear_all() == {"competitions": 1, "deliveries": 1}
        assert not state.is_baseline_initialized()
        assert state.counts() == {"competitions": 0}


def test_script_requires_exact_confirmation(tmp_path: Path, monkeypatch) -> None:
    config = populate_database(tmp_path)
    monkeypatch.setattr(clear_database, "load_config", lambda _: config)
    output: list[str] = []

    exit_code = clear_database.main(
        ["--config", str(tmp_path / "config.toml")],
        input_func=lambda _: "yes",
        output=output.append,
    )

    assert exit_code == 0
    assert any("cancelled" in line for line in output)
    with StateStore(config.state_path) as state:
        assert state.is_baseline_initialized()
        assert state.counts() == {"competitions": 1, "deliveries_pending": 1}


def test_script_clears_database_after_confirmation(tmp_path: Path, monkeypatch) -> None:
    config = populate_database(tmp_path)
    monkeypatch.setattr(clear_database, "load_config", lambda _: config)
    output: list[str] = []

    exit_code = clear_database.main(
        ["--config", str(tmp_path / "config.toml")],
        input_func=lambda _: clear_database.CONFIRMATION_WORD,
        output=output.append,
    )

    assert exit_code == 0
    assert "Database cleared: competitions=1 deliveries=1" in output
    assert output[-1] == "The next poll will create a new silent baseline."
    with StateStore(config.state_path) as state:
        assert not state.is_baseline_initialized()
        assert state.counts() == {"competitions": 0}


def test_script_refuses_to_clear_while_service_lock_is_held(tmp_path: Path, monkeypatch) -> None:
    config = populate_database(tmp_path)
    monkeypatch.setattr(clear_database, "load_config", lambda _: config)
    errors: list[str] = []

    with ProcessLock(config.lock_path):
        exit_code = clear_database.main(
            ["--config", str(tmp_path / "config.toml")],
            input_func=lambda _: clear_database.CONFIRMATION_WORD,
            output=lambda _: None,
            error_output=errors.append,
        )

    assert exit_code == 1
    assert errors == ["Cannot clear database: another reminder process is already running"]
    with StateStore(config.state_path) as state:
        assert state.is_baseline_initialized()
        assert state.counts() == {"competitions": 1, "deliveries_pending": 1}
