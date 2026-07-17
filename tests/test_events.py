from wca_competition_reminder.events import (
    OFFICIAL_EVENT_IDS,
    OFFICIAL_EVENTS,
    format_event_ids,
)


def test_official_event_catalog_contains_all_17_wca_events() -> None:
    assert len(OFFICIAL_EVENTS) == 17
    assert {
        "222",
        "333",
        "444",
        "555",
        "666",
        "777",
        "333bf",
        "333fm",
        "333mbf",
        "333oh",
        "444bf",
        "555bf",
        "clock",
        "minx",
        "pyram",
        "skewb",
        "sq1",
    } == OFFICIAL_EVENT_IDS


def test_event_names_are_formatted_in_wca_order() -> None:
    assert format_event_ids(["minx", "333"]) == "三阶魔方 (333)、五魔方 (minx)"
