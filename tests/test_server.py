"""End-to-end tests for all MCP tools, annotations, isError semantics, and stdio transport."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import httpx
import pytest

from bangumi_mcp.client import BangumiClient
from bangumi_mcp.config import BangumiConfig
from bangumi_mcp.server import create_server


def _build_mock_transport() -> tuple[httpx.MockTransport, dict[str, int]]:
    counters = {"user_collections": 0}

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
            counters["user_collections"] += 1
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
            return httpx.Response(200, json={"id": 99, "title": "Updated", "desc": "Top picks", "total": 1, "creator": {"username": "demo", "nickname": "Demo"}})
        if m == "GET" and p == "/v0/indices/99/subjects":
            return httpx.Response(200, json={"total": 1, "data": [{"id": 10380, "type": 2, "name": "STEINS;GATE", "name_cn": "命运石之门", "comment": "Must watch"}]})

        # Authenticated endpoints (matching live Go backend behavior)
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
        if m == "POST" and p in (
            "/v0/characters/12203/collect",
            "/v0/persons/4697/collect",
            "/v0/indices/99/collect",
        ):
            return httpx.Response(204)
        if m == "DELETE" and p == "/v0/indices/99/collect":
            return httpx.Response(204)
        if m == "POST" and p == "/v0/indices":
            body = json.loads(request.content.decode("utf-8")) if request.content else {}
            return httpx.Response(200, json={"id": 100, "title": body.get("title", ""), "desc": body.get("description", "")})
        if m == "PUT" and p == "/v0/indices/99":
            # Current Go backend returns empty 204 on PUT
            return httpx.Response(204)
        if p.startswith("/v0/indices/99/subjects"):
            return httpx.Response(200)

        return httpx.Response(404, json={"title": "Not Found", "description": f"{m} {p}"})

    return httpx.MockTransport(handler), counters


async def _call(mcp: Any, name: str, args: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    result = await mcp.call_tool(name, args or {})
    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    blocks = result.content if hasattr(result, "content") else result
    return is_error, json.loads(blocks[0].text)


@pytest.mark.asyncio
async def test_all_tools_registered_annotations_and_public_tools() -> None:
    cfg = BangumiConfig(access_token=None, retry_base_delay=0.0, page_delay=0.0)
    transport, _ = _build_mock_transport()
    client = BangumiClient(cfg, transport=transport)
    mcp = create_server(config=cfg, client=client)

    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    assert len(by_name) == 33
    # MCP sync_user_collections MUST NOT accept arbitrary filesystem output_path
    sync_props = by_name["sync_user_collections"].input_schema.get("properties", {})
    assert "output_path" not in sync_props
    assert by_name["get_subject"].annotations.read_only_hint is True
    assert by_name["upsert_collection"].annotations.read_only_hint is False
    assert by_name["remove_index_subject"].annotations.destructive_hint is True

    # Public tools succeed with isError=False
    assert (await _call(mcp, "search_subjects", {"keyword": "Steins", "subject_types": ["anime"]}))[1]["count"] == 1
    assert (await _call(mcp, "browse_subjects", {"subject_type": "anime"}))[1]["count"] == 1
    assert (await _call(mcp, "get_subject", {"subject_id": 10380}))[1]["name_cn"] == "命运石之门"
    assert (await _call(mcp, "get_subject_persons", {"subject_id": 10380}))[1]["total"] == 1
    assert (await _call(mcp, "get_subject_characters", {"subject_id": 10380}))[1]["total"] == 1
    assert (await _call(mcp, "get_subject_relations", {"subject_id": 10380}))[1]["total"] == 1
    assert (await _call(mcp, "get_episodes", {"subject_id": 10380, "ep_type": "main"}))[1]["count"] == 1
    assert (await _call(mcp, "get_episode", {"episode_id": 77463}))[1]["ep"] == 1
    assert len((await _call(mcp, "get_calendar", {"weekday": "wed"}))[1]["days"]) == 1
    assert (await _call(mcp, "search_characters", {"keyword": "岡部"}))[1]["count"] == 1
    assert (await _call(mcp, "get_character", {"character_id": 12203}))[1]["related_subjects_total"] == 1
    assert (await _call(mcp, "search_persons", {"keyword": "宮野", "career": ["seiyu"]}))[1]["count"] == 1
    assert (await _call(mcp, "get_person", {"person_id": 4697}))[1]["related_characters_total"] == 1
    assert (await _call(mcp, "get_user", {"username": "demo"}))[1]["username"] == "demo"
    assert (await _call(mcp, "get_user_collections", {"username": "demo", "subject_type": "anime"}))[1]["count"] == 1
    assert (await _call(mcp, "get_user_subject_collection", {"username": "demo", "subject_id": 10380}))[1]["rate"] == 10
    assert (await _call(mcp, "sync_user_collections", {"username": "demo"}))[1]["total_collections"] == 1
    assert (await _call(mcp, "check_user_collections", {"username": "demo", "items": ["命运石之门"]}))[1]["collected_count"] == 1
    assert (await _call(mcp, "get_user_favorites", {"username": "demo"}))[1]["characters"]["total"] == 1
    idx_ok, idx_data = await _call(mcp, "get_index", {"index_id": 99})
    assert idx_ok is False and idx_data["subjects"][0]["name_cn"] == "命运石之门"

    # Auth tool fails cleanly with isError=True
    is_err, me_err = await _call(mcp, "get_me")
    assert is_err is True
    assert me_err["code"] == "AUTH_REQUIRED"
    await client.aclose()


@pytest.mark.asyncio
async def test_authenticated_tools_cache_invalidation_and_error_flags() -> None:
    cfg = BangumiConfig(access_token="valid-token", retry_base_delay=0.0, page_delay=0.0)
    transport, counters = _build_mock_transport()
    client = BangumiClient(cfg, transport=transport)
    mcp = create_server(config=cfg, client=client)

    assert (await _call(mcp, "get_me"))[1]["username"] == "demo"
    assert (await _call(mcp, "upsert_collection", {"subject_id": 10380, "collection_type": "看过", "rate": 10, "tags": ["神作"]}))[1]["ok"] is True
    assert (await _call(mcp, "get_episode_progress", {"subject_id": 10380}))[1]["count"] == 1
    assert (await _call(mcp, "get_episode_progress", {"episode_id": 77463}))[1]["watch_status"] == "done"

    # Populate cache, update episode progress -> cache MUST invalidate
    await _call(mcp, "check_user_collections", {"username": "demo", "items": [10380], "subject_types": ["anime"]})
    before = counters["user_collections"]
    await _call(mcp, "update_episode_status", {"episode_id": 77463, "status": "done"})
    await _call(mcp, "check_user_collections", {"username": "demo", "items": [10380], "subject_types": ["anime"]})
    assert counters["user_collections"] > before

    assert (await _call(mcp, "batch_update_episodes", {"subject_id": 10380, "episode_ids": [77463], "status": "看过"}))[1]["updated_count"] == 1
    assert (await _call(mcp, "set_character_collection", {"character_id": 12203, "collect": True}))[1]["collected"] is True

    # Uncollect character/person returns UNSUPPORTED_UPSTREAM with isError=True
    uncoll_err, uncoll_data = await _call(mcp, "set_character_collection", {"character_id": 12203, "collect": False})
    assert uncoll_err is True and uncoll_data["code"] == "UNSUPPORTED_UPSTREAM"

    assert (await _call(mcp, "set_person_collection", {"person_id": 4697, "collect": True}))[1]["collected"] is True
    assert (await _call(mcp, "create_index", {"title": "New List", "description": "Desc"}))[1]["id"] == 100
    # update_index handles 204 empty response from PUT seamlessly
    upd_err, upd_data = await _call(mcp, "update_index", {"index_id": 99, "title": "Updated"})
    assert upd_err is False and upd_data["title"] == "Updated"

    assert (await _call(mcp, "add_index_subject", {"index_id": 99, "subject_id": 10380, "comment": "Top 1"}))[1]["action"] == "added"
    assert (await _call(mcp, "update_index_subject", {"index_id": 99, "subject_id": 10380, "sort": 1, "comment": "Top 1"}))[1]["action"] == "updated"
    assert (await _call(mcp, "remove_index_subject", {"index_id": 99, "subject_id": 10380}))[1]["action"] == "removed"
    assert (await _call(mcp, "set_index_collection", {"index_id": 99, "collect": True}))[1]["collected"] is True

    # Validation error flags
    tag_err, tag_data = await _call(mcp, "upsert_collection", {"subject_id": 10380, "tags": ["has space"]})
    assert tag_err is True and tag_data["error"] is True

    both_err, _ = await _call(mcp, "get_episode_progress", {"subject_id": 10380, "episode_id": 77463})
    assert both_err is True

    await client.aclose()


def test_stdio_subprocess_emits_clean_jsonrpc_only() -> None:
    """Verify real stdio MCP server keeps stdout strictly valid JSON-RPC frames."""
    init_req = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        }
    )
    initialized_notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    list_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    payload = f"{init_req}\n{initialized_notif}\n{list_req}\n"

    proc = subprocess.run(
        [sys.executable, "-c", "from bangumi_mcp.cli import main_mcp; raise SystemExit(main_mcp(['--transport', 'stdio']))"],
        input=payload,
        text=True,
        capture_output=True,
        timeout=15,
        encoding="utf-8",
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 2, f"Expected JSON-RPC responses on stdout, got stderr={proc.stderr!r}"
    messages = [json.loads(ln) for ln in lines]
    by_id = {m.get("id"): m for m in messages if "id" in m}
    assert 1 in by_id and "result" in by_id[1]
    assert 2 in by_id and len(by_id[2]["result"]["tools"]) == 33
