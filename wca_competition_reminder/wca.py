from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from wca_competition_reminder.config import WcaConfig
from wca_competition_reminder.models import CompetitionDetails, CompetitionSummary, WcaCountry


class WcaApiError(RuntimeError):
    pass


class _PaginationDriftError(WcaApiError):
    pass


def _required_string(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise WcaApiError(f"WCA response field {name!r} must be a non-empty string")
    return value.strip()


def _optional_string(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WcaApiError(f"WCA response field {name!r} must be a string")
    return value.strip()


def _date(document: dict[str, Any], name: str) -> date:
    value = _required_string(document, name)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WcaApiError(f"WCA response field {name!r} is not an ISO date") from exc


def _datetime(document: dict[str, Any], name: str, *, optional: bool = False) -> datetime | None:
    value = document.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise WcaApiError(f"WCA response field {name!r} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WcaApiError(f"WCA response field {name!r} is not an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise WcaApiError(f"WCA response field {name!r} lacks timezone information")
    return parsed.astimezone(UTC)


def _event_ids(document: dict[str, Any]) -> tuple[str, ...]:
    value = document.get("event_ids")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise WcaApiError("WCA response field 'event_ids' must be a string array")
    return tuple(value)


def _coordinate(document: dict[str, Any], name: str) -> float | None:
    value = document.get(name)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _raw_json(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def parse_countries(document: Any) -> dict[str, WcaCountry]:
    if not isinstance(document, list):
        raise WcaApiError("WCA countries response must be an array")

    countries: dict[str, WcaCountry] = {}
    for item in document:
        if not isinstance(item, dict):
            raise WcaApiError("WCA countries response item must be an object")
        name = _required_string(item, "name")
        iso2 = _required_string(item, "iso2")
        continent_id = _required_string(item, "continent_id")
        if not continent_id.startswith("_") or len(continent_id) == 1:
            raise WcaApiError("WCA country continent_id must start with '_'")
        if iso2 in countries:
            raise WcaApiError(f"WCA countries response contains duplicate ISO2 code: {iso2}")
        countries[iso2] = WcaCountry(
            name=name,
            iso2=iso2,
            continent_name=continent_id.removeprefix("_"),
        )
    return countries


def parse_competition_summary(document: dict[str, Any]) -> CompetitionSummary:
    announced_at = _datetime(document, "announced_at")
    assert announced_at is not None
    return CompetitionSummary(
        competition_id=_required_string(document, "id"),
        name=_required_string(document, "name"),
        start_date=_date(document, "start_date"),
        end_date=_date(document, "end_date"),
        announced_at=announced_at,
        event_ids=_event_ids(document),
        city=_optional_string(document, "city"),
        venue=_optional_string(document, "venue"),
        country_iso2=_optional_string(document, "country_iso2"),
        latitude=_coordinate(document, "latitude_degrees"),
        longitude=_coordinate(document, "longitude_degrees"),
        raw_json=_raw_json(document),
    )


def parse_competition_details(document: dict[str, Any]) -> CompetitionDetails:
    announced_at = _datetime(document, "announced_at")
    assert announced_at is not None
    competition_id = _required_string(document, "id")
    return CompetitionDetails(
        competition_id=competition_id,
        name=_required_string(document, "name"),
        start_date=_date(document, "start_date"),
        end_date=_date(document, "end_date"),
        announced_at=announced_at,
        event_ids=_event_ids(document),
        city=_optional_string(document, "city"),
        venue=_optional_string(document, "venue"),
        venue_address=_optional_string(document, "venue_address"),
        venue_details=_optional_string(document, "venue_details"),
        country_iso2=_optional_string(document, "country_iso2"),
        latitude=_coordinate(document, "latitude_degrees"),
        longitude=_coordinate(document, "longitude_degrees"),
        url=_optional_string(document, "url")
        or f"https://www.worldcubeassociation.org/competitions/{competition_id}",
        cancelled_at=_datetime(document, "cancelled_at", optional=True),
        raw_json=_raw_json(document),
    )


def summary_from_json(value: str) -> CompetitionSummary:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WcaApiError("stored competition summary is invalid JSON") from exc
    if not isinstance(document, dict):
        raise WcaApiError("stored competition summary must be an object")
    return parse_competition_summary(document)


class WcaClient:
    INDEX_PATH = "/api/v0/competition_index"
    COUNTRIES_PATH = "/api/v0/countries"

    def __init__(
        self,
        config: WcaConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self._config = config
        self._sleeper = sleeper
        self._clock = clock
        self._stop_requested = stop_requested
        self._countries_by_iso2: dict[str, WcaCountry] | None = None
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.read_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={"Accept": "application/json", "User-Agent": config.user_agent},
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WcaClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_all_future(self, current_date: date) -> list[CompetitionSummary]:
        return self._fetch_index(
            {
                "ongoing_and_future": current_date.isoformat(),
                "include_cancelled": "false",
                "sort": "start_date,end_date,name",
                "per_page": self._config.page_size,
                "page": 1,
            }
        )

    def fetch_recent_future(
        self,
        current_date: date,
        announced_after: date,
    ) -> list[CompetitionSummary]:
        return self._fetch_index(
            {
                "ongoing_and_future": current_date.isoformat(),
                "include_cancelled": "false",
                "announced_after": announced_after.isoformat(),
                "sort": "-announced_at,name",
                "per_page": self._config.page_size,
                "page": 1,
            }
        )

    def fetch_details(self, competition_id: str) -> CompetitionDetails:
        response = self._request(f"/api/v0/competitions/{quote(competition_id, safe='')}")
        document = self._json(response)
        if not isinstance(document, dict):
            raise WcaApiError("WCA competition detail response must be an object")
        details = parse_competition_details(document)
        if details.competition_id != competition_id:
            raise WcaApiError("WCA competition detail ID does not match the request")
        return details

    def fetch_country(self, country_iso2: str) -> WcaCountry:
        self.fetch_countries()
        try:
            assert self._countries_by_iso2 is not None
            return self._countries_by_iso2[country_iso2]
        except KeyError as exc:
            raise WcaApiError(
                f"WCA countries response does not contain ISO2 code: {country_iso2 or '<empty>'}"
            ) from exc

    def fetch_countries(self) -> dict[str, WcaCountry]:
        """Fetch and cache the WCA country/continent catalog for UI filters."""
        if self._countries_by_iso2 is None:
            response = self._request(self.COUNTRIES_PATH)
            self._countries_by_iso2 = parse_countries(self._json(response))
        return dict(self._countries_by_iso2)

    def _fetch_index(self, params: dict[str, object]) -> list[CompetitionSummary]:
        for scan_attempt in range(2):
            self._raise_if_stopping()
            try:
                return self._fetch_index_once(params)
            except _PaginationDriftError:
                if scan_attempt == 1:
                    raise
                self._sleeper(0.25)
                self._raise_if_stopping()
        raise AssertionError("unreachable")

    def _fetch_index_once(self, params: dict[str, object]) -> list[CompetitionSummary]:
        next_url: str | None = self.INDEX_PATH
        next_params: dict[str, object] | None = params
        visited_urls: set[str] = set()
        documents: list[dict[str, Any]] = []
        competition_ids: set[str] = set()
        expected_total: int | None = None
        pages = 0

        while next_url is not None:
            self._raise_if_stopping()
            pages += 1
            if pages > 1000:
                raise WcaApiError("WCA pagination exceeded 1000 pages")

            response = self._request(next_url, params=next_params)
            next_params = None
            current_url = str(response.request.url)
            if current_url in visited_urls:
                raise WcaApiError("WCA pagination repeated a page URL")
            visited_urls.add(current_url)

            total_header = response.headers.get("total")
            try:
                page_total = int(total_header) if total_header is not None else -1
            except ValueError as exc:
                raise WcaApiError("WCA pagination returned an invalid total header") from exc
            if page_total < 0:
                raise WcaApiError("WCA pagination did not return a total header")
            if expected_total is None:
                expected_total = page_total
            elif page_total != expected_total:
                raise _PaginationDriftError("WCA pagination total changed during the scan")

            page_document = self._json(response)
            if not isinstance(page_document, list):
                raise WcaApiError("WCA competition index response must be an array")
            for item in page_document:
                if not isinstance(item, dict):
                    raise WcaApiError("WCA competition index item must be an object")
                competition_id = _required_string(item, "id")
                if competition_id in competition_ids:
                    raise _PaginationDriftError(
                        "WCA pagination returned a duplicate competition ID"
                    )
                competition_ids.add(competition_id)
                documents.append(item)

            link = response.links.get("next")
            if link is None:
                next_url = None
            else:
                linked_url = link.get("url")
                if not isinstance(linked_url, str):
                    raise WcaApiError("WCA next-page link is invalid")
                self._validate_next_url(linked_url)
                next_url = linked_url

        if expected_total is None or len(documents) != expected_total:
            raise _PaginationDriftError(
                "WCA pagination ended before the advertised number of competitions was fetched"
            )
        return [parse_competition_summary(document) for document in documents]

    def _validate_next_url(self, value: str) -> None:
        linked = httpx.URL(value)
        base = httpx.URL(self._config.base_url)
        if (
            linked.scheme != base.scheme
            or linked.host != base.host
            or linked.port != base.port
            or linked.path != self.INDEX_PATH
        ):
            raise WcaApiError("WCA next-page link points outside the competition index")

    def _request(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._config.request_attempts + 1):
            self._raise_if_stopping()
            try:
                response = self._client.get(url, params=params)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self._config.request_attempts:
                    self._sleeper(float(2 ** (attempt - 1)))
                    self._raise_if_stopping()
                    continue
                break

            if response.status_code == 200:
                self._raise_if_stopping()
                return response
            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                last_error = WcaApiError(f"WCA returned HTTP {response.status_code}")
                if attempt < self._config.request_attempts:
                    retry_after = response.headers.get("retry-after")
                    delay = self._retry_delay(retry_after, default=2 ** (attempt - 1))
                    self._sleeper(float(delay))
                    self._raise_if_stopping()
                    continue
                break
            request_id = response.headers.get("x-request-id", "unknown")
            raise WcaApiError(f"WCA returned HTTP {response.status_code} (request ID {request_id})")

        raise WcaApiError(f"WCA request failed after retries: {last_error}") from last_error

    def _raise_if_stopping(self) -> None:
        if self._stop_requested():
            raise WcaApiError("WCA request cancelled during shutdown")

    def _retry_delay(self, value: str | None, *, default: float) -> float:
        if value is None:
            return default
        try:
            delay = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return default
            if retry_at.tzinfo is None:
                return default
            delay = (retry_at.astimezone(UTC) - self._clock().astimezone(UTC)).total_seconds()
        if not math.isfinite(delay):
            return default
        return min(max(delay, 0.0), 60.0)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WcaApiError("WCA returned invalid JSON") from exc
