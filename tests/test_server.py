"""End-to-end tests for all MCP tools registered on FastMCP."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from bangumi_mcp.client import BangumiClient
from bangumi_mcp.config import BangumiConfig
from bangumi_mcp.server import create_server


def _build_mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        m = request.method
        p = request.url.path

        if m == "POST" and p == "/v0/search/subjects":
            return httpx.Response(200, json={"total": 1, "limit": 15, "offset": 0, "data": [{"id": 10380, "type": 2, "name": "STEINS;GATE", "name_cn": "命运石之门", "rating": {"score": 8.8, "rank": 5, "total": 18000}}]})
        if m == "GET" and p == "/v0/subjects":
            return httpx.Response(200, json={"total": 1, "limit": 20, "offset": 0, "data": [{"id": 10380, "type": 2, "name": "STEINS;GATE", "name_cn": "命运石之门", "rating": {"score": 8.8, "rank": 5}}]})
        if m == "GET" and p == "/v0/subjects/10380":
            return httpx.Response(200, json={"id": 10380, "type": 2, "name": "STEINS;GATE", "name_cn": "命运石之门", "summary": "El Psy Kongroo", "rating": {"score": 8.8, "rank": 5, "total": 18000}, "collection": {"collect": 20000}})
        if m == "GET" and p == "/v0/subjects/10380/persons":
            return httpx.Response(200, json=[{"id": 6073, "name": "WHITE FOX", "relation": "动画制作", "type": 2, "career": ["producer"]}])
        if m == "GET" and p == "/v0/subjects/10380/characters":
            return httpx.Response(200, json=[{"id": 12203, "name": "岡部倫太郎", "relation": "主角", "type": 1, "actors": [{"id": 4697, "name": "宮野真守"}]}])
        if m == "GET" and p == "/v0/subjects/10380/subjects":
            return httpx.Response(200, json=[{"id": 129807, "type": 2, "name": "STEINS;GATE 0", "name_cn": "命运石之门 0", "relation": "续集"}])
        if m == "GET" and p == "/v0/episodes":
            return httpx.Response(200, json={"total": 1, "limit": 100, "offset": 0, "data": [{"id": 77463, "type": 0, "ep": 1, "sort": 1, "name": "Turning Point", "name_cn": "开始与终结的序章"}]})
        if m == "GET" and p == "/v0/episodes/77463":
            return httpx.Response(200, json={"id": 77463, "subject_id": 10380, "type": 0, "ep": 1, "sort": 1, "name": "Turning Point", "name_cn": "开始与终结的序章", "desc": "First episode"})
        if m == "GET" and p == "/calendar":
            return httpx.Response(200, json=[{"weekday": {"id": 3, "en": "Wed", "cn": "星期三"}, "items": [{"id": 10380, "name": "STEINS;GATE", "name_cn": "命运石之门", "rating": {"score": 8.8}}]}])
        if m == "POST" and p == "/v0/search/characters":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 12203, "name": "岡部倫太郎", "type": 1, "summary": "Mad scientist"}]})
        if m == "GET" and p == "/v0/characters/12203":
            return httpx.Response(200, json={"id": 12203, "name": "岡部倫太郎", "type": 1, "summary": "Mad scientist", "stat": {"collects": 5000}})
        if m == "GET" and p == "/v0/characters/12203/subjects":
            return httpx.Response(200, json=[{"id": 10380, "type": 2, "name": "STEINS;GATE", "name_cn": "命运石之门", "staff": "主角"}])
        if m == "GET" and p == "/v0/characters/12203/persons":
            return httpx.Response(200, json=[{"id": 4697, "name": "宮野真守", "subject_id": 10380, "subject_name": "STEINS;GATE", "staff": "主角"}])
        if m == "POST" and p == "/v0/search/persons":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 4697, "name": "宮野真守", "type": 1, "career": ["seiyu"]}]})
        if m == "GET" and p == "/v0/persons/4697":
            return httpx.Response(200, json={"id": 4697, "name": "宮野真守", "type": 1, "career": ["seiyu"], "summary": "Voice actor", "stat": {"collects": 3000}})
        if m == "GET" and p == "/v0/persons/4697/subjects":
            return httpx.Response(200, json=[{"id": 10380, "type": 2, "name": "STEINS;GATE", "staff": "主题歌演出"}])
        if m == "GET" and p == "/v0/persons/4697/characters":
            return httpx.Response(200, json=[{"id": 12203, "name": "岡部倫太郎", "subject_id": 10380, "subject_name": "STEINS;GATE"}])
        if m == "GET" and p == "/v0/users/demo":
            return httpx.Response(200, json={"id": 1, "username": "demo", "nickname": "Demo User", "sign": "hi"})
        if m == "GET" and p == "/v0/users/demo/collections":
            st = request.url.params.get("subject_type")
            items = (
                [{"subject_id": 10380, "subject_type": 2, "type": 2, "rate": 10, "subject": {"name": "STEINS;GATE", "name_cn": "命运石之门"}}]
                if st in (None, "2")
                else []
            )
            return httpx.Response(200, json={"total": len(items), "limit": 30, "offset": 0, "data": items})
        if m == "GET" and p == "/v0/users/demo/collections/10380":
            return httpx.Response(200, json={"subject_id": 10380, "subject_type": 2, "type": 2, "rate": 10, "comment": "Masterpiece", "subject": {"name": "STEINS;GATE", "name_cn": "命运石之门"}})
        if m == "GET" and p == "/v0/users/demo/collections/-/characters":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 12203, "name": "岡部倫太郎", "type": 1}]})
        if m == "GET" and p == "/v0/users/demo/collections/-/persons":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 4697, "name": "宮野真守", "type": 1, "career": ["seiyu"]}]})
        if m == "GET" and p == "/v0/indices/99":
            return httpx.Response(200, json={"id": 99, "title": "Sci-Fi Classics", "desc": "Top picks", "total": 1, "creator": {"username": "demo", "nickname": "Demo"}})
        if m == "GET" and p == "/v0/indices/99/subjects":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 10380, "type": 2, "name": "STEINS;GATE", "comment": "Must watch"}]})

        # Authenticated endpoints
        if m == "GET" and p == "/v0/me":
            return httpx.Response(200, json={"id": 1, "username": "demo", "nickname": "Demo User"})
        if m in ("POST", "PATCH") and p == "/v0/users/-/collections/10380":
            return httpx.Response(204)
        if m == "GET" and p == "/v0/users/-/collections/10380/episodes":
            return httpx.Response(200, json={"total": 1, "data": [{"type": 2, "updated_at": 1700000000, "episode": {"id": 77463, "type": 0, "ep": 1, "sort": 1, "name": "Ep1"}}]})
        if m == "GET" and p == "/v0/users/-/collections/-/episodes/77463":
            return httpx.Response(200, json={"type": 2, "updated_at": 1700000000, "episode": {"id": 77463, "type": 0, "ep": 1, "sort": 1, "name": "Ep1"}})
        if m == "PUT" and p == "/v0/users/-/collections/-/episodes/77463":
            return httpx.Response(204)
        if m == "PATCH" and p == "/v0/users/-/collections/10380/episodes":
            return httpx.Response(204)
        if m in ("POST", "DELETE") and p in (
            "/v0/characters/12203/collect",
            "/v0/persons/4697/collect",
            "/v0/indices/99/collect",
        ):
            return httpx.Response(204)
        if m == "POST" and p == "/v0/indices":
            return httpx.Response(200, json={"id": 100, "title": "", "desc": ""})
        if m == "PUT" and p in ("/v0/indices/99", "/v0/indices/100"):
            body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": int(p.split("/")[-1]), "title": body.get("title", ""), "desc": body.get("description", "")})
        if p.startswith("/v0/indices/99/subjects"):
            return httpx.Response(200)

        return httpx.Response(404, json={"title": "Not Found", "description": f"{m} {p}"})

    return httpx.MockTransport(handler)


async def _call_json(mcp: Any, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    result = await mcp.call_tool(name, args or {})
    if hasattr(result, "content"):
        blocks = result.content
    elif isinstance(result, tuple):
        blocks = result[0]
    else:
        blocks = result
    text = blocks[0].text
    return json.loads(text)


@pytest.mark.asyncio
async def test_all_tools_registered_and_public_tools_work_without_token() -> None:
    cfg = BangumiConfig(access_token=None, retry_base_delay=0.0, page_delay=0.0)
    client = BangumiClient(cfg, transport=_build_mock_transport())
    mcp = create_server(config=cfg, client=client)

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert len(tool_names) == 33
    assert {"search_subjects", "check_user_collections", "sync_user_collections", "get_me", "upsert_collection"} <= tool_names

    # Public tools succeed without token
    assert (await _call_json(mcp, "search_subjects", {"keyword": "Steins", "subject_types": ["anime"]}))["count"] == 1
    assert (await _call_json(mcp, "browse_subjects", {"subject_type": "anime"}))["count"] == 1
    assert (await _call_json(mcp, "get_subject", {"subject_id": 10380}))["name_cn"] == "命运石之门"
    assert (await _call_json(mcp, "get_subject_persons", {"subject_id": 10380}))["total"] == 1
    assert (await _call_json(mcp, "get_subject_characters", {"subject_id": 10380}))["total"] == 1
    assert (await _call_json(mcp, "get_subject_relations", {"subject_id": 10380}))["total"] == 1
    assert (await _call_json(mcp, "get_episodes", {"subject_id": 10380, "ep_type": "main"}))["count"] == 1
    assert (await _call_json(mcp, "get_episode", {"episode_id": 77463}))["ep"] == 1
    assert len((await _call_json(mcp, "get_calendar", {"weekday": "wed"}))["days"]) == 1
    assert (await _call_json(mcp, "search_characters", {"keyword": "岡部"}))["count"] == 1
    assert (await _call_json(mcp, "get_character", {"character_id": 12203}))["related_subjects_total"] == 1
    assert (await _call_json(mcp, "search_persons", {"keyword": "宮野", "career": ["seiyu"]}))["count"] == 1
    assert (await _call_json(mcp, "get_person", {"person_id": 4697}))["related_characters_total"] == 1
    assert (await _call_json(mcp, "get_user", {"username": "demo"}))["username"] == "demo"
    assert (await _call_json(mcp, "get_user_collections", {"username": "demo", "subject_type": "anime"}))["count"] == 1
    assert (await _call_json(mcp, "get_user_subject_collection", {"username": "demo", "subject_id": 10380}))["rate"] == 10
    assert (await _call_json(mcp, "sync_user_collections", {"username": "demo"}))["total_collections"] == 1
    assert (await _call_json(mcp, "check_user_collections", {"username": "demo", "items": ["命运石之门"]}))["collected_count"] == 1
    assert (await _call_json(mcp, "get_user_favorites", {"username": "demo"}))["characters"]["total"] == 1
    assert (await _call_json(mcp, "get_index", {"index_id": 99}))["subjects_total"] == 1

    # Auth tool gracefully reports AUTH_REQUIRED instead of crashing
    me_err = await _call_json(mcp, "get_me")
    assert me_err["error"] is True
    assert me_err["code"] == "AUTH_REQUIRED"
    assert "BANGUMI_ACCESS_TOKEN" in me_err["message"]
    await client.aclose()


@pytest.mark.asyncio
async def test_authenticated_tools_and_validation() -> None:
    cfg = BangumiConfig(access_token="valid-token", retry_base_delay=0.0, page_delay=0.0)
    client = BangumiClient(cfg, transport=_build_mock_transport())
    mcp = create_server(config=cfg, client=client)

    assert (await _call_json(mcp, "get_me"))["username"] == "demo"
    assert (await _call_json(mcp, "upsert_collection", {"subject_id": 10380, "collection_type": "看过", "rate": 10, "tags": ["神作"]}))["ok"] is True
    assert (await _call_json(mcp, "get_episode_progress", {"subject_id": 10380}))["count"] == 1
    assert (await _call_json(mcp, "get_episode_progress", {"episode_id": 77463}))["watch_status"] == "done"
    assert (await _call_json(mcp, "update_episode_status", {"episode_id": 77463, "status": "done"}))["ok"] is True
    assert (await _call_json(mcp, "batch_update_episodes", {"subject_id": 10380, "episode_ids": [77463], "status": "看过"}))["updated_count"] == 1
    assert (await _call_json(mcp, "set_character_collection", {"character_id": 12203, "collect": True}))["collected"] is True
    assert (await _call_json(mcp, "set_character_collection", {"character_id": 12203, "collect": False}))["collected"] is False
    assert (await _call_json(mcp, "set_person_collection", {"person_id": 4697, "collect": True}))["collected"] is True
    assert (await _call_json(mcp, "create_index", {"title": "New List", "description": "Desc"}))["id"] == 100
    assert (await _call_json(mcp, "update_index", {"index_id": 99, "title": "Updated"}))["title"] == "Updated"
    assert (await _call_json(mcp, "add_index_subject", {"index_id": 99, "subject_id": 10380, "comment": "Top 1"}))["action"] == "added"
    assert (await _call_json(mcp, "update_index_subject", {"index_id": 99, "subject_id": 10380, "sort": 1}))["action"] == "updated"
    assert (await _call_json(mcp, "remove_index_subject", {"index_id": 99, "subject_id": 10380}))["action"] == "removed"
    assert (await _call_json(mcp, "set_index_collection", {"index_id": 99, "collect": True}))["collected"] is True

    # Validation error checks
    bad_rate = await _call_json(mcp, "upsert_collection", {"subject_id": 10380, "rate": 11})
    assert bad_rate["error"] is True
    bad_tag = await _call_json(mcp, "upsert_collection", {"subject_id": 10380, "tags": ["has space"]})
    assert bad_tag["error"] is True
    bad_eps = await _call_json(mcp, "batch_update_episodes", {"subject_id": 10380, "episode_ids": []})
    assert bad_eps["error"] is True

    await client.aclose()
