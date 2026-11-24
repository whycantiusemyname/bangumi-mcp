"""Async HTTP client for Bangumi API v0 with retries, rate-limit backoff, and clean errors."""

from __future__ import annotations

import asyncio
import random
from typing import Any
from urllib.parse import quote

import httpx

from .config import BangumiConfig

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class BangumiError(Exception):
    """Base exception for bangumi-mcp."""


class AuthRequiredError(BangumiError):
    """Raised when an authenticated endpoint is called without BANGUMI_ACCESS_TOKEN."""

    def __init__(self, action: str = "this operation") -> None:
        super().__init__(
            f"BANGUMI_ACCESS_TOKEN is required for {action}. "
            "Public read-only tools work without a token. "
            "To enable personal read/write actions, generate a Personal Access Token at "
            "https://next.bgm.tv/demo/access-token and set the BANGUMI_ACCESS_TOKEN environment variable."
        )


class BangumiAPIError(BangumiError):
    """Structured error returned by Bangumi API."""

    def __init__(
        self,
        status_code: int,
        title: str,
        description: str = "",
        details: Any = None,
        path: str = "",
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.description = description
        self.details = details
        self.path = path
        parts = [f"Bangumi API error {status_code}: {title}"]
        if description:
            parts.append(description)
        if details and details != description:
            parts.append(f"({details})")
        super().__init__(" - ".join(parts))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": True,
            "status_code": self.status_code,
            "title": self.title,
            "description": self.description,
        }
        if self.details:
            payload["details"] = self.details
        if self.path:
            payload["path"] = self.path
        return payload


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    try:
        delay = float(header_value.strip())
        return max(0.0, min(delay, 30.0))
    except ValueError:
        return None


class BangumiClient:
    """Async client wrapping Bangumi API v0 and /calendar."""

    def __init__(
        self,
        config: BangumiConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or BangumiConfig.from_env()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def has_token(self) -> bool:
        return bool(self.config.access_token)

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
        }
        if self.config.access_token:
            headers["Authorization"] = f"Bearer {self.config.access_token}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=self._build_headers(),
                timeout=httpx.Timeout(self.config.timeout),
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> BangumiClient:
        self._get_client()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    def _backoff_delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return retry_after
        if self.config.retry_base_delay <= 0:
            return 0.0
        base = self.config.retry_base_delay * (2**attempt)
        jitter = random.uniform(0.0, self.config.retry_base_delay * 0.4)
        return min(base + jitter, 12.0)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        require_auth: bool = False,
        action_name: str | None = None,
    ) -> Any:
        if require_auth and not self.has_token:
            raise AuthRequiredError(action_name or f"{method} {path}")

        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params is not None else None
        )
        client = self._get_client()
        max_attempts = self.config.max_retries + 1

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = await client.request(
                    method,
                    path,
                    params=clean_params,
                    json=json_body,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise BangumiError(f"Network error calling {method} {path}: {exc}") from exc

            if response.status_code in RETRYABLE_STATUS_CODES and attempt + 1 < max_attempts:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await asyncio.sleep(self._backoff_delay(attempt, retry_after))
                continue

            if response.status_code >= 400:
                title = response.reason_phrase or f"HTTP {response.status_code}"
                description = ""
                details: Any = None
                try:
                    err_data = response.json()
                    if isinstance(err_data, dict):
                        title = str(err_data.get("title") or title)
                        description = str(err_data.get("description") or "")
                        details = err_data.get("details")
                except Exception:
                    description = response.text[:300].strip()

                if response.status_code == 401 and not description:
                    description = "Invalid or expired BANGUMI_ACCESS_TOKEN, or insufficient scope."
                raise BangumiAPIError(
                    status_code=response.status_code,
                    title=title,
                    description=description,
                    details=details,
                    path=path,
                )

            if response.status_code == 204 or not response.content:
                return None

            try:
                return response.json()
            except ValueError as exc:
                raise BangumiError(
                    f"Invalid JSON response from {method} {path} (status {response.status_code})"
                ) from exc

        raise BangumiError(f"Request failed after retries: {last_exc}")

    # ------------------------------------------------------------------
    # Public Read-Only Endpoints
    # ------------------------------------------------------------------

    async def search_subjects(
        self,
        keyword: str,
        *,
        sort: str = "match",
        subject_types: list[int] | None = None,
        tags: list[str] | None = None,
        meta_tags: list[str] | None = None,
        air_date: list[str] | None = None,
        rating: list[str] | None = None,
        rating_count: list[str] | None = None,
        rank: list[str] | None = None,
        nsfw: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        filter_obj: dict[str, Any] = {}
        if subject_types:
            filter_obj["type"] = subject_types
        if tags:
            filter_obj["tag"] = tags
        if meta_tags:
            filter_obj["meta_tags"] = meta_tags
        if air_date:
            filter_obj["air_date"] = air_date
        if rating:
            filter_obj["rating"] = rating
        if rating_count:
            filter_obj["rating_count"] = rating_count
        if rank:
            filter_obj["rank"] = rank
        if nsfw is not None:
            filter_obj["nsfw"] = nsfw

        body: dict[str, Any] = {"keyword": keyword, "sort": sort}
        if filter_obj:
            body["filter"] = filter_obj

        return await self.request(
            "POST",
            "/v0/search/subjects",
            params={"limit": limit, "offset": offset},
            json_body=body,
        )

    async def browse_subjects(
        self,
        subject_type: int,
        *,
        cat: int | None = None,
        series: bool | None = None,
        platform: str | None = None,
        sort: str | None = None,
        year: int | None = None,
        month: int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/v0/subjects",
            params={
                "type": subject_type,
                "cat": cat,
                "series": series,
                "platform": platform,
                "sort": sort,
                "year": year,
                "month": month,
                "limit": limit,
                "offset": offset,
            },
        )

    async def get_subject(self, subject_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/v0/subjects/{subject_id}")

    async def get_subject_persons(self, subject_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/subjects/{subject_id}/persons")

    async def get_subject_characters(self, subject_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/subjects/{subject_id}/characters")

    async def get_subject_relations(self, subject_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/subjects/{subject_id}/subjects")

    async def get_episodes(
        self,
        subject_id: int,
        *,
        ep_type: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/v0/episodes",
            params={
                "subject_id": subject_id,
                "type": ep_type,
                "limit": limit,
                "offset": offset,
            },
        )

    async def get_episode(self, episode_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/v0/episodes/{episode_id}")

    async def get_calendar(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/calendar")

    async def search_characters(
        self,
        keyword: str,
        *,
        nsfw: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"keyword": keyword}
        if nsfw is not None:
            body["filter"] = {"nsfw": nsfw}
        return await self.request(
            "POST",
            "/v0/search/characters",
            params={"limit": limit, "offset": offset},
            json_body=body,
        )

    async def get_character(self, character_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/v0/characters/{character_id}")

    async def get_character_subjects(self, character_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/characters/{character_id}/subjects")

    async def get_character_persons(self, character_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/characters/{character_id}/persons")

    async def search_persons(
        self,
        keyword: str,
        *,
        career: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"keyword": keyword}
        if career:
            body["filter"] = {"career": career}
        return await self.request(
            "POST",
            "/v0/search/persons",
            params={"limit": limit, "offset": offset},
            json_body=body,
        )

    async def get_person(self, person_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/v0/persons/{person_id}")

    async def get_person_subjects(self, person_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/persons/{person_id}/subjects")

    async def get_person_characters(self, person_id: int) -> list[dict[str, Any]]:
        return await self.request("GET", f"/v0/persons/{person_id}/characters")

    async def get_user(self, username: str) -> dict[str, Any]:
        safe_user = quote(username, safe="")
        return await self.request("GET", f"/v0/users/{safe_user}")

    async def get_user_collections(
        self,
        username: str,
        *,
        subject_type: int | None = None,
        collection_type: int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_user = quote(username, safe="")
        return await self.request(
            "GET",
            f"/v0/users/{safe_user}/collections",
            params={
                "subject_type": subject_type,
                "type": collection_type,
                "limit": limit,
                "offset": offset,
            },
        )

    async def get_user_subject_collection(
        self, username: str, subject_id: int
    ) -> dict[str, Any]:
        safe_user = quote(username, safe="")
        return await self.request("GET", f"/v0/users/{safe_user}/collections/{subject_id}")

    async def get_user_character_collections(
        self, username: str, *, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        safe_user = quote(username, safe="")
        return await self.request(
            "GET",
            f"/v0/users/{safe_user}/collections/-/characters",
            params={"limit": limit, "offset": offset},
        )

    async def get_user_person_collections(
        self, username: str, *, limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        safe_user = quote(username, safe="")
        return await self.request(
            "GET",
            f"/v0/users/{safe_user}/collections/-/persons",
            params={"limit": limit, "offset": offset},
        )

    async def get_index(self, index_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/v0/indices/{index_id}")

    async def get_index_subjects(
        self,
        index_id: int,
        *,
        subject_type: int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/v0/indices/{index_id}/subjects",
            params={"type": subject_type, "limit": limit, "offset": offset},
        )

    # ------------------------------------------------------------------
    # Authenticated Endpoints (require BANGUMI_ACCESS_TOKEN)
    # ------------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        return await self.request(
            "GET", "/v0/me", require_auth=True, action_name="fetching current user (/v0/me)"
        )

    async def upsert_user_collection(
        self,
        subject_id: int,
        *,
        collection_type: int | None = None,
        rate: int | None = None,
        ep_status: int | None = None,
        vol_status: int | None = None,
        comment: str | None = None,
        private: bool | None = None,
        tags: list[str] | None = None,
        create_if_missing: bool = True,
    ) -> None:
        payload: dict[str, Any] = {}
        if collection_type is not None:
            payload["type"] = collection_type
        if rate is not None:
            payload["rate"] = rate
        if ep_status is not None:
            payload["ep_status"] = ep_status
        if vol_status is not None:
            payload["vol_status"] = vol_status
        if comment is not None:
            payload["comment"] = comment
        if private is not None:
            payload["private"] = private
        if tags is not None:
            payload["tags"] = tags

        method = "POST" if create_if_missing else "PATCH"
        await self.request(
            method,
            f"/v0/users/-/collections/{subject_id}",
            json_body=payload,
            require_auth=True,
            action_name=f"updating collection for subject {subject_id}",
        )

    async def get_user_subject_episodes(
        self,
        subject_id: int,
        *,
        episode_type: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/v0/users/-/collections/{subject_id}/episodes",
            params={
                "episode_type": episode_type,
                "limit": limit,
                "offset": offset,
            },
            require_auth=True,
            action_name=f"reading episode progress for subject {subject_id}",
        )

    async def get_user_episode(self, episode_id: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/v0/users/-/collections/-/episodes/{episode_id}",
            require_auth=True,
            action_name=f"reading episode progress for episode {episode_id}",
        )

    async def update_user_episode(self, episode_id: int, status: int) -> None:
        await self.request(
            "PUT",
            f"/v0/users/-/collections/-/episodes/{episode_id}",
            json_body={"type": status},
            require_auth=True,
            action_name=f"updating episode {episode_id} watch status",
        )

    async def batch_update_user_episodes(
        self, subject_id: int, episode_ids: list[int], status: int
    ) -> None:
        await self.request(
            "PATCH",
            f"/v0/users/-/collections/{subject_id}/episodes",
            json_body={"episode_id": episode_ids, "type": status},
            require_auth=True,
            action_name=f"batch updating episode progress for subject {subject_id}",
        )

    async def collect_character(self, character_id: int) -> None:
        await self.request(
            "POST",
            f"/v0/characters/{character_id}/collect",
            require_auth=True,
            action_name=f"collecting character {character_id}",
        )

    async def uncollect_character(self, character_id: int) -> None:
        await self.request(
            "DELETE",
            f"/v0/characters/{character_id}/collect",
            require_auth=True,
            action_name=f"uncollecting character {character_id}",
        )

    async def collect_person(self, person_id: int) -> None:
        await self.request(
            "POST",
            f"/v0/persons/{person_id}/collect",
            require_auth=True,
            action_name=f"collecting person {person_id}",
        )

    async def uncollect_person(self, person_id: int) -> None:
        await self.request(
            "DELETE",
            f"/v0/persons/{person_id}/collect",
            require_auth=True,
            action_name=f"uncollecting person {person_id}",
        )

    async def create_index(
        self, *, title: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        created = await self.request(
            "POST",
            "/v0/indices",
            require_auth=True,
            action_name="creating a new index",
        )
        if created and isinstance(created, dict) and (title is not None or description is not None):
            index_id = created.get("id")
            if index_id:
                return await self.update_index(
                    int(index_id), title=title, description=description
                )
        return created

    async def update_index(
        self,
        index_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        return await self.request(
            "PUT",
            f"/v0/indices/{index_id}",
            json_body=body,
            require_auth=True,
            action_name=f"editing index {index_id}",
        )

    async def add_index_subject(
        self,
        index_id: int,
        subject_id: int,
        *,
        sort: int | None = None,
        comment: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"subject_id": subject_id}
        if sort is not None:
            body["sort"] = sort
        if comment is not None:
            body["comment"] = comment
        await self.request(
            "POST",
            f"/v0/indices/{index_id}/subjects",
            json_body=body,
            require_auth=True,
            action_name=f"adding subject {subject_id} to index {index_id}",
        )

    async def update_index_subject(
        self,
        index_id: int,
        subject_id: int,
        *,
        sort: int | None = None,
        comment: str | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if sort is not None:
            body["sort"] = sort
        if comment is not None:
            body["comment"] = comment
        await self.request(
            "PUT",
            f"/v0/indices/{index_id}/subjects/{subject_id}",
            json_body=body,
            require_auth=True,
            action_name=f"updating subject {subject_id} in index {index_id}",
        )

    async def remove_index_subject(self, index_id: int, subject_id: int) -> None:
        await self.request(
            "DELETE",
            f"/v0/indices/{index_id}/subjects/{subject_id}",
            require_auth=True,
            action_name=f"removing subject {subject_id} from index {index_id}",
        )

    async def collect_index(self, index_id: int) -> None:
        await self.request(
            "POST",
            f"/v0/indices/{index_id}/collect",
            require_auth=True,
            action_name=f"collecting index {index_id}",
        )

    async def uncollect_index(self, index_id: int) -> None:
        await self.request(
            "DELETE",
            f"/v0/indices/{index_id}/collect",
            require_auth=True,
            action_name=f"uncollecting index {index_id}",
        )
