"""Bangumi API v0 enum definitions and ergonomic bidirectional parsers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

# SubjectType (note: Bangumi has no 5)
SUBJECT_TYPES: dict[int, str] = {
    1: "book",
    2: "anime",
    3: "music",
    4: "game",
    6: "real",
}
SUBJECT_TYPE_LABELS_ZH: dict[int, str] = {
    1: "书籍",
    2: "动画",
    3: "音乐",
    4: "游戏",
    6: "三次元",
}
_SUBJECT_TYPE_ALIASES: dict[str, int] = {
    "1": 1,
    "book": 1,
    "books": 1,
    "书籍": 1,
    "2": 2,
    "anime": 2,
    "动画": 2,
    "番剧": 2,
    "3": 3,
    "music": 3,
    "音乐": 3,
    "4": 4,
    "game": 4,
    "games": 4,
    "游戏": 4,
    "6": 6,
    "real": 6,
    "三次元": 6,
    "剧集": 6,
}

# SubjectCollectionType
COLLECTION_TYPES: dict[int, str] = {
    1: "wish",
    2: "collect",
    3: "doing",
    4: "on_hold",
    5: "dropped",
}
COLLECTION_TYPE_LABELS_ZH: dict[int, str] = {
    1: "想看",
    2: "看过",
    3: "在看",
    4: "搁置",
    5: "抛弃",
}
_COLLECTION_TYPE_ALIASES: dict[str, int] = {
    "1": 1,
    "wish": 1,
    "plan": 1,
    "想看": 1,
    "想读": 1,
    "想玩": 1,
    "想听": 1,
    "2": 2,
    "collect": 2,
    "done": 2,
    "watched": 2,
    "completed": 2,
    "看过": 2,
    "读过": 2,
    "玩过": 2,
    "听过": 2,
    "3": 3,
    "doing": 3,
    "watching": 3,
    "在看": 3,
    "在读": 3,
    "在玩": 3,
    "在听": 3,
    "4": 4,
    "on_hold": 4,
    "on-hold": 4,
    "onhold": 4,
    "hold": 4,
    "搁置": 4,
    "5": 5,
    "dropped": 5,
    "drop": 5,
    "抛弃": 5,
}

# EpType
EPISODE_TYPES: dict[int, str] = {
    0: "main",
    1: "sp",
    2: "op",
    3: "ed",
    4: "pv",
    5: "mad",
    6: "other",
}
_EPISODE_TYPE_ALIASES: dict[str, int] = {
    "0": 0,
    "main": 0,
    "mainstory": 0,
    "本篇": 0,
    "1": 1,
    "sp": 1,
    "special": 1,
    "特别篇": 1,
    "2": 2,
    "op": 2,
    "3": 3,
    "ed": 3,
    "4": 4,
    "pv": 4,
    "cm": 4,
    "预告": 4,
    "5": 5,
    "mad": 5,
    "6": 6,
    "other": 6,
    "其他": 6,
}

# EpisodeCollectionType
EPISODE_COLLECTION_TYPES: dict[int, str] = {
    0: "none",
    1: "wish",
    2: "done",
    3: "dropped",
}
EPISODE_COLLECTION_LABELS_ZH: dict[int, str] = {
    0: "未收藏",
    1: "想看",
    2: "看过",
    3: "抛弃",
}
_EPISODE_COLLECTION_ALIASES: dict[str, int] = {
    "0": 0,
    "none": 0,
    "remove": 0,
    "uncollect": 0,
    "未收藏": 0,
    "撤销": 0,
    "1": 1,
    "wish": 1,
    "想看": 1,
    "2": 2,
    "done": 2,
    "collect": 2,
    "watched": 2,
    "看过": 2,
    "3": 3,
    "dropped": 3,
    "drop": 3,
    "抛弃": 3,
}

CHARACTER_TYPES: dict[int, str] = {
    1: "character",
    2: "mechanic",
    3: "ship",
    4: "organization",
}

PERSON_TYPES: dict[int, str] = {
    1: "individual",
    2: "corporation",
    3: "association",
}

VALID_SUBJECT_SORTS = ("match", "heat", "rank", "score")
VALID_BROWSE_SORTS = ("date", "rank")
VALID_PERSON_CAREERS = (
    "producer",
    "mangaka",
    "artist",
    "seiyu",
    "writer",
    "illustrator",
    "actor",
)

_WEEKDAY_ALIASES: dict[str, int] = {
    "1": 1,
    "mon": 1,
    "monday": 1,
    "周一": 1,
    "星期一": 1,
    "月": 1,
    "2": 2,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "周二": 2,
    "星期二": 2,
    "火": 2,
    "3": 3,
    "wed": 3,
    "wednesday": 3,
    "周三": 3,
    "星期三": 3,
    "水": 3,
    "4": 4,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "周四": 4,
    "星期四": 4,
    "木": 4,
    "5": 5,
    "fri": 5,
    "friday": 5,
    "周五": 5,
    "星期五": 5,
    "金": 5,
    "6": 6,
    "sat": 6,
    "saturday": 6,
    "周六": 6,
    "星期六": 6,
    "土": 6,
    "7": 7,
    "sun": 7,
    "sunday": 7,
    "周日": 7,
    "周天": 7,
    "星期日": 7,
    "星期天": 7,
    "日": 7,
}


def parse_subject_type(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value in SUBJECT_TYPES:
            return value
        raise ValueError(
            f"Invalid subject_type {value!r}. Expected one of {sorted(SUBJECT_TYPES)} "
            f"({', '.join(SUBJECT_TYPES.values())})."
        )
    key = str(value).strip().lower()
    if key in _SUBJECT_TYPE_ALIASES:
        return _SUBJECT_TYPE_ALIASES[key]
    raise ValueError(
        f"Invalid subject_type {value!r}. Expected one of: book(1), anime(2), music(3), game(4), real(6)."
    )


def parse_subject_types(values: Iterable[int | str] | None) -> list[int] | None:
    if values is None:
        return None
    result: list[int] = []
    for item in values:
        parsed = parse_subject_type(item)
        if parsed not in result:
            result.append(parsed)
    return result


def parse_collection_type(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value in COLLECTION_TYPES:
            return value
        raise ValueError(
            f"Invalid collection_type {value!r}. Expected 1(wish), 2(collect), 3(doing), 4(on_hold), 5(dropped)."
        )
    key = str(value).strip().lower()
    if key in _COLLECTION_TYPE_ALIASES:
        return _COLLECTION_TYPE_ALIASES[key]
    raise ValueError(
        f"Invalid collection_type {value!r}. Expected one of: wish(1), collect(2), doing(3), on_hold(4), dropped(5)."
    )


def parse_episode_type(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value in EPISODE_TYPES:
            return value
        raise ValueError(
            f"Invalid episode type {value!r}. Expected 0(main), 1(sp), 2(op), 3(ed), 4(pv), 5(mad), 6(other)."
        )
    key = str(value).strip().lower()
    if key in _EPISODE_TYPE_ALIASES:
        return _EPISODE_TYPE_ALIASES[key]
    raise ValueError(
        f"Invalid episode type {value!r}. Expected one of: main(0), sp(1), op(2), ed(3), pv(4), mad(5), other(6)."
    )


def parse_episode_collection_type(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value in EPISODE_COLLECTION_TYPES:
            return value
        raise ValueError(
            f"Invalid episode status {value!r}. Expected 0(none), 1(wish), 2(done), 3(dropped)."
        )
    key = str(value).strip().lower()
    if key in _EPISODE_COLLECTION_ALIASES:
        return _EPISODE_COLLECTION_ALIASES[key]
    raise ValueError(
        f"Invalid episode status {value!r}. Expected one of: none(0), wish(1), done(2), dropped(3)."
    )


def parse_weekday(value: int | str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if 1 <= value <= 7:
            return value
        raise ValueError(f"Invalid weekday {value!r}. Expected 1 (Monday) through 7 (Sunday).")
    key = str(value).strip().lower()
    if key in ("today", "今天", "今日"):
        # Bangumi calendar follows UTC+8/UTC+9 East Asian schedule; use UTC+8 default
        tz_cn = timezone(timedelta(hours=8))
        return datetime.now(tz_cn).isoweekday()
    if key in _WEEKDAY_ALIASES:
        return _WEEKDAY_ALIASES[key]
    raise ValueError(
        f"Invalid weekday {value!r}. Expected 1-7, monday-sunday, 周一-周日, or 'today'."
    )
