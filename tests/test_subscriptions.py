from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode

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
from wca_competition_reminder import web
from wca_competition_reminder.models import DeliveryDraft, WcaCountry
from wca_competition_reminder.service import ReminderService
from wca_competition_reminder.state import StateStore
from wca_competition_reminder.subscriptions import (
    SubscriptionNotFoundError,
    SubscriptionService,
    SubscriptionValidationError,
)


def subscription_payload(email: str = "new@example.com") -> dict[str, object]:
    return {
        "email": email,
        "name": "New competitor",
        "notification_consent": True,
        "latitude": 31.2304,
        "longitude": 121.4737,
        "events": ["333", "minx"],
        "countries": ["China", "Hong Kong, China"],
        "continents": ["Asia"],
    }


def test_subscription_register_query_update_and_cancel(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        view = service.register(subscription_payload())

        assert view.email == "new@example.com"
        assert view.max_distance_km is None
        assert view.events == ("333", "minx")
        assert service.get({"email": "NEW@example.com"}) == view
        assert state.subscriber_count() == 1

        updated = service.update(
            {
                **subscription_payload(),
                "name": "Updated competitor",
                "max_distance_km": 250,
                "events": [],
                "countries": [],
                "continents": [],
            }
        )
        assert updated.name == "Updated competitor"
        assert updated.max_distance_km == 250
        assert updated.events is None
        assert updated.countries is None

        cancelled = service.cancel({"email": view.email})
        assert not cancelled.active
        assert state.subscriber_count() == 0

        with pytest.raises(SubscriptionNotFoundError):
            service.update(subscription_payload())


def test_subscription_notification_language_is_saved_and_preserved_on_omission(
    tmp_path: Path,
) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        view = service.register({**subscription_payload(), "notification_language": "ja-JP"})
        assert view.notification_language == "ja"
        assert view.to_dict()["notification_language"] == "ja"

        updated = service.update(
            {
                "email": view.email,
                "name": "Updated language",
                "conditions": [{}],
            }
        )
        assert updated.notification_language == "ja"

        changed = service.update(
            {
                "email": view.email,
                "name": "English language",
                "notification_language": "en",
                "conditions": [{}],
            }
        )
        assert changed.notification_language == "en"


def test_invalid_subscription_notification_language_is_rejected(tmp_path: Path) -> None:
    with (
        StateStore(tmp_path / "state.sqlite3") as state,
        pytest.raises(SubscriptionValidationError, match="邮件通知语言"),
    ):
        SubscriptionService(state, clock=lambda: NOW).register(
            {**subscription_payload(), "notification_language": "fr"}
        )


def test_subscription_persists_up_to_ten_ordered_conditions(tmp_path: Path) -> None:
    conditions = [
        {
            "latitude": 31.2304,
            "longitude": 121.4737,
            "max_distance_km": 300,
            "events": ["333"],
            "countries": ["China"],
            "continents": [],
        },
        {
            "latitude": 39.9042,
            "longitude": 116.4074,
            "max_distance_km": 120,
            "events": ["minx"],
            "countries": [],
            "continents": ["Asia"],
        },
    ]
    payload = {
        "email": "conditions@example.com",
        "name": "Condition owner",
        "notification_consent": True,
        "conditions": conditions,
    }

    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        view = service.register(payload)

        assert len(view.conditions) == 2
        assert view.conditions[0].event_ids == frozenset({"333"})
        assert view.conditions[1].event_ids == frozenset({"minx"})
        serialized_conditions = view.to_dict()["conditions"]
        assert serialized_conditions[0] == {**conditions[0], "continents": None}
        assert serialized_conditions[1] == {**conditions[1], "countries": None}

        updated = service.update(
            {
                **payload,
                "conditions": [*conditions, *({} for _index in range(8))],
            }
        )
        assert len(updated.conditions) == 10
        assert [condition.event_ids for condition in updated.conditions[:2]] == [
            frozenset({"333"}),
            frozenset({"minx"}),
        ]

        with sqlite3.connect(tmp_path / "state.sqlite3") as connection:
            positions = [
                int(row[0])
                for row in connection.execute(
                    """
                    SELECT position FROM subscriber_conditions
                    WHERE subscriber_email = ? ORDER BY position
                    """,
                    ("conditions@example.com",),
                ).fetchall()
            ]
        assert positions == list(range(10))


def test_subscription_condition_count_and_per_condition_validation(tmp_path: Path) -> None:
    base = {
        "email": "conditions@example.com",
        "name": "Condition owner",
        "notification_consent": True,
    }
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        with pytest.raises(SubscriptionValidationError, match="conditions"):
            service.register({**base, "conditions": None})
        with pytest.raises(SubscriptionValidationError, match="1 至 10"):
            service.register({**base, "conditions": []})
        with pytest.raises(SubscriptionValidationError, match="最多只能配置 10"):
            service.register({**base, "conditions": [{} for _index in range(11)]})
        with pytest.raises(SubscriptionValidationError, match=r"关注条件 2.*经度"):
            service.register(
                {
                    **base,
                    "conditions": [{}, {"max_distance_km": 100}],
                }
            )


def test_active_subscription_overwrites_a_cancelled_email(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        service.register(subscription_payload())
        service.cancel({"email": "new@example.com"})

        view = service.register({**subscription_payload(), "name": "Registered again"})
        assert view.active
        assert view.name == "Registered again"
        assert state.subscriber_count() == 1


def test_invalid_subscription_payloads_are_rejected(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        with pytest.raises(SubscriptionValidationError, match="未知 WCA"):
            service.register({**subscription_payload(), "events": ["unknown"]})
        with pytest.raises(SubscriptionValidationError, match="纬度"):
            service.register({**subscription_payload(), "latitude": 91})
        with pytest.raises(SubscriptionValidationError, match="同时填写"):
            service.register({**subscription_payload(), "latitude": None})
        with pytest.raises(SubscriptionValidationError, match="称呼"):
            service.register({**subscription_payload(), "name": ""})
        with pytest.raises(SubscriptionValidationError, match="大于 0"):
            service.register({**subscription_payload(), "max_distance_km": 0})
        with pytest.raises(SubscriptionValidationError, match="经度"):
            service.register(
                {
                    **subscription_payload(),
                    "latitude": None,
                    "longitude": None,
                    "max_distance_km": 100,
                }
            )


def test_subscription_registration_requires_notification_consent(tmp_path: Path) -> None:
    payload = subscription_payload()
    payload.pop("notification_consent")
    with (
        StateStore(tmp_path / "state.sqlite3") as state,
        pytest.raises(SubscriptionValidationError, match="同意接收"),
    ):
        SubscriptionService(state, clock=lambda: NOW).register(payload)


def test_cancel_blocks_pending_delivery_for_the_email(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        service = SubscriptionService(state, clock=lambda: NOW)
        view = service.register(subscription_payload())
        state.initialize_baseline([], NOW)
        state.record_scan(
            [make_summary("QueuedForCancel2026", announced_at=NOW + timedelta(seconds=1))],
            NOW + timedelta(seconds=2),
            full_reconciliation=False,
        )
        state.queue_deliveries(
            "QueuedForCancel2026",
            make_summary("QueuedForCancel2026").raw_json,
            [
                DeliveryDraft(
                    recipient_email=view.email,
                    recipient_name=view.name,
                    recipient_latitude=view.latitude,
                    recipient_longitude=view.longitude,
                    message_id="message-id",
                    subject="subject",
                    text_body="text",
                    html_body="<p>html</p>",
                )
            ],
            NOW,
        )

        service.cancel({"email": view.email})
        assert state.claim_delivery(NOW, lease=timedelta(minutes=5)) is None
        assert state.counts() == {"competitions": 1, "deliveries_blocked": 1}


def test_dynamic_subscription_without_coordinates_is_used_by_poller(tmp_path: Path) -> None:
    config = replace(make_config(tmp_path), recipients=())
    summary = make_summary("DynamicSubscriber2026", announced_at=NOW + timedelta(seconds=1))
    details = make_details("DynamicSubscriber2026")
    clock = MutableClock()
    mailer = FakeMailer()
    with StateStore(config.state_path) as state:
        SubscriptionService(state, clock=lambda: NOW).register(
            {**subscription_payload(), "latitude": None, "longitude": None}
        )
        wca = FakeWca(recent_future=[summary], details={summary.competition_id: details})
        reminder = ReminderService(config, state, wca, mailer, clock=clock)
        assert reminder.run_once()
        assert reminder.run_once()

    assert [delivery.recipient_email for delivery in mailer.sent] == ["new@example.com"]
    assert "直线（大圆）距离：-" in mailer.sent[0].text_body


def test_options_payload_uses_wca_country_catalog(tmp_path: Path, monkeypatch) -> None:
    config = make_config(tmp_path)

    class FakeWca:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def fetch_countries(self):
            return {
                "CN": WcaCountry("China", "CN", "Asia"),
                "FR": WcaCountry("France", "FR", "Europe"),
            }

    monkeypatch.setattr(web, "WcaClient", lambda _config: FakeWca())
    server = web.create_server(config, port=0)
    try:
        payload = server.options_payload()
        assert payload["continents"] == ["Asia", "Europe"]
        assert [country["name"] for country in payload["countries"]] == ["China", "France"]
    finally:
        server.server_close()


def _request_json(
    connection: HTTPConnection,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[HTTPResponse, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = json.loads(response.read().decode("utf-8"))
    return response, result


def _start_test_server(tmp_path: Path, clock: MutableClock):
    sent_codes: list[tuple[str, str, datetime]] = []
    config = make_config(tmp_path)
    server = web.create_server(
        config,
        port=0,
        verification_sender=lambda email, code, now: sent_codes.append((email, code, now)),
        verification_code_factory=lambda: "123456",
        clock=clock,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, sent_codes


def test_verification_sender_receives_selected_notification_language(tmp_path: Path) -> None:
    clock = MutableClock()
    sent_languages: list[str] = []

    def sender(_email: str, _code: str, _created_at: datetime, language: str) -> None:
        sent_languages.append(language)

    config = make_config(tmp_path)
    server = web.create_server(
        config,
        port=0,
        verification_sender=sender,
        verification_code_factory=lambda: "123456",
        clock=clock,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, _ = _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "language@example.com", "notification_language": "ja"},
        )
        assert response.status == 200
        assert sent_languages == ["ja"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_verification_and_subscription_endpoints(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger=web.__name__)
    clock = MutableClock()
    server, thread, sent_codes = _start_test_server(tmp_path, clock)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, body = _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "new@example.com"},
        )
        assert response.status == 200
        assert body["expires_in_seconds"] == 300
        assert sent_codes == [("new@example.com", "123456", NOW)]

        response, body = _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "new@example.com"},
        )
        assert response.status == 429
        assert response.getheader("Retry-After") == "50"
        assert body["retry_after_seconds"] == 50

        clock.current += timedelta(seconds=50)
        response, _ = _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "new@example.com"},
        )
        assert response.status == 200
        assert len(sent_codes) == 2

        response, body = _request_json(
            connection,
            "POST",
            "/api/subscriptions",
            {
                **subscription_payload(),
                "verification_code": "123456",
                "notification_consent": False,
            },
        )
        assert response.status == 400
        assert "同意接收" in str(body["message"])

        register_payload = {
            "email": "new@example.com",
            "name": "New competitor",
            "notification_consent": True,
            "verification_code": "123456",
            "conditions": [
                {
                    "latitude": 31.2304,
                    "longitude": 121.4737,
                    "max_distance_km": 300,
                    "events": ["333", "minx"],
                    "countries": ["China", "Hong Kong, China"],
                    "continents": ["Asia"],
                },
                {"events": ["pyram"]},
            ],
        }
        response, body = _request_json(
            connection,
            "POST",
            "/api/subscriptions",
            register_payload,
        )
        assert response.status == 201
        assert body["subscription"]["email"] == "new@example.com"
        assert body["subscription"]["max_distance_km"] == 300
        assert len(body["subscription"]["conditions"]) == 2
        assert "management_token" not in body

        response, body = _request_json(
            connection,
            "GET",
            f"/api/subscriptions?{urlencode({'email': 'new@example.com'})}",
        )
        assert response.status == 200
        assert body["subscription"]["name"] == "New competitor"

        update = {
            "email": "new@example.com",
            "name": "HTTP updated",
            "conditions": [{}],
        }
        response, body = _request_json(connection, "PUT", "/api/subscriptions", update)
        assert response.status == 200
        assert body["subscription"]["name"] == "HTTP updated"
        assert body["subscription"]["latitude"] is None
        assert body["subscription"]["max_distance_km"] is None
        assert len(body["subscription"]["conditions"]) == 1

        response, body = _request_json(
            connection,
            "DELETE",
            "/api/subscriptions",
            {"email": "new@example.com"},
        )
        assert response.status == 200
        assert not body["subscription"]["active"]

        response, _ = _request_json(
            connection,
            "GET",
            f"/api/subscriptions?{urlencode({'email': 'new@example.com'})}",
        )
        assert response.status == 404

        with StateStore(server.settings.config.state_path) as state:
            activity = state.activity_logs(
                now=clock.current,
                actor_type="user",
                limit=50,
            )
        actions = {(item["action"], item["outcome"]) for item in activity["items"]}
        assert {
            ("verification_code_request", "success"),
            ("verification_code_request", "rate_limited"),
            ("subscription_register", "rejected"),
            ("subscription_register", "success"),
            ("subscription_lookup", "success"),
            ("subscription_lookup", "not_found"),
            ("subscription_update", "success"),
            ("subscription_cancel", "success"),
        } <= actions
        register_log = next(
            item
            for item in activity["items"]
            if item["action"] == "subscription_register" and item["outcome"] == "success"
        )
        assert register_log["email"] == "new@example.com"
        assert register_log["method"] == "POST"
        assert register_log["path"] == "/api/subscriptions"
        assert register_log["details"]["subscription"]["max_distance_km"] == 300
        serialized_activity = json.dumps(activity, ensure_ascii=False)
        assert "123456" not in serialized_activity
        assert all("verification_code" not in item["details"] for item in activity["items"])

        assert "audit action=verification_code_request outcome=success" in caplog.text
        assert "audit action=subscription_register outcome=success" in caplog.text
        assert "audit action=subscription_lookup outcome=success" in caplog.text
        assert "audit action=subscription_update outcome=success" in caplog.text
        assert "audit action=subscription_cancel outcome=success" in caplog.text
        assert "new@example.com" not in caplog.text
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_verification_code_expires_after_five_minutes(tmp_path: Path) -> None:
    clock = MutableClock()
    server, thread, _ = _start_test_server(tmp_path, clock)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, _ = _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "new@example.com"},
        )
        assert response.status == 200
        clock.current += timedelta(minutes=5)

        response, body = _request_json(
            connection,
            "POST",
            "/api/subscriptions",
            {**subscription_payload(), "verification_code": "123456"},
        )
        assert response.status == 400
        assert "已过期" in str(body["message"])
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_verification_code_is_consumed_after_registration(tmp_path: Path) -> None:
    clock = MutableClock()
    server, thread, _ = _start_test_server(tmp_path, clock)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        _request_json(
            connection,
            "POST",
            "/api/verification-codes",
            {"email": "new@example.com"},
        )
        response, _ = _request_json(
            connection,
            "POST",
            "/api/subscriptions",
            {**subscription_payload(), "verification_code": "123456"},
        )
        assert response.status == 201

        response, body = _request_json(
            connection,
            "POST",
            "/api/subscriptions",
            {
                **subscription_payload("other@example.com"),
                "email": "new@example.com",
                "verification_code": "123456",
            },
        )
        assert response.status == 400
        assert "无效或已过期" in str(body["message"])
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
