"""Unit tests for BangumiClient: headers, retries, auth guard, error parsing, endpoints."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from bangumi_mcp.client import AuthRequiredError, BangumiAPIError, BangumiClient
from bangumi_mcp.config import BangumiConfig


def _make_config(**overrides: Any) -> BangumiConfig:
    defaults = dict(
        base_url="https://api.bgm.tv",
        access_token=None,
        retry_base_delay=0.0,
        page_delay=0.0,
        max_retries=2,
    )
    defaults.update(overrides)
    return BangumiConfig(**defaults)


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
async def test_retry_on_429_and_503_then_succeed() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"title": "Too Many Requests"})
        if attempts == 2:
            return httpx.Response(503, json={"title": "Service Unavailable"})
        return httpx.Response(200, json={"id": 42, "name": "Recovered"})

    async with BangumiClient(_make_config(max_retries=3), transport=httpx.MockTransport(handler)) as client:
        data = await client.get_subject(42)
    assert attempts == 3
    assert data["name"] == "Recovered"


@pytest.mark.asyncio
async def test_api_error_parsing_404_and_400() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "title": "Not Found",
                "description": "subject does not exist",
                "details": {"path": "/v0/subjects/99999999"},
            },
        )

    async with BangumiClient(_make_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BangumiAPIError) as exc_info:
            await client.get_subject(99999999)
    err = exc_info.value
    assert err.status_code == 404
    assert err.title == "Not Found"
    assert "does not exist" in err.description
    assert err.to_dict()["status_code"] == 404


@pytest.mark.asyncio
async def test_204_no_content_and_create_index_flow() -> None:
    requests_log: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests_log.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path == "/v0/indices":
            return httpx.Response(200, json={"id": 777, "title": "", "desc": ""})
        if request.method == "PUT" and request.url.path == "/v0/indices/777":
            return httpx.Response(
                200,
                json={"id": 777, "title": body["title"], "desc": body["description"]},
            )
        return httpx.Response(204)

    async with BangumiClient(
        _make_config(access_token="tok"), transport=httpx.MockTransport(handler)
    ) as client:
        await client.upsert_user_collection(10, collection_type=2, rate=9, tags=["神作"])
        idx = await client.create_index(title="2026 Top", description="My favorites")

    assert requests_log[0] == ("POST", "/v0/users/-/collections/10", {"type": 2, "rate": 9, "tags": ["神作"]})
    assert requests_log[1] == ("POST", "/v0/indices", None)
    assert requests_log[2] == ("PUT", "/v0/indices/777", {"title": "2026 Top", "description": "My favorites"})
    assert idx["id"] == 777
    assert idx["title"] == "2026 Top"
