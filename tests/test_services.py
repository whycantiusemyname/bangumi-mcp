"""Unit tests for full collection sync, pagination resilience, caching, and batch deduplication."""

from __future__ import annotations

import asyncio
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


def _mock_library_transport(
    *,
    short_first_page: bool = False,
    fail_search: bool = False,
) -> tuple[httpx.MockTransport, dict[str, int]]:
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
    book_items = [
        {
            "subject_id": 304567,
            "subject_type": 1,
            "type": 1,  # wish (same title as anime 400602!)
            "subject": {
                "id": 304567,
                "name": "葬送のフリーレン",
                "name_cn": "葬送的芙莉莲",
                "score": 8.3,
            },
        }
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
            source = anime_items if st == 2 else (book_items if st == 1 else (game_items if st == 4 else []))
            batch = source[offset : offset + limit]
            total = len(source)
            if short_first_page and st == 2:
                # Simulate upstream filtering out 1 deleted subject on page 0 while total is 4
                total = 4
                if offset == 0:
                    batch = anime_items[:1]  # short page (1 < limit=2)
                elif offset == 2:
                    batch = anime_items[1:3]
                else:
                    batch = []
            return httpx.Response(
                200,
                json={"total": total, "limit": limit, "offset": offset, "data": batch},
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
            if fail_search:
                return httpx.Response(500, json={"title": "Internal Error"})
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
            if "第二季" in kw:
                # Top hit is uncollected Season 2 (500002); second hit is collected Season 1 (400602).
                # Must resolve canonical #1 (500002 -> uncollected), NOT pick #2!
                return httpx.Response(
                    200,
                    json={
                        "total": 2,
                        "data": [
                            {"id": 500002, "type": 2, "name": "葬送のフリーレン 第2期", "name_cn": "葬送的芙莉莲 第二季"},
                            {"id": 400602, "type": 2, "name": "葬送のフリーレン", "name_cn": "葬送的芙莉莲"},
                        ],
                    },
                )
            if kw == "86":
                return httpx.Response(
                    200,
                    json={
                        "total": 1,
                        "data": [{"id": 302189, "type": 2, "name": "86-エイティシックス-", "name_cn": "86 -不存在的战区-"}],
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
async def test_sync_handles_short_intermediate_page_and_exports(tmp_path: Path) -> None:
    transport, counts = _mock_library_transport(short_first_page=True)
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0)
    out_file = tmp_path / "export.json"

    async with BangumiClient(cfg, transport=transport) as client:
        payload = await sync_user_collections(
            client,
            "alice",
            include_favorites=True,
            page_size=2,
            output_path=out_file,
        )

    assert payload["complete"] is True
    # Must NOT stop after short page 0 (1 item); must continue to offset=2 and get items 1..2!
    assert payload["summary_by_type"]["anime"]["fetched"] == 3
    assert payload["summary_by_type"]["anime"]["skipped_unavailable"] == 1
    assert payload["total_collections"] == 5
    assert out_file.exists()
    assert json.loads(out_file.read_text(encoding="utf-8"))["total_collections"] == 5


@pytest.mark.asyncio
async def test_check_dedup_season_isolation_ambiguity_numeric_title_and_cache() -> None:
    transport, counts = _mock_library_transport()
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0)
    cache = CollectionLibraryCache(ttl_seconds=300.0)

    candidates: list[int | str] = [
        10380,  # strict int subject_id -> collect
        "id:400602",  # explicit id: prefix -> doing
        "孤独摇滚",  # exact normalized CN title -> collect
        "葬送的芙莉莲",  # exact title present in BOTH book & anime -> ambiguous=True
        "葬送的芙莉莲 第二季",  # season 2 must NOT fuzzy-match S1 or pick #2 from search -> uncollected!
        "Bocchi the Rock!",  # search resolves #1 = 328609 -> collect
        "86",  # short numeric title must NOT be treated as subject_id 86 -> resolves to 302189 uncollected
        "关于地球的运动",  # truly uncollected
        "关于地球的运动",  # duplicate in batch should not re-search!
    ]

    async with BangumiClient(cfg, transport=transport) as client:
        report = await check_user_collections(client, "alice", candidates, cache=cache)
        # Verify cache isolation: sync AFTER check still returns populated user profile!
        synced = await sync_user_collections(client, "alice", cache=cache)
        assert synced["user"]["username"] == "alice"

    assert report["library_complete"] is True
    assert report["unknown_count"] == 0

    results = report["results"]
    assert results[0]["status"] == "collect" and results[0]["matched_by"] == "subject_id"
    assert results[1]["status"] == "doing" and results[1]["matched_by"] == "subject_id"
    assert results[2]["status"] == "collect" and results[2]["matched_by"] == "exact_title"
    assert results[3]["ambiguous"] is True and len(results[3]["other_matches"]) == 1
    assert results[4]["collected"] is False and results[4]["resolved_candidate"]["id"] == 500002
    assert results[5]["status"] == "collect" and results[5]["matched_by"] == "search_resolved"
    assert results[6]["collected"] is False and results[6]["resolved_candidate"]["id"] == 302189
    assert results[7]["collected"] is False and results[7]["resolved_candidate"]["id"] == 999001
    # Only 4 unique search queries: S2, Bocchi, 86, 关于地球的运动 (duplicate deduplicated!)
    assert counts["search"] == 4


@pytest.mark.asyncio
async def test_search_failure_returns_unknown_not_uncollected() -> None:
    transport, _ = _mock_library_transport(fail_search=True)
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0, max_retries=0)
    async with BangumiClient(cfg, transport=transport) as client:
        report = await check_user_collections(client, "alice", ["不存在本地的标题"])
    assert report["unknown_count"] == 1
    assert report["uncollected_count"] == 0
    assert report["results"][0]["status"] == "unknown"
    assert report["results"][0]["collected"] is None


@pytest.mark.asyncio
async def test_cache_coalesces_concurrent_misses_and_respects_epoch_invalidation() -> None:
    transport, counts = _mock_library_transport()
    cfg = BangumiConfig(retry_base_delay=0.0, page_delay=0.0)
    cache = CollectionLibraryCache(ttl_seconds=300.0)

    async with BangumiClient(cfg, transport=transport) as client:
        r1, r2 = await asyncio.gather(
            check_user_collections(client, "alice", [10380], subject_types=[2], cache=cache),
            check_user_collections(client, "alice", [400602], subject_types=[2], cache=cache),
        )
    assert r1["collected_count"] == 1 and r2["collected_count"] == 1
    # Coalesced into a single anime fetch (1 request total, not 2)
    assert counts["collections"] == 1

    # Epoch invalidation: invalidating during an in-flight fetch prevents stale write-back
    cache2 = CollectionLibraryCache(ttl_seconds=300.0)
    gate = asyncio.Event()

    async def slow_fetcher() -> Any:
        await gate.wait()
        async with BangumiClient(cfg, transport=transport) as c:
            from bangumi_mcp.services import _fetch_lib_only

            return await _fetch_lib_only(c, "alice", (2,))

    task = asyncio.create_task(cache2.get_or_fetch("alice", (2,), slow_fetcher))
    await asyncio.sleep(0)
    cache2.invalidate()
    gate.set()
    await task
    assert cache2.get("alice", (2,)) is None
