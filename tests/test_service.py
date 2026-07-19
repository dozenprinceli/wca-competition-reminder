import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event

import pytest

from tests.conftest import (
    NOW,
    FakeMailer,
    FakeWca,
    MutableClock,
    make_config,
    make_details,
    make_summary,
)
from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.email_content import build_delivery_drafts
from wca_competition_reminder.mailer import DeliverySendError
from wca_competition_reminder.models import CompetitionStatus, FollowCondition, WcaCountry
from wca_competition_reminder.service import ReminderService
from wca_competition_reminder.state import StateError, StateStore
from wca_competition_reminder.wca import WcaApiError


def stored_competition_status(path: Path, competition_id: str) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT status FROM competitions WHERE id = ?", (competition_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_first_run_builds_silent_baseline(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    wca = FakeWca(
        all_future=[
            make_summary("MinxBaseline2026"),
            make_summary("NoMinxBaseline2026", event_ids=["333"]),
        ]
    )
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        assert ReminderService(config, state, wca, mailer, clock=MutableClock()).run_once()
        assert state.is_baseline_initialized()
        assert state.counts() == {"competitions": 2}

    assert mailer.sent == []
    assert wca.detail_calls == []


def test_failed_baseline_is_not_partially_initialized(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    wca = FakeWca(all_error=WcaApiError("page two failed"))

    with StateStore(config.state_path) as state:
        service = ReminderService(config, state, wca, FakeMailer(), clock=MutableClock())
        with pytest.raises(WcaApiError):
            service.run_once()
        assert not state.is_baseline_initialized()
        assert state.counts() == {"competitions": 0}


def test_competition_announced_during_baseline_fetch_is_not_silenced(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    clock = MutableClock()
    new_summary = make_summary(
        "DuringBaseline2026",
        announced_at=NOW + timedelta(seconds=30),
    )
    details = make_details(
        "DuringBaseline2026",
        announced_at=NOW + timedelta(seconds=30),
    )

    class AdvancingWca(FakeWca):
        def fetch_all_future(self, current_date):
            clock.current += timedelta(minutes=1)
            return super().fetch_all_future(current_date)

    wca = AdvancingWca(
        recent_future=[new_summary],
        details={"DuringBaseline2026": details},
    )
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        service = ReminderService(config, state, wca, mailer, clock=clock)
        assert service.run_once()
        assert service.run_once()

    assert len(mailer.sent) == 2


def test_new_minx_competition_sends_personalized_email_once(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    baseline = make_summary("Baseline2026", announced_at=NOW - timedelta(days=1))
    new_summary = make_summary("NewMinx2026", announced_at=NOW + timedelta(seconds=1))
    details = make_details("NewMinx2026", announced_at=NOW + timedelta(seconds=1))
    wca = FakeWca(recent_future=[new_summary], details={"NewMinx2026": details})
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([baseline], NOW)
        service = ReminderService(config, state, wca, mailer, clock=clock)
        assert service.run_once()
        assert state.counts() == {"competitions": 2, "deliveries_sent": 2}
        assert service.run_once()
        assert state.counts() == {"competitions": 2, "deliveries_sent": 2}

    assert len(mailer.sent) == 2
    assert "0.0 km" in mailer.sent[0].text_body
    assert "1067" in mailer.sent[1].text_body
    assert wca.detail_calls == ["NewMinx2026"]


def test_new_non_minx_official_competition_sends_reminders(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    new_summary = make_summary(
        "NewThreeByThree2026",
        announced_at=NOW + timedelta(seconds=1),
        event_ids=["333"],
    )
    details = make_details("NewThreeByThree2026", event_ids=["333"])
    wca = FakeWca(
        recent_future=[new_summary],
        details={"NewThreeByThree2026": details},
    )
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        assert ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()
        assert state.counts() == {"competitions": 1, "deliveries_sent": 2}

    assert wca.detail_calls == ["NewThreeByThree2026"]
    assert all("三阶魔方 (333)" in delivery.text_body for delivery in mailer.sent)


@pytest.mark.parametrize(
    ("details_kwargs", "expected_status"),
    [
        (
            {"cancelled_at": "2026-07-16T03:00:00Z"},
            CompetitionStatus.IGNORED_CANCELLED,
        ),
        (
            {"event_ids": ["unofficial"]},
            CompetitionStatus.IGNORED_NO_OFFICIAL_EVENTS,
        ),
    ],
)
def test_detail_recheck_ignores_cancelled_or_missing_official_events(
    tmp_path: Path,
    details_kwargs: dict[str, object],
    expected_status: CompetitionStatus,
) -> None:
    config = make_config(tmp_path)
    competition_id = "ChangedDetails2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(
        competition_id,
        announced_at=NOW + timedelta(seconds=1),
        **details_kwargs,
    )
    wca = FakeWca(recent_future=[summary], details={competition_id: details})
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()
        assert state.counts() == {"competitions": 1}

    assert mailer.sent == []
    assert stored_competition_status(config.state_path, competition_id) == expected_status


def test_each_recipient_only_receives_subscribed_events(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    config = replace(
        base_config,
        recipients=(
            replace(
                base_config.recipients[0],
                event_ids=frozenset({"333", "minx"}),
            ),
            replace(
                base_config.recipients[1],
                event_ids=frozenset({"pyram", "skewb"}),
            ),
        ),
    )
    competition_id = "ThreeByThreeOnly2026"
    summary = make_summary(
        competition_id,
        announced_at=NOW + timedelta(seconds=1),
        event_ids=["333"],
    )
    details = make_details(competition_id, event_ids=["333"])
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()
        assert state.counts() == {"competitions": 1, "deliveries_sent": 1}

    assert [delivery.recipient_email for delivery in mailer.sent] == ["one@example.com"]
    assert "命中的关注项目：三阶魔方 (333)" in mailer.sent[0].text_body


def test_filters_from_different_conditions_cannot_form_a_false_match(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    recipient = RecipientConfig.from_conditions(
        email="isolated@example.com",
        name="Isolated",
        conditions=(
            FollowCondition(
                event_ids=frozenset({"333"}),
                country_names=frozenset({"Japan"}),
            ),
            FollowCondition(
                event_ids=frozenset({"minx"}),
                country_names=frozenset({"China"}),
            ),
        ),
    )
    config = replace(base_config, recipients=(recipient,))
    competition_id = "NoCrossConditionMatch2026"
    summary = make_summary(
        competition_id,
        announced_at=NOW + timedelta(seconds=1),
        event_ids=["333"],
    )
    details = make_details(competition_id, event_ids=["333"], country_iso2="CN")
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

    assert mailer.sent == []


def test_any_complete_condition_matches_and_email_uses_first_matching_location(
    tmp_path: Path,
) -> None:
    base_config = make_config(tmp_path)
    recipient = RecipientConfig.from_conditions(
        email="or@example.com",
        name="OR",
        conditions=(
            FollowCondition(
                latitude=31.2304,
                longitude=121.4737,
                event_ids=frozenset({"minx"}),
            ),
            FollowCondition(
                latitude=39.9042,
                longitude=116.4074,
                max_distance_km=50,
                event_ids=frozenset({"333"}),
            ),
        ),
    )
    config = replace(base_config, recipients=(recipient,))
    competition_id = "SecondConditionMatch2026"
    summary = make_summary(
        competition_id,
        announced_at=NOW + timedelta(seconds=1),
        event_ids=["333"],
        latitude=39.9042,
        longitude=116.4074,
    )
    details = make_details(
        competition_id,
        event_ids=["333"],
        latitude=39.9042,
        longitude=116.4074,
    )
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

    assert [delivery.recipient_email for delivery in mailer.sent] == ["or@example.com"]
    assert "命中的关注项目：三阶魔方 (333)" in mailer.sent[0].text_body
    assert "直线（大圆）距离：0.0 km" in mailer.sent[0].text_body


def test_recipient_country_and_continent_filters_form_a_union(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    recipient = base_config.recipients[0]
    config = replace(
        base_config,
        recipients=(
            replace(recipient, email="all@example.com"),
            replace(recipient, email="country@example.com", country_names=frozenset({"China"})),
            replace(recipient, email="continent@example.com", continent_names=frozenset({"Asia"})),
            replace(
                recipient,
                email="union@example.com",
                country_names=frozenset({"United States"}),
                continent_names=frozenset({"Asia"}),
            ),
            replace(
                recipient,
                email="miss@example.com",
                country_names=frozenset({"Japan"}),
                continent_names=frozenset({"Europe"}),
            ),
        ),
    )
    competition_id = "ChinaCompetition2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id, country_iso2="CN")
    wca = FakeWca(
        recent_future=[summary],
        details={competition_id: details},
        countries={"CN": WcaCountry("China", "CN", "Asia")},
    )
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

    assert [delivery.recipient_email for delivery in mailer.sent] == [
        "all@example.com",
        "country@example.com",
        "continent@example.com",
        "union@example.com",
    ]
    assert wca.country_calls == ["CN"]


def test_recipient_distance_filter_only_queues_competitions_within_radius(
    tmp_path: Path,
) -> None:
    base_config = make_config(tmp_path)
    config = replace(
        base_config,
        recipients=tuple(
            replace(recipient, max_distance_km=100) for recipient in base_config.recipients
        ),
    )
    competition_id = "NearbyCompetition2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id, latitude=31.2304, longitude=121.4737)
    mailer = FakeMailer()

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

    assert [delivery.recipient_email for delivery in mailer.sent] == ["one@example.com"]


def test_no_matching_region_skips_coordinate_retry(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    config = replace(
        base_config,
        recipients=tuple(
            replace(recipient, country_names=frozenset({"Japan"}))
            for recipient in base_config.recipients
        ),
    )
    competition_id = "NoMatchingRegion2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id, latitude=None, longitude=None)
    wca = FakeWca(recent_future=[summary], details={competition_id: details})

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            wca,
            FakeMailer(),
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

        assert state.due_enrichments(NOW + timedelta(days=1)) == []
        assert stored_competition_status(config.state_path, competition_id) == (
            CompetitionStatus.QUEUED
        )


def test_country_catalog_failure_keeps_competition_pending(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    config = replace(
        base_config,
        recipients=tuple(
            replace(recipient, continent_names=frozenset({"Asia"}))
            for recipient in base_config.recipients
        ),
    )
    competition_id = "RegionRetry2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    wca = FakeWca(
        recent_future=[summary],
        details={competition_id: make_details(competition_id)},
        country_error=WcaApiError("temporary countries failure"),
    )
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(config, state, wca, FakeMailer(), clock=clock).run_once()
        assert state.due_enrichments(clock.current) == []
        assert len(state.due_enrichments(clock.current + timedelta(minutes=1))) == 1

    assert wca.country_calls == ["CN"]


def test_no_matching_recipient_skips_coordinate_retry(tmp_path: Path) -> None:
    base_config = make_config(tmp_path)
    config = replace(
        base_config,
        recipients=tuple(
            replace(recipient, event_ids=frozenset({"pyram"}))
            for recipient in base_config.recipients
        ),
    )
    competition_id = "NoSubscribers2026"
    summary = make_summary(
        competition_id,
        announced_at=NOW + timedelta(seconds=1),
        event_ids=["333"],
    )
    details = make_details(
        competition_id,
        event_ids=["333"],
        latitude=None,
        longitude=None,
    )

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            FakeMailer(),
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()

        assert state.due_enrichments(NOW + timedelta(days=1)) == []
        assert stored_competition_status(config.state_path, competition_id) == (
            CompetitionStatus.QUEUED
        )


def test_cancellation_during_coordinate_retry_prevents_delivery(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    competition_id = "CancelledWhileWaiting2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    wca = FakeWca(
        recent_future=[summary],
        details={competition_id: make_details(competition_id, latitude=None, longitude=None)},
    )
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        service = ReminderService(config, state, wca, mailer, clock=clock)
        service.run_once()
        wca.details[competition_id] = make_details(
            competition_id,
            cancelled_at="2026-07-16T03:00:00Z",
        )
        clock.current += timedelta(minutes=1)
        service.run_once()
        assert state.counts() == {"competitions": 1}

    assert mailer.sent == []
    assert (
        stored_competition_status(config.state_path, competition_id)
        == CompetitionStatus.IGNORED_CANCELLED
    )


def test_incremental_failure_does_not_advance_checkpoint(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    competition_id = "AfterRetry2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    wca = FakeWca(
        recent_future=[summary],
        details={competition_id: make_details(competition_id)},
        recent_error=WcaApiError("temporary index failure"),
    )
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        checkpoint = state.incremental_checkpoint_at()
        service = ReminderService(config, state, wca, mailer, clock=clock)
        assert not service.run_once()
        assert state.incremental_checkpoint_at() == checkpoint
        assert state.counts() == {"competitions": 0}

        wca.recent_error = None
        clock.current += timedelta(minutes=1)
        assert service.run_once()
        assert state.incremental_checkpoint_at() == clock.current

    assert len(mailer.sent) == 2


def test_failed_full_reconciliation_remains_due_and_recovers(tmp_path: Path) -> None:
    config = make_config(tmp_path, full_reconcile_hours=1)
    competition_id = "FullReconcileRecovery2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(minutes=1))
    wca = FakeWca(
        all_future=[summary],
        details={competition_id: make_details(competition_id)},
        all_error=WcaApiError("full index failure"),
    )
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(hours=2))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        service = ReminderService(config, state, wca, mailer, clock=clock)
        assert not service.run_once()
        assert state.incremental_checkpoint_at() == clock.current
        assert state.full_reconciliation_due(clock.current, timedelta(hours=1))

        wca.all_error = None
        assert service.run_once()
        assert not state.full_reconciliation_due(clock.current, timedelta(hours=1))
        assert state.counts() == {"competitions": 1, "deliveries_sent": 2}

    assert len(mailer.sent) == 2


def test_detail_failure_remains_pending_for_retry(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    new_summary = make_summary("RetryDetails2026", announced_at=NOW + timedelta(seconds=1))
    wca = FakeWca(
        recent_future=[new_summary],
        details={"RetryDetails2026": WcaApiError("temporary failure")},
    )
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(config, state, wca, FakeMailer(), clock=clock).run_once()
        assert len(state.due_enrichments(clock.current)) == 0
        clock.current += timedelta(minutes=1)
        assert len(state.due_enrichments(clock.current)) == 1


def test_coordinate_failure_degrades_after_deadline(tmp_path: Path) -> None:
    config = make_config(tmp_path, coordinate_retry_hours=24, full_reconcile_hours=168)
    new_summary = make_summary("NoCoordinates2026", announced_at=NOW + timedelta(seconds=1))
    details = make_details("NoCoordinates2026", latitude=None, longitude=None)
    wca = FakeWca(recent_future=[new_summary], details={"NoCoordinates2026": details})
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        service = ReminderService(config, state, wca, mailer, clock=clock)
        service.run_once()
        assert mailer.sent == []
        clock.current += timedelta(hours=24, minutes=1)
        service.run_once()
        assert state.counts()["deliveries_sent"] == 2

    assert all("直线（大圆）距离：-" in delivery.text_body for delivery in mailer.sent)


def test_missing_competition_coordinates_exclude_distance_filtered_recipient_after_deadline(
    tmp_path: Path,
) -> None:
    base_config = make_config(tmp_path, coordinate_retry_hours=1, full_reconcile_hours=168)
    config = replace(
        base_config,
        recipients=(
            replace(base_config.recipients[0], max_distance_km=100),
            base_config.recipients[1],
        ),
    )
    competition_id = "UnknownDistance2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id, latitude=None, longitude=None)
    mailer = FakeMailer()
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        service = ReminderService(
            config,
            state,
            FakeWca(recent_future=[summary], details={competition_id: details}),
            mailer,
            clock=clock,
        )
        service.run_once()
        assert mailer.sent == []
        clock.current += timedelta(hours=1, minutes=1)
        service.run_once()

    assert [delivery.recipient_email for delivery in mailer.sent] == ["two@example.com"]


def test_one_recipient_failure_does_not_block_the_next(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    new_summary = make_summary("PartialDelivery2026", announced_at=NOW + timedelta(seconds=1))
    details = make_details("PartialDelivery2026")
    wca = FakeWca(recent_future=[new_summary], details={"PartialDelivery2026": details})
    mailer = FakeMailer({"one@example.com": DeliverySendError("temporary", permanent=False)})

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()
        assert state.counts() == {
            "competitions": 1,
            "deliveries_pending": 1,
            "deliveries_sent": 1,
        }

    assert [delivery.recipient_email for delivery in mailer.sent] == ["two@example.com"]


def test_recipient_permanent_failure_is_blocked_without_stopping_run(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    competition_id = "RejectedRecipient2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id)
    wca = FakeWca(recent_future=[summary], details={competition_id: details})
    mailer = FakeMailer(
        {"one@example.com": DeliverySendError("recipient rejected", permanent=True)}
    )

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        assert ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
        ).run_once()
        assert state.counts() == {
            "competitions": 1,
            "deliveries_blocked": 1,
            "deliveries_sent": 1,
        }

    assert [delivery.recipient_email for delivery in mailer.sent] == ["two@example.com"]


def test_global_smtp_failure_remains_pending_and_stops_process(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    competition_id = "AuthenticationFailure2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id)
    wca = FakeWca(recent_future=[summary], details={competition_id: details})
    mailer = FakeMailer(
        {
            "one@example.com": DeliverySendError(
                "authentication failed",
                permanent=True,
                stop_run=True,
            )
        }
    )
    clock = MutableClock(NOW + timedelta(minutes=1))

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        service = ReminderService(config, state, wca, mailer, clock=clock)
        with pytest.raises(DeliverySendError, match="authentication failed"):
            service.run_once()

        assert state.counts() == {
            "competitions": 1,
            "deliveries_pending": 2,
        }
        retried = state.claim_delivery(clock.current, lease=timedelta(minutes=5))
        assert retried is not None
        assert retried.recipient_email == "one@example.com"


def test_shutdown_finishes_current_email_without_claiming_the_next(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    stop_event = Event()
    competition_id = "ShutdownDuringDelivery2026"
    summary = make_summary(competition_id, announced_at=NOW + timedelta(seconds=1))
    details = make_details(competition_id)
    wca = FakeWca(recent_future=[summary], details={competition_id: details})

    class StoppingMailer(FakeMailer):
        def send(self, delivery) -> None:
            super().send(delivery)
            stop_event.set()

    mailer = StoppingMailer()
    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        ReminderService(
            config,
            state,
            wca,
            mailer,
            clock=MutableClock(NOW + timedelta(minutes=1)),
            stop_requested=stop_event.is_set,
        ).run_once()
        assert state.counts() == {
            "competitions": 1,
            "deliveries_pending": 1,
            "deliveries_sent": 1,
        }

    assert [delivery.recipient_email for delivery in mailer.sent] == ["one@example.com"]


def test_expired_delivery_claim_cannot_be_completed_by_old_owner(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    summary = make_summary("Claim2026", announced_at=NOW + timedelta(seconds=1))
    details = make_details("Claim2026")
    drafts = build_delivery_drafts(
        details,
        config.recipients[:1],
        from_address=config.smtp.from_address,
        distance_available=True,
    )

    with StateStore(config.state_path) as state:
        state.initialize_baseline([], NOW)
        state.record_scan([summary], NOW + timedelta(seconds=2), full_reconciliation=False)
        state.queue_deliveries("Claim2026", details.raw_json, drafts, NOW + timedelta(seconds=3))
        old_claim = state.claim_delivery(NOW + timedelta(seconds=4), lease=timedelta(minutes=1))
        assert old_claim is not None
        new_claim = state.claim_delivery(NOW + timedelta(minutes=2), lease=timedelta(minutes=1))
        assert new_claim is not None
        with pytest.raises(StateError, match="no longer owned"):
            state.mark_delivery_sent(old_claim, NOW + timedelta(minutes=2))
        state.mark_delivery_sent(new_claim, NOW + timedelta(minutes=2))
        assert state.counts()["deliveries_sent"] == 1
