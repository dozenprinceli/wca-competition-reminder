import hashlib
import html
from urllib.parse import urlsplit

from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.distance import coordinates_are_valid, haversine_km
from wca_competition_reminder.events import format_event_ids, ordered_official_event_ids
from wca_competition_reminder.models import CompetitionDetails, DeliveryDraft


def _date_range(details: CompetitionDetails) -> str:
    if details.start_date == details.end_date:
        return details.start_date.isoformat()
    return f"{details.start_date.isoformat()} 至 {details.end_date.isoformat()}"


def _message_id(competition_id: str, recipient_email: str, from_address: str) -> str:
    digest = hashlib.sha256(f"{competition_id}\0{recipient_email}".encode()).hexdigest()[:32]
    domain = urlsplit(f"mailto:{from_address}").path.rpartition("@")[2]
    domain = domain or "wca-reminder.local"
    return f"<wca-{digest}@{domain}>"


def _html_row(label: str, value: str, *, strong: bool = False) -> str:
    escaped_value = html.escape(value)
    if strong:
        escaped_value = f"<strong>{escaped_value}</strong>"
    return f'    <tr><th align="left">{label}</th><td>{escaped_value}</td></tr>'


def build_delivery_drafts(
    details: CompetitionDetails,
    recipients: tuple[RecipientConfig, ...],
    *,
    from_address: str,
    distance_available: bool,
) -> list[DeliveryDraft]:
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
        matched_events_text = format_event_ids(matched_event_ids)
        greeting = f"{recipient.name}，你好：" if recipient.name else "你好："
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
            coordinate_text = "暂不可用"
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

        subject = f"[WCA 比赛提醒] {details.name}"
        lines = [
            greeting,
            "",
            "WCA 新公示了一场包含你所关注项目的比赛。",
            "",
            f"比赛：{details.name}",
            f"命中的关注项目：{matched_events_text}",
            f"日期：{_date_range(details)}",
            f"城市：{details.city or '未提供'} ({details.country_iso2 or '未知国家/地区'})",
            f"场馆：{details.venue or '未提供'}",
            f"地址：{details.venue_address or '未提供'}",
            f"比赛坐标：{coordinate_text}",
            f"与你配置位置的直线（大圆）距离：{distance_text}",
            f"WCA 公示时间：{details.announced_at.isoformat()}",
            f"比赛详情：{details.url}",
        ]
        if details.venue_details:
            lines.extend(("", f"场地说明：{details.venue_details}"))
        text_body = "\n".join(lines)

        escaped_url = html.escape(details.url, quote=True)
        city = f"{details.city or '未提供'} ({details.country_iso2 or '未知国家/地区'})"
        rows = "\n".join(
            (
                _html_row("比赛", details.name),
                _html_row("命中的关注项目", matched_events_text, strong=True),
                _html_row("日期", _date_range(details)),
                _html_row("城市", city),
                _html_row("场馆", details.venue or "未提供"),
                _html_row("地址", details.venue_address or "未提供"),
                _html_row("比赛坐标", coordinate_text),
                _html_row("直线（大圆）距离", distance_text, strong=True),
                _html_row("WCA 公示时间", details.announced_at.isoformat()),
            )
        )
        venue_details_html = ""
        if details.venue_details:
            venue_details_html = (
                f"<p><strong>场地说明：</strong>{html.escape(details.venue_details)}</p>"
            )
        html_body = f"""\
<!doctype html>
<html lang="zh-CN">
<body>
  <p>{html.escape(greeting)}</p>
  <p>WCA 新公示了一场包含你所关注项目的比赛。</p>
  <table cellpadding="6" cellspacing="0" border="0">
{rows}
  </table>
  <p><a href="{escaped_url}">查看 WCA 比赛详情</a></p>
  {venue_details_html}
</body>
</html>
"""
        drafts.append(
            DeliveryDraft(
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                recipient_latitude=recipient.latitude,
                recipient_longitude=recipient.longitude,
                message_id=_message_id(details.competition_id, recipient.email, from_address),
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        )
    return drafts
