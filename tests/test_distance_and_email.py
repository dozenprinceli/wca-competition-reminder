from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.conftest import make_config, make_details
from wca_competition_reminder.config import RecipientConfig
from wca_competition_reminder.distance import haversine_km
from wca_competition_reminder.email_content import build_delivery_drafts
from wca_competition_reminder.email_templates import DEFAULT_EMAIL_TEMPLATES_PATH


def test_haversine_same_point_is_zero() -> None:
    assert haversine_km(0, 0, 0, 0) == 0


def test_haversine_shanghai_to_beijing() -> None:
    assert haversine_km(31.2304, 121.4737, 39.9042, 116.4074) == pytest.approx(1067.3, abs=1)


def test_haversine_handles_antipodal_points() -> None:
    assert haversine_km(0, 0, 0, 180) == pytest.approx(20015.1, abs=0.2)


def test_distance_filter_includes_exact_boundary_and_rejects_beyond_it() -> None:
    distance = haversine_km(31.2304, 121.4737, 39.9042, 116.4074)
    recipient = RecipientConfig(
        "one@example.com",
        31.2304,
        121.4737,
        max_distance_km=distance,
    )

    assert recipient.follows_distance(39.9042, 116.4074)
    assert not replace(recipient, max_distance_km=distance - 0.01).follows_distance(
        39.9042, 116.4074
    )
    assert not recipient.follows_distance(None, None)


def test_email_is_personalized_and_html_escaped(tmp_path) -> None:
    config = make_config(tmp_path)
    details = make_details("Safe2026")
    details = replace(
        details,
        venue="<Unsafe & venue>",
        announced_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    drafts = build_delivery_drafts(
        details,
        config.recipients,
        from_address=config.smtp.from_address,
        subscription_base_url=config.web_base_url,
        distance_available=True,
    )

    assert len(drafts) == 2
    assert "0.0 km" in drafts[0].text_body
    assert "1067" in drafts[1].text_body
    assert "三阶魔方 (333)、五魔方 (minx)" in drafts[0].text_body
    assert "&lt;Unsafe &amp; venue&gt;" in drafts[0].html_body
    assert (
        "修改订阅：https://reminder.test/subscriptions/?tab=modify&email=one%40example.com"
        in drafts[0].text_body
    )
    assert (
        'href="https://reminder.test/subscriptions/?tab=modify&amp;email=one%40example.com"'
        in drafts[0].html_body
    )
    assert (
        'href="https://reminder.test/subscriptions/?tab=cancel&amp;email=one%40example.com"'
        in drafts[0].html_body
    )
    assert drafts[0].message_id != drafts[1].message_id


def test_degraded_email_has_no_distance(tmp_path) -> None:
    config = make_config(tmp_path)
    details = make_details("NoCoordinates2026", latitude=None, longitude=None)

    draft = build_delivery_drafts(
        details,
        config.recipients[:1],
        from_address=config.smtp.from_address,
        subscription_base_url=config.web_base_url,
        distance_available=False,
    )[0]

    assert "直线（大圆）距离：-" in draft.text_body
    assert "暂不可用" in draft.text_body


def test_email_uses_dash_when_recipient_coordinates_are_empty(tmp_path) -> None:
    config = make_config(tmp_path)
    recipient = replace(config.recipients[0], latitude=None, longitude=None)

    draft = build_delivery_drafts(
        make_details("NoRecipientCoordinates2026"),
        (recipient,),
        from_address=config.smtp.from_address,
        subscription_base_url=config.web_base_url,
        distance_available=True,
    )[0]

    assert "比赛坐标：31.230400, 121.473700" in draft.text_body
    assert "直线（大圆）距离：-" in draft.text_body


def test_subscription_links_url_encode_plus_addressing(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    recipient = replace(config.recipients[0], email="one+alerts@example.com")

    draft = build_delivery_drafts(
        make_details("PlusAddress2026"),
        (recipient,),
        from_address=config.smtp.from_address,
        subscription_base_url=config.web_base_url,
        distance_available=True,
    )[0]

    assert "email=one%2Balerts%40example.com" in draft.text_body
    assert "email=one%2Balerts%40example.com" in draft.html_body


def test_email_templates_render_english_and_japanese_notifications(tmp_path) -> None:
    config = make_config(tmp_path)
    recipients = (
        replace(config.recipients[0], notification_language="en"),
        replace(config.recipients[1], notification_language="ja"),
    )

    drafts = build_delivery_drafts(
        make_details("Localized2026"),
        recipients,
        from_address=config.smtp.from_address,
        subscription_base_url=config.web_base_url,
        distance_available=True,
    )

    assert drafts[0].subject.startswith("[WCA competition alert]")
    assert "Matched events:" in drafts[0].text_body
    assert (
        "Edit subscription: https://reminder.test/subscriptions/?tab=modify"
        in drafts[0].text_body
    )
    assert '<html lang="en">' in drafts[0].html_body
    assert drafts[1].subject.startswith("[WCA 大会告知]")
    assert "一致した種目：" in drafts[1].text_body
    assert "登録を解除：https://reminder.test/subscriptions/?tab=cancel" in drafts[1].text_body
    assert '<html lang="ja">' in drafts[1].html_body


def test_email_templates_are_reloaded_from_the_config_path_on_each_call(tmp_path) -> None:
    config = make_config(tmp_path)
    recipient = replace(config.recipients[0], notification_language="en")
    template_path = tmp_path / "email_templates.toml"
    source = DEFAULT_EMAIL_TEMPLATES_PATH.read_text(encoding="utf-8")

    def rendered_subject(prefix: str) -> str:
        template_path.write_text(
            source.replace(
                "[WCA competition alert] {competition_name}",
                f"{prefix} {{competition_name}}",
            ),
            encoding="utf-8",
        )
        return build_delivery_drafts(
            make_details("Reloaded2026"),
            (recipient,),
            from_address=config.smtp.from_address,
            subscription_base_url=config.web_base_url,
            distance_available=True,
            templates_path=template_path,
        )[0].subject

    assert rendered_subject("FIRST") == "FIRST Competition Reloaded2026"
    assert rendered_subject("SECOND") == "SECOND Competition Reloaded2026"
