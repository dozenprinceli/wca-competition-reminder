from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from email.headerregistry import Address
from typing import Any

from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.events import OFFICIAL_EVENT_IDS
from wca_competition_reminder.models import SubscriberRecord
from wca_competition_reminder.state import StateStore
from wca_competition_reminder.utils import utc_now


class SubscriptionError(ValueError):
    """Base class for errors that can be shown to a subscription user."""


class SubscriptionValidationError(SubscriptionError):
    pass


class SubscriptionConflictError(SubscriptionError):
    pass


class SubscriptionNotFoundError(SubscriptionError):
    pass


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    email: str
    name: str | None
    latitude: float | None
    longitude: float | None
    max_distance_km: float | None
    events: tuple[str, ...] | None
    countries: tuple[str, ...] | None
    continents: tuple[str, ...] | None
    active: bool
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None

    @classmethod
    def from_record(cls, record: SubscriberRecord) -> SubscriptionView:
        return cls(
            email=record.email,
            name=record.name,
            latitude=record.latitude,
            longitude=record.longitude,
            max_distance_km=record.max_distance_km,
            events=tuple(sorted(record.event_ids)) if record.event_ids is not None else None,
            countries=(
                tuple(sorted(record.country_names)) if record.country_names is not None else None
            ),
            continents=(
                tuple(sorted(record.continent_names))
                if record.continent_names is not None
                else None
            ),
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            cancelled_at=record.cancelled_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "max_distance_km": self.max_distance_km,
            "events": list(self.events) if self.events is not None else None,
            "countries": list(self.countries) if self.countries is not None else None,
            "continents": list(self.continents) if self.continents is not None else None,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
        }


def recipient_from_record(record: SubscriberRecord) -> RecipientConfig:
    return RecipientConfig(
        email=record.email,
        latitude=record.latitude,
        longitude=record.longitude,
        name=record.name,
        event_ids=record.event_ids,
        country_names=record.country_names,
        continent_names=record.continent_names,
        max_distance_km=record.max_distance_km,
    )


def normalize_email(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SubscriptionValidationError("请输入有效的邮箱地址")
    normalized = value.strip().lower()
    try:
        address = Address(addr_spec=normalized)
    except (TypeError, ValueError) as exc:
        raise SubscriptionValidationError("请输入有效的邮箱地址") from exc
    if not address.username or not address.domain or address.addr_spec != normalized:
        raise SubscriptionValidationError("请输入有效的邮箱地址")
    return normalized


def _coordinate(value: object, field_name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubscriptionValidationError(f"{field_name} 必须是数字")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise SubscriptionValidationError(f"{field_name} 超出有效范围")
    return number


def _name(value: object) -> str:
    if not isinstance(value, str):
        raise SubscriptionValidationError("称呼必须是文本")
    name = value.strip()
    if not name:
        raise SubscriptionValidationError("请输入称呼")
    if len(name) > 120:
        raise SubscriptionValidationError("称呼不能超过 120 个字符")
    return name


def _coordinates(payload: dict[str, object]) -> tuple[float | None, float | None]:
    latitude_value = payload.get("latitude")
    longitude_value = payload.get("longitude")
    latitude_missing = latitude_value is None or latitude_value == ""
    longitude_missing = longitude_value is None or longitude_value == ""
    if latitude_missing and longitude_missing:
        return None, None
    if latitude_missing or longitude_missing:
        raise SubscriptionValidationError("纬度和经度需要同时填写或同时留空")
    return (
        _coordinate(latitude_value, "纬度", -90, 90),
        _coordinate(longitude_value, "经度", -180, 180),
    )


def _max_distance_km(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubscriptionValidationError("最远距离必须是数字")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise SubscriptionValidationError("最远距离必须大于 0 公里")
    return number


def _values(value: object, field_name: str, *, event_ids: bool = False) -> frozenset[str] | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = list(value)
    else:
        raise SubscriptionValidationError(f"{field_name} 必须是字符串数组")
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise SubscriptionValidationError(f"{field_name} 只能包含非空字符串")
    normalized = {item.strip() for item in items}
    if event_ids:
        normalized = {item.lower() for item in normalized}
        unknown = sorted(normalized - OFFICIAL_EVENT_IDS)
        if unknown:
            raise SubscriptionValidationError(f"包含未知 WCA 项目：{', '.join(unknown)}")
    return frozenset(normalized) or None


def _regions(value: object, field_name: str) -> frozenset[str] | None:
    # A single string is kept intact because country names such as "Hong Kong, China"
    # legitimately contain commas. The browser sends arrays for multiple values.
    if isinstance(value, str) and value.strip():
        values = frozenset({value.strip()})
    else:
        values = _values(value, field_name)
    return values


def _recipient(payload: object, *, email: str | None = None) -> RecipientConfig:
    if not isinstance(payload, dict):
        raise SubscriptionValidationError("请求内容必须是 JSON 对象")
    supplied_email = payload.get("email")
    normalized_email = normalize_email(email if email is not None else supplied_email)
    if (
        email is not None
        and supplied_email is not None
        and normalize_email(supplied_email) != email
    ):
        raise SubscriptionValidationError("邮箱地址不能在修改时变更")
    latitude, longitude = _coordinates(payload)
    max_distance_km = _max_distance_km(payload.get("max_distance_km"))
    if max_distance_km is not None and latitude is None:
        raise SubscriptionValidationError("设置最远距离时必须同时填写纬度和经度")
    return RecipientConfig(
        email=normalized_email,
        latitude=latitude,
        longitude=longitude,
        name=_name(payload.get("name")),
        event_ids=_values(payload.get("events"), "events", event_ids=True),
        country_names=_regions(payload.get("countries"), "countries"),
        continent_names=_regions(payload.get("continents"), "continents"),
        max_distance_km=max_distance_km,
    )


class SubscriptionService:
    def __init__(self, state: StateStore, *, clock=utc_now) -> None:
        self._state = state
        self._clock = clock

    def register(self, payload: object) -> SubscriptionView:
        if not isinstance(payload, dict):
            raise SubscriptionValidationError("请求内容必须是 JSON 对象")
        if payload.get("notification_consent") is not True:
            raise SubscriptionValidationError("注册前请同意接收 WCA 比赛通知邮件")
        recipient = _recipient(payload)
        if not self._state.register_subscriber(recipient, self._clock()):
            raise SubscriptionConflictError("该邮箱已经订阅，请使用修改或取消操作")
        record = self._state.find_subscriber(recipient.email)
        if record is None:
            raise SubscriptionError("订阅保存失败")
        return SubscriptionView.from_record(record)

    def update(self, payload: object) -> SubscriptionView:
        if not isinstance(payload, dict):
            raise SubscriptionValidationError("请求内容必须是 JSON 对象")
        email = normalize_email(payload.get("email"))
        recipient = _recipient(payload, email=email)
        if not self._state.update_subscriber(recipient, self._clock()):
            raise SubscriptionNotFoundError("该邮箱尚未注册")
        record = self._state.find_subscriber(email)
        if record is None:
            raise SubscriptionNotFoundError("订阅不存在")
        return SubscriptionView.from_record(record)

    def cancel(self, payload: object) -> SubscriptionView:
        if not isinstance(payload, dict):
            raise SubscriptionValidationError("请求内容必须是 JSON 对象")
        email = normalize_email(payload.get("email"))
        if not self._state.cancel_subscriber(email, self._clock()):
            raise SubscriptionNotFoundError("该邮箱尚未注册")
        record = self._state.find_subscriber(email)
        if record is None:
            raise SubscriptionNotFoundError("订阅不存在")
        return SubscriptionView.from_record(record)

    def get(self, payload: object) -> SubscriptionView:
        if not isinstance(payload, dict):
            raise SubscriptionValidationError("请求内容必须是 JSON 对象")
        email = normalize_email(payload.get("email"))
        record = self._state.find_subscriber(email)
        if record is None or not record.active:
            raise SubscriptionNotFoundError("该邮箱尚未注册")
        return SubscriptionView.from_record(record)
