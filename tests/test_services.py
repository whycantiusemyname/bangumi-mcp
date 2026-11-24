"""Unit tests for full collection sync, caching, and batch deduplication."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from bangumi_mcp.client import BangumiClient
from bangumi_mcp.config import BangumiConfig
from bangumi_mcp.services import (
    CollectionLibraryCache,
    check_user_collections,
    normalize_title,
    sync_user_collections,
)


def _mock_library_transport() -> tuple[httpx.MockTransport, dict[str, int]]:
    call_counts = {"collections": 0, "search": 0}

    anime_items = [
        {
            "subject_id": 328609,
            "subject_type": 2,
            "type": 2,  # collect
            "rate": 9,
            "ep_status": 12,
            "tags": ["乐队", "搞笑"],
            "comment": "波奇酱太棒了",
            "subject": {
                "id": 328609,
                "name": "ぼっち・ざ・ろっく！",
                "name_cn": "孤独摇滚！",
                "score": 8.4,
                "rank": 40,
                "eps": 12,
            },
        },
        {
            "subject_id": 400602,
            "subject_type": 2,
            "type": 3,  # doing
            "rate": 8,
            "ep_status": 14,
            "subject": {
                "id": 400602,
                "name": "葬送のフリーレン",
                "name_cn": "葬送的芙莉莲",
                "score": 8.6,
                "rank": 15,
                "eps": 28,
            },
        },
        {
            "subject_id": 10380,
            "subject_type": 2,
            "type": 2,  # collect
            "rate": 10,
            "ep_status": 24,
            "subject": {
                "id": 10380,
                "name": "STEINS;GATE",
                "name_cn": "命运石之门",
                "score": 8.8,
                "rank": 5,
                "eps": 24,
            },
        },
    ]
    game_items = [
        {
            "subject_id": 123456,
            "subject_type": 4,
            "type": 5,  # dropped
            "rate": 4,
            "subject": {
                "id": 123456,
                "name": "Some Dropped Game",
                "name_cn": "某弃坑游戏",
                "score": 6.2,
            },
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v0/users/alice":
            return httpx.Response(200, json={"id": 10, "username": "alice", "nickname": "Alice"})

        if path == "/v0/users/alice/collections":
            call_counts["collections"] += 1
            st = int(request.url.params.get("subject_type", "2"))
            limit = int(request.url.params.get("limit", "50"))
            offset = int(request.url.params.get("offset", "0"))
            source = anime_items if st == 2 else (game_items if st == 4 else [])
            batch = source[offset : offset + limit]
            return httpx.Response(
                200,
                json={"total": len(source), "limit": limit, "offset": offset, "data": batch},
            )

        if path == "/v0/users/alice/collections/-/characters":
            return httpx.Response(
                200,
                json={"total": 1, "limit": 50, "offset": 0, "data": [{"id": 1, "name": "Hitori Gotoh", "type": 1}]},
            )
        if path == "/v0/users/alice/collections/-/persons":
            return httpx.Response(
                200,
                json={"total": 1, "limit": 50, "offset": 0, "data": [{"id": 2, "name": "Keiichiro Saito", "type": 1}]},
            )

        if path == "/v0/search/subjects" and request.method == "POST":
            call_counts["search"] += 1
            body = json.loads(request.content.decode("utf-8"))
            kw = body.get("keyword", "")
            if "Bocchi" in kw:
                return httpx.Response(
                    200,
                    json={
                        "total": 1,
                        "data": [{"id": 328609, "type": 2, "name": "ぼっち・ざ・ろっく！", "name_cn": "孤独摇滚！"}],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "data": [
                        {
                            "id": 999001,
                            "type": 2,
                            "name": "Orb: On the Movements of the Earth",
                            "name_cn": "地。-关于地球的运动-",
                            "rating": {"score": 8.1, "rank": 120},
                        }
                    ],
                },
            )

        return httpx.Response(404, json={"title": "Not Found"})

    return httpx.MockTransport(handler), call_counts


def test_normalize_title() -> None:
    assert normalize_title("STEINS;GATE") == normalize_title("steins gate")
    assert normalize_title("孤独摇滚！") == normalize_title("孤独摇滚")
    assert normalize_title("「葬送のフリーレン」") == "葬送のフリーレン"


@pytest.mark.asyncio
async def test_sync_user_collections_pagination_stats_and_export(tmp_path: Path) -> None:
    transport, counts = _mock_library_transport()
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0)
    out_file = tmp_path / "export.json"

    async with BangumiClient(cfg, transport=transport) as client:
        # Force page_size=2 to verify multi-page pagination on anime (3 items -> 2 pages)
        payload = await sync_user_collections(
            client,
            "alice",
            include_favorites=True,
            page_size=2,
            output_path=out_file,
        )

    assert payload["total_collections"] == 4
    assert payload["overall_by_status"] == {"collect": 2, "doing": 1, "dropped": 1}
    assert payload["summary_by_type"]["anime"]["fetched"] == 3
    assert payload["summary_by_type"]["game"]["by_status"] == {"dropped": 1}
    assert len(payload["favorite_characters"]) == 1
    assert len(payload["favorite_persons"]) == 1
    assert out_file.exists()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["total_collections"] == 4
    # 5 subject types, anime takes 2 pages -> 6 total collection requests
    assert counts["collections"] == 6


@pytest.mark.asyncio
async def test_check_user_collections_dedup_and_caching() -> None:
    transport, counts = _mock_library_transport()
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0)
    cache = CollectionLibraryCache(ttl_seconds=300.0)

    candidates: list[int | str] = [
        10380,  # subject_id match -> collect
        "400602",  # numeric string subject_id match -> doing
        "孤独摇滚",  # exact normalized CN title match (ignores "！") -> collect
        "steins gate",  # exact normalized EN/JP title match -> collect
        "葬送のフリー",  # fuzzy substring match -> doing
        "Bocchi the Rock!",  # not in local titles -> resolved via search to 328609 -> collect!
        "关于地球的运动",  # truly uncollected -> search returns candidate 999001
        999999,  # uncollected subject_id
    ]

    async with BangumiClient(cfg, transport=transport) as client:
        report = await check_user_collections(
            client,
            "alice",
            candidates,
            cache=cache,
        )
        # Second call should reuse cache (no additional collection requests)
        first_coll_calls = counts["collections"]
        report2 = await check_user_collections(
            client,
            "alice",
            [10380],
            cache=cache,
        )
        assert counts["collections"] == first_coll_calls
        assert report2["collected_count"] == 1

    assert report["library_total"] == 4
    assert report["checked_count"] == 8
    assert report["collected_count"] == 6
    assert report["uncollected_count"] == 2
    assert report["uncollected_items"] == ["关于地球的运动", 999999]

    by_query: dict[Any, dict[str, Any]] = {r["query"]: r for r in report["results"]}
    assert by_query[10380]["status"] == "collect"
    assert by_query[10380]["matched_by"] == "subject_id"
    assert by_query["400602"]["status"] == "doing"
    assert by_query["孤独摇滚"]["matched_by"] == "exact_title"
    assert by_query["steins gate"]["matched_by"] == "exact_title"
    assert by_query["葬送のフリー"]["matched_by"] == "fuzzy_title"
    assert by_query["Bocchi the Rock!"]["matched_by"] == "search_resolved"
    assert by_query["Bocchi the Rock!"]["subject_id"] == 328609
    assert by_query["关于地球的运动"]["collected"] is False
    assert by_query["关于地球的运动"]["status_zh"] == "未收藏"
    assert by_query["关于地球的运动"]["resolved_candidate"]["id"] == 999001
