from __future__ import annotations

import hashlib
import html
from pathlib import Path
from urllib.parse import urlsplit

from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.distance import coordinates_are_valid, haversine_km
from wca_competition_reminder.email_templates import (
    DEFAULT_EMAIL_TEMPLATES_PATH,
    EmailTemplateCatalog,
    load_email_templates,
)
from wca_competition_reminder.events import OFFICIAL_EVENTS, ordered_official_event_ids
from wca_competition_reminder.models import CompetitionDetails, DeliveryDraft

_EVENT_NAMES = {
    "zh": dict(OFFICIAL_EVENTS),
    "en": {
        "333": "3x3 Cube",
        "222": "2x2 Cube",
        "444": "4x4 Cube",
        "555": "5x5 Cube",
        "666": "6x6 Cube",
        "777": "7x7 Cube",
        "333bf": "3x3 Blindfolded",
        "333fm": "3x3 Fewest Moves",
        "333oh": "3x3 One-Handed",
        "clock": "Clock",
        "minx": "Megaminx",
        "pyram": "Pyraminx",
        "skewb": "Skewb",
        "sq1": "Square-1",
        "444bf": "4x4 Blindfolded",
        "555bf": "5x5 Blindfolded",
        "333mbf": "3x3 Multi-Blind",
    },
    "ja": {
        "333": "3x3キューブ",
        "222": "2x2キューブ",
        "444": "4x4キューブ",
        "555": "5x5キューブ",
        "666": "6x6キューブ",
        "777": "7x7キューブ",
        "333bf": "3x3目隠し",
        "333fm": "3x3最少手数",
        "333oh": "3x3片手",
        "clock": "クロック",
        "minx": "メガミンクス",
        "pyram": "ピラミンクス",
        "skewb": "スキューブ",
        "sq1": "スクエア1",
        "444bf": "4x4目隠し",
        "555bf": "5x5目隠し",
        "333mbf": "3x3マルチブラインド",
    },
}

_TEXT_FALLBACKS = {
    "zh": {"unknown": "未提供", "unknown_country": "未知国家/地区", "unavailable": "暂不可用"},
    "en": {
        "unknown": "Not provided",
        "unknown_country": "Unknown country/region",
        "unavailable": "Temporarily unavailable",
    },
    "ja": {"unknown": "未提供", "unknown_country": "不明な国・地域", "unavailable": "一時利用不可"},
}


def _date_range(details: CompetitionDetails, language: str = "zh") -> str:
    if details.start_date == details.end_date:
        return details.start_date.isoformat()
    separator = {"zh": " 至 ", "ja": "～"}.get(language, " - ")
    return f"{details.start_date.isoformat()}{separator}{details.end_date.isoformat()}"


def _message_id(competition_id: str, recipient_email: str, from_address: str) -> str:
    digest = hashlib.sha256(f"{competition_id}\0{recipient_email}".encode()).hexdigest()[:32]
    domain = urlsplit(f"mailto:{from_address}").path.rpartition("@")[2]
    domain = domain or "wca-reminder.local"
    return f"<wca-{digest}@{domain}>"


def _format_event_ids(event_ids: tuple[str, ...], language: str) -> str:
    names = _EVENT_NAMES.get(language, _EVENT_NAMES["zh"])
    separator = ", " if language == "en" else "、"
    return separator.join(f"{names.get(event_id, event_id)} ({event_id})" for event_id in event_ids)


def _escape_values(values: dict[str, str]) -> dict[str, str]:
    return {key: html.escape(value, quote=True) for key, value in values.items()}


def build_delivery_drafts(
    details: CompetitionDetails,
    recipients: tuple[RecipientConfig, ...],
    *,
    from_address: str,
    distance_available: bool,
    template_catalog: EmailTemplateCatalog | None = None,
    templates_path: Path | None = None,
) -> list[DeliveryDraft]:
    """Render one localized delivery draft for every matching recipient."""

    catalog = template_catalog or load_email_templates(
        templates_path or DEFAULT_EMAIL_TEMPLATES_PATH
    )
    drafts: list[DeliveryDraft] = []
    competition_event_ids = ordered_official_event_ids(details.event_ids)
    for recipient in recipients:
        matched_event_ids = (
            competition_event_ids
            if recipient.event_ids is None
            else ordered_official_event_ids(recipient.event_ids.intersection(competition_event_ids))
        )
        if not matched_event_ids:
            continue

        language = recipient.notification_language
        language_fallbacks = _TEXT_FALLBACKS.get(language, _TEXT_FALLBACKS["zh"])
        matched_events = _format_event_ids(matched_event_ids, language)
        greeting = (
            {
                "zh": f"{recipient.name}，你好：",
                "en": f"Hello {recipient.name},",
                "ja": f"{recipient.name}さん、こんにちは。",
            }.get(language, f"{recipient.name},")
            if recipient.name
            else {"zh": "你好：", "en": "Hello,", "ja": "こんにちは。"}.get(language, "Hello,")
        )

        competition_coordinates_available = distance_available and coordinates_are_valid(
            details.latitude, details.longitude
        )
        recipient_coordinates_available = coordinates_are_valid(
            recipient.latitude, recipient.longitude
        )
        if competition_coordinates_available:
            assert details.latitude is not None and details.longitude is not None
            coordinate_text = f"{details.latitude:.6f}, {details.longitude:.6f}"
        else:
            coordinate_text = language_fallbacks["unavailable"]
        if competition_coordinates_available and recipient_coordinates_available:
            assert recipient.latitude is not None and recipient.longitude is not None
            distance = haversine_km(
                recipient.latitude,
                recipient.longitude,
                details.latitude,
                details.longitude,
            )
            distance_text = f"{distance:.1f} km"
        else:
            distance_text = "-"

        city_name = details.city or language_fallbacks["unknown"]
        country_name = details.country_iso2 or language_fallbacks["unknown_country"]
        city = f"{city_name} ({country_name})"
        venue = details.venue or language_fallbacks["unknown"]
        venue_address = details.venue_address or language_fallbacks["unknown"]
        venue_label = {"zh": "场地说明", "en": "Venue details", "ja": "会場説明"}.get(
            language, "Venue details"
        )
        venue_details_line = (
            f"\n{venue_label}{':' if language == 'en' else '：'}"
            f"{details.venue_details}"
            if details.venue_details
            else ""
        )
        venue_details_html = ""
        if details.venue_details:
            venue_details_html = (
                f"<p><strong>{html.escape(venue_label)}"
                f"{':' if language == 'en' else '：'}</strong>"
                f"{html.escape(details.venue_details)}</p>"
            )

        values = {
            "greeting": greeting,
            "competition_name": details.name,
            "matched_events": matched_events,
            "date_range": _date_range(details, language),
            "city": city,
            "venue": venue,
            "venue_address": venue_address,
            "competition_coordinates": coordinate_text,
            "distance": distance_text,
            "announced_at": details.announced_at.isoformat(),
            "competition_url": details.url,
            "venue_details_line": venue_details_line,
            "venue_details_html": venue_details_html,
        }
        html_values = _escape_values(values)
        # This value is already a deliberately constructed, escaped HTML fragment.
        html_values["venue_details_html"] = venue_details_html
        rendered = catalog.render_notification(
            language,
            subject_values=values,
            text_values=values,
            html_values=html_values,
        )
        drafts.append(
            DeliveryDraft(
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                recipient_latitude=recipient.latitude,
                recipient_longitude=recipient.longitude,
                message_id=_message_id(details.competition_id, recipient.email, from_address),
                subject=rendered.subject,
                text_body=rendered.text_body,
                html_body=rendered.html_body,
            )
        )
    return drafts
