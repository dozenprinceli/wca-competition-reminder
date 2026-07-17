from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from tests.conftest import details_document, summary_document
from wca_competition_reminder.config import WcaConfig
from wca_competition_reminder.models import WcaCountry
from wca_competition_reminder.wca import WcaApiError, WcaClient


def client_config() -> WcaConfig:
    return WcaConfig(
        base_url="https://wca.test",
        user_agent="tests/1.0",
        page_size=25,
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        request_attempts=1,
        overlap_days=2,
    )


def test_index_follows_next_link_and_checks_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "1":
            assert dict(request.url.params) == {
                "ongoing_and_future": "2026-07-16",
                "include_cancelled": "false",
                "sort": "start_date,end_date,name",
                "per_page": "25",
                "page": "1",
            }
            return httpx.Response(
                200,
                json=[summary_document("First2026")],
                headers={
                    "total": "2",
                    "per-page": "1",
                    "link": (
                        "<https://wca.test/api/v0/competition_index?"
                        "ongoing_and_future=2026-07-16&include_cancelled=false&"
                        'sort=start_date%2Cend_date%2Cname&per_page=25&page=2>; rel="next"'
                    ),
                },
            )
        assert dict(request.url.params) == {
            "ongoing_and_future": "2026-07-16",
            "include_cancelled": "false",
            "sort": "start_date,end_date,name",
            "per_page": "25",
            "page": "2",
        }
        return httpx.Response(
            200,
            json=[summary_document("Second2026")],
            headers={"total": "2", "per-page": "1"},
        )

    with WcaClient(client_config(), transport=httpx.MockTransport(handler)) as client:
        summaries = client.fetch_all_future(date(2026, 7, 16))

    assert [item.competition_id for item in summaries] == ["First2026", "Second2026"]


def test_incremental_index_sends_announcement_cutoff() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {
            "ongoing_and_future": "2026-07-16",
            "include_cancelled": "false",
            "announced_after": "2026-07-14",
            "sort": "-announced_at,name",
            "per_page": "25",
            "page": "1",
        }
        return httpx.Response(200, json=[], headers={"total": "0"})

    with WcaClient(client_config(), transport=httpx.MockTransport(handler)) as client:
        summaries = client.fetch_recent_future(date(2026, 7, 16), date(2026, 7, 14))

    assert summaries == []


def test_index_restarts_once_after_pagination_drift() -> None:
    request_count = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                json=[summary_document("First2026")],
                headers={
                    "total": "2",
                    "link": '<https://wca.test/api/v0/competition_index?page=2>; rel="next"',
                },
            )
        competition_id = "First2026" if request_count == 2 else "Second2026"
        return httpx.Response(
            200,
            json=[summary_document(competition_id)],
            headers={"total": "2"},
        )

    with WcaClient(
        client_config(),
        transport=httpx.MockTransport(handler),
        sleeper=delays.append,
    ) as client:
        summaries = client.fetch_all_future(date(2026, 7, 16))

    assert [item.competition_id for item in summaries] == ["First2026", "Second2026"]
    assert request_count == 4
    assert delays == [0.25]


def test_index_rejects_duplicate_id_across_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"total": "2", "per-page": "1"}
        if request.url.params.get("page") == "1":
            headers["link"] = '<https://wca.test/api/v0/competition_index?page=2>; rel="next"'
        return httpx.Response(200, json=[summary_document("Duplicate2026")], headers=headers)

    with (
        WcaClient(client_config(), transport=httpx.MockTransport(handler)) as client,
        pytest.raises(WcaApiError, match="duplicate"),
    ):
        client.fetch_all_future(date(2026, 7, 16))


def test_index_rejects_cross_host_next_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[summary_document("First2026")],
            headers={
                "total": "2",
                "per-page": "1",
                "link": '<https://evil.test/steal?page=2>; rel="next"',
            },
        )

    with (
        WcaClient(client_config(), transport=httpx.MockTransport(handler)) as client,
        pytest.raises(WcaApiError, match="outside"),
    ):
        client.fetch_all_future(date(2026, 7, 16))


def test_detail_id_must_match_request() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=details_document("Other2026"))
    )
    with (
        WcaClient(client_config(), transport=transport) as client,
        pytest.raises(WcaApiError, match="does not match"),
    ):
        client.fetch_details("Expected2026")


def test_country_catalog_preserves_names_and_is_cached() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.path == "/api/v0/countries"
        return httpx.Response(
            200,
            json=[
                {
                    "name": "Hong Kong, China",
                    "iso2": "HK",
                    "continent_id": "_Asia",
                },
                {
                    "name": "Côte d'Ivoire",
                    "iso2": "CI",
                    "continent_id": "_Africa",
                },
            ],
        )

    with WcaClient(client_config(), transport=httpx.MockTransport(handler)) as client:
        assert client.fetch_country("HK") == WcaCountry("Hong Kong, China", "HK", "Asia")
        assert client.fetch_country("CI") == WcaCountry("Côte d'Ivoire", "CI", "Africa")

    assert request_count == 1


def test_country_catalog_rejects_unknown_competition_country() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[{"name": "China", "iso2": "CN", "continent_id": "_Asia"}],
        )
    )
    with (
        WcaClient(client_config(), transport=transport) as client,
        pytest.raises(WcaApiError, match="does not contain ISO2 code: ZZ"),
    ):
        client.fetch_country("ZZ")


def test_retry_after_http_date_is_clamped() -> None:
    now = datetime(2026, 7, 16, 2, 0, tzinfo=UTC)
    delays: list[float] = []
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                429,
                headers={"retry-after": format_datetime(now + timedelta(seconds=90), usegmt=True)},
            )
        return httpx.Response(200, json=details_document("Retry2026"))

    with WcaClient(
        replace(client_config(), request_attempts=2),
        transport=httpx.MockTransport(handler),
        sleeper=delays.append,
        clock=lambda: now,
    ) as client:
        details = client.fetch_details("Retry2026")

    assert details.competition_id == "Retry2026"
    assert delays == [60.0]


def test_shutdown_interrupts_retry_wait_before_another_request() -> None:
    stopping = False
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        return httpx.Response(503)

    def request_stop(delay: float) -> None:
        nonlocal stopping
        assert delay == 1.0
        stopping = True

    with (
        WcaClient(
            replace(client_config(), request_attempts=3),
            transport=httpx.MockTransport(handler),
            sleeper=request_stop,
            stop_requested=lambda: stopping,
        ) as client,
        pytest.raises(WcaApiError, match="cancelled during shutdown"),
    ):
        client.fetch_details("CancelledRetry2026")

    assert request_count == 1


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [
        ("-5", 0.0),
        ("NaN", 1.0),
        ("Thu, 16 Jul 2026 01:59:00 GMT", 0.0),
    ],
)
def test_retry_after_invalid_or_past_values_are_safe(
    retry_after: str,
    expected_delay: float,
) -> None:
    now = datetime(2026, 7, 16, 2, 0, tzinfo=UTC)
    delays: list[float] = []
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        if request_count == 1:
            return httpx.Response(429, headers={"retry-after": retry_after})
        return httpx.Response(200, json=details_document("RetryValue2026"))

    with WcaClient(
        replace(client_config(), request_attempts=2),
        transport=httpx.MockTransport(handler),
        sleeper=delays.append,
        clock=lambda: now,
    ) as client:
        client.fetch_details("RetryValue2026")

    assert delays == [expected_delay]
