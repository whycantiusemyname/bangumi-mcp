"""Unit tests for BangumiClient: headers, security, safe retries, Retry-After, and index contracts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from bangumi_mcp.client import (
    AuthRequiredError,
    BangumiAPIError,
    BangumiClient,
    BangumiError,
    UnsupportedUpstreamError,
    parse_retry_after,
)
from bangumi_mcp.config import BangumiConfig


def _make_config(**overrides: Any) -> BangumiConfig:
    defaults = dict(
        base_url="https://api.bgm.tv",
        access_token=None,
        retry_base_delay=0.0,
        page_delay=0.0,
        max_retries=2,
        max_retry_after=30.0,
    )
    defaults.update(overrides)
    return BangumiConfig(**defaults)


def test_config_repr_hides_access_token_and_blocks_plain_http_token() -> None:
    cfg = _make_config(access_token="super-secret-token")
    assert "super-secret-token" not in repr(cfg)

    with pytest.raises(BangumiError, match="insecure scheme"):
        BangumiClient(_make_config(base_url="http://api.example.com", access_token="tok"))

    # Loopback HTTP is permitted for local tests
    local_client = BangumiClient(_make_config(base_url="http://127.0.0.1:8080", access_token="tok"))
    assert local_client.has_token


def test_parse_retry_after_seconds_and_http_date() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after("-3") is None
    assert parse_retry_after("nan") is None
    assert parse_retry_after("inf") is None

    future = datetime.now(timezone.utc) + timedelta(seconds=12)
    parsed = parse_retry_after(format_datetime(future, usegmt=True))
    assert parsed is not None
    assert 8.0 <= parsed <= 15.0


@pytest.mark.asyncio
async def test_headers_without_and_with_token() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"id": 1, "name": "test"})

    transport = httpx.MockTransport(handler)
    async with BangumiClient(_make_config(), transport=transport) as client:
        await client.get_subject(1)
    assert "bangumi-mcp" in seen_headers[0]["user-agent"]
    assert "authorization" not in seen_headers[0]

    async with BangumiClient(_make_config(access_token="secret-tok"), transport=transport) as client:
        await client.get_me()
    assert seen_headers[1]["authorization"] == "Bearer secret-tok"


@pytest.mark.asyncio
async def test_auth_required_guard_blocks_before_network() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async with BangumiClient(_make_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthRequiredError, match="BANGUMI_ACCESS_TOKEN"):
            await client.get_me()
        with pytest.raises(AuthRequiredError):
            await client.upsert_user_collection(123, collection_type=2)
        with pytest.raises(AuthRequiredError):
            await client.update_user_episode(456, 2)
    assert not called


@pytest.mark.asyncio
async def test_read_requests_retry_but_writes_never_auto_replay() -> None:
    get_attempts = 0
    search_attempts = 0
    write_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_attempts, search_attempts, write_attempts
        if request.method == "GET":
            get_attempts += 1
            if get_attempts < 3:
                return httpx.Response(429, headers={"Retry-After": "0"}, json={"title": "Too Many Requests"})
            return httpx.Response(200, json={"id": 42, "name": "Recovered"})
        if request.url.path == "/v0/search/subjects":
            search_attempts += 1
            if search_attempts == 1:
                return httpx.Response(503, json={"title": "Unavailable"})
            return httpx.Response(200, json={"total": 0, "data": []})
        if request.url.path == "/v0/indices":
            write_attempts += 1
            return httpx.Response(502, json={"title": "Bad Gateway"})
        return httpx.Response(404)

    async with BangumiClient(
        _make_config(access_token="tok", max_retries=3), transport=httpx.MockTransport(handler)
    ) as client:
        assert (await client.get_subject(42))["name"] == "Recovered"
        assert (await client.search_subjects("test"))["total"] == 0
        with pytest.raises(BangumiAPIError) as exc_info:
            await client.create_index(title="No Duplicate")

    assert get_attempts == 3
    assert search_attempts == 2
    assert write_attempts == 1  # NEVER replayed!
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_retry_after_exceeding_budget_fails_immediately() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"title": "Too Many Requests"})

    async with BangumiClient(
        _make_config(max_retries=3, max_retry_after=10.0), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(BangumiAPIError) as exc_info:
            await client.get_subject(1)
    assert attempts == 1
    assert exc_info.value.status_code == 429
    assert exc_info.value.details["retry_after_seconds"] == 120.0


@pytest.mark.asyncio
async def test_api_error_parsing_404_and_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/99999999"):
            return httpx.Response(
                404,
                json={"title": "Not Found", "description": "subject does not exist"},
            )
        return httpx.Response(403, text="")

    async with BangumiClient(
        _make_config(access_token="tok"), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(BangumiAPIError) as e404:
            await client.get_subject(99999999)
        assert e404.value.status_code == 404

        with pytest.raises(BangumiAPIError) as e403:
            await client.get_subject(1)
        assert e403.value.status_code == 403
        assert "Forbidden" in e403.value.description


@pytest.mark.asyncio
async def test_create_and_update_index_current_upstream_contract() -> None:
    requests_log: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests_log.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/v0/indices":
            # Current Go backend accepts title/description directly in POST
            return httpx.Response(
                200,
                json={"id": 777, "title": body["title"], "desc": body["description"]},
            )
        if request.method == "PUT" and request.url.path == "/v0/indices/777":
            # Current Go backend returns empty 204/200 body on PUT
            return httpx.Response(204)
        if request.method == "GET" and request.url.path == "/v0/indices/777":
            return httpx.Response(
                200,
                json={"id": 777, "title": "Updated Title", "desc": "Updated Desc"},
            )
        return httpx.Response(204)

    async with BangumiClient(
        _make_config(access_token="tok"), transport=httpx.MockTransport(handler)
    ) as client:
        created = await client.create_index(title="2026 Top", description="My favorites")
        updated = await client.update_index(777, title="Updated Title", description="Updated Desc")
        with pytest.raises(UnsupportedUpstreamError):
            await client.uncollect_character(1)
        with pytest.raises(UnsupportedUpstreamError):
            await client.uncollect_person(2)

    assert requests_log[0] == ("POST", "/v0/indices", {"title": "2026 Top", "description": "My favorites"})
    assert created["id"] == 777
    assert requests_log[1] == ("PUT", "/v0/indices/777", {"title": "Updated Title", "description": "Updated Desc"})
    assert requests_log[2] == ("GET", "/v0/indices/777", None)
    assert updated["title"] == "Updated Title"
