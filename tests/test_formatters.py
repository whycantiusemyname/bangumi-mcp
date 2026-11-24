"""Unit tests for constants parsers and LLM-friendly formatters."""

from __future__ import annotations

import pytest

from bangumi_mcp.constants import (
    parse_collection_type,
    parse_episode_collection_type,
    parse_episode_type,
    parse_subject_type,
    parse_subject_types,
    parse_weekday,
)
from bangumi_mcp.formatters import (
    format_calendar,
    format_subject_detail,
    format_subject_summary,
    format_user_collection,
    format_user_episode,
)


def test_parsers_accept_ints_en_and_zh() -> None:
    assert parse_subject_type("anime") == 2
    assert parse_subject_type("动画") == 2
    assert parse_subject_type(6) == 6
    assert parse_subject_types(["anime", 1, "anime", "游戏"]) == [2, 1, 4]

    assert parse_collection_type("wish") == 1
    assert parse_collection_type("看过") == 2
    assert parse_collection_type("watching") == 3
    assert parse_collection_type("on-hold") == 4
    assert parse_collection_type(5) == 5

    assert parse_episode_type("main") == 0
    assert parse_episode_type("特别篇") == 1
    assert parse_episode_collection_type("done") == 2
    assert parse_episode_collection_type("未收藏") == 0

    assert parse_weekday("monday") == 1
    assert parse_weekday("周日") == 7
    assert 1 <= parse_weekday("today") <= 7


def test_parsers_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        parse_subject_type(5)  # Bangumi has no type 5
    with pytest.raises(ValueError):
        parse_collection_type("unknown")
    with pytest.raises(ValueError):
        parse_episode_type(99)
    with pytest.raises(ValueError):
        parse_episode_collection_type(9)
    with pytest.raises(ValueError):
        parse_weekday(8)


def test_format_subject_detail_dehydrates_noise() -> None:
    raw = {
        "id": 400602,
        "type": 2,
        "name": "葬送のフリーレン",
        "name_cn": "葬送的芙莉莲",
        "date": "2023-09-29",
        "platform": "TV",
        "summary": "A   long   summary\nwith   extra   spaces",
        "total_episodes": 28,
        "rating": {"score": 8.6, "rank": 15, "total": 25000, "count": {"10": 5000, "1": 10}},
        "collection": {"wish": 3000, "collect": 20000, "doing": 4000, "on_hold": 500, "dropped": 200},
        "images": {"large": "https://img/l.jpg", "common": "https://img/c.jpg", "grid": "https://img/g.jpg"},
        "meta_tags": ["漫改", "奇幻", "治愈"],
        "tags": [{"name": "MADHOUSE", "count": 4000}, {"name": "奇幻", "count": 3800}],
        "infobox": [
            {"key": "中文名", "value": "葬送的芙莉莲"},
            {"key": "别名", "value": [{"v": "Frieren"}, {"k": "英文名", "v": "Frieren: Beyond Journey's End"}]},
        ],
    }
    detail = format_subject_detail(raw)
    assert detail["type"] == "anime"
    assert detail["type_zh"] == "动画"
    assert detail["rating"] == {"score": 8.6, "rank": 15, "votes": 25000}
    assert "count" not in detail["rating"]
    assert detail["image"] == "https://img/c.jpg"
    assert detail["infobox"]["中文名"] == "葬送的芙莉莲"
    assert "英文名: Frieren: Beyond Journey's End" in detail["infobox"]["别名"]
    assert detail["summary"] == "A long summary with extra spaces"
    assert detail["url"] == "https://bgm.tv/subject/400602"

    summary = format_subject_summary(raw, max_summary_len=15)
    assert summary["summary"].endswith("…")
    assert summary["tags"] == ["MADHOUSE", "奇幻"]


def test_format_calendar_and_collections() -> None:
    cal_raw = [
        {
            "weekday": {"id": 1, "en": "Mon", "cn": "星期一"},
            "items": [{"id": 100, "name": "Test A", "name_cn": "测试A", "rating": {"score": 7.5}}],
        },
        {
            "weekday": {"id": 5, "en": "Fri", "cn": "星期五"},
            "items": [{"id": 200, "name": "Test B", "name_cn": "测试B", "rating": {"score": 8.2}}],
        },
    ]
    filtered = format_calendar(cal_raw, weekday_filter=5)
    assert len(filtered) == 1
    assert filtered[0]["weekday_id"] == 5
    assert filtered[0]["items"][0]["id"] == 200

    coll = format_user_collection(
        {
            "subject_id": 100,
            "subject_type": 2,
            "type": 2,
            "rate": 9,
            "ep_status": 12,
            "comment": "Great!",
            "tags": ["神作"],
            "subject": {"name": "Test A", "name_cn": "测试A", "score": 8.1, "rank": 50},
        }
    )
    assert coll["status"] == "collect"
    assert coll["status_zh"] == "看过"
    assert coll["rate"] == 9

    ep = format_user_episode(
        {
            "type": 2,
            "updated_at": 1700000000,
            "episode": {"id": 55, "type": 0, "ep": 1, "sort": 1, "name": "Ep1", "name_cn": "第1话"},
        }
    )
    assert ep["watch_status"] == "done"
    assert ep["watch_status_zh"] == "看过"
