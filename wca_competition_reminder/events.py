from collections.abc import Iterable

# WCA event IDs are stable API identifiers. Keep this in the official WCA display order.
OFFICIAL_EVENTS: tuple[tuple[str, str], ...] = (
    ("333", "三阶魔方"),
    ("222", "二阶魔方"),
    ("444", "四阶魔方"),
    ("555", "五阶魔方"),
    ("666", "六阶魔方"),
    ("777", "七阶魔方"),
    ("333bf", "三阶盲拧"),
    ("333fm", "三阶最少步"),
    ("333oh", "三阶单手"),
    ("clock", "魔表"),
    ("minx", "五魔方"),
    ("pyram", "金字塔魔方"),
    ("skewb", "斜转魔方"),
    ("sq1", "Square-1"),
    ("444bf", "四阶盲拧"),
    ("555bf", "五阶盲拧"),
    ("333mbf", "三阶多盲"),
)

OFFICIAL_EVENT_IDS = frozenset(event_id for event_id, _ in OFFICIAL_EVENTS)
OFFICIAL_EVENT_NAMES = dict(OFFICIAL_EVENTS)


def ordered_official_event_ids(event_ids: Iterable[str]) -> tuple[str, ...]:
    requested = set(event_ids)
    return tuple(event_id for event_id, _ in OFFICIAL_EVENTS if event_id in requested)


def format_event_ids(event_ids: Iterable[str]) -> str:
    return "、".join(
        f"{OFFICIAL_EVENT_NAMES[event_id]} ({event_id})"
        for event_id in ordered_official_event_ids(event_ids)
    )
