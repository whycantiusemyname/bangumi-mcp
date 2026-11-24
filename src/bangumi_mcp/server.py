"""FastMCP server exposing Bangumi API v0 public read-only and authenticated write tools."""

from __future__ import annotations

import json
from typing import Any, Literal

try:
    from mcp.server.mcpserver import MCPServer as _BaseMCPServer

    _MCP_V2 = True
except ModuleNotFoundError:  # pragma: no cover - fallback for mcp 1.x
    from mcp.server.fastmcp import FastMCP as _BaseMCPServer  # type: ignore[no-redef]

    _MCP_V2 = False

from .client import AuthRequiredError, BangumiAPIError, BangumiClient, BangumiError
from .config import BangumiConfig
from .constants import (
    COLLECTION_TYPE_LABELS_ZH,
    COLLECTION_TYPES,
    EPISODE_COLLECTION_LABELS_ZH,
    EPISODE_COLLECTION_TYPES,
    VALID_BROWSE_SORTS,
    VALID_PERSON_CAREERS,
    VALID_SUBJECT_SORTS,
    parse_collection_type,
    parse_episode_collection_type,
    parse_episode_type,
    parse_subject_type,
    parse_subject_types,
    parse_weekday,
)
from .formatters import (
    BGM_WEB,
    format_calendar,
    format_character_detail,
    format_character_summary,
    format_episode,
    format_index,
    format_index_subject,
    format_person_detail,
    format_person_summary,
    format_related_character,
    format_related_person,
    format_related_subject,
    format_subject_detail,
    format_subject_summary,
    format_user,
    format_user_collection,
    format_user_episode,
)
from .services import (
    CollectionLibraryCache,
)
from .services import (
    check_user_collections as svc_check_user_collections,
)
from .services import (
    sync_user_collections as svc_sync_user_collections,
)


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _error_payload(exc: Exception) -> str:
    if isinstance(exc, AuthRequiredError):
        return _dump(
            {
                "error": True,
                "code": "AUTH_REQUIRED",
                "message": str(exc),
            }
        )
    if isinstance(exc, BangumiAPIError):
        return _dump(exc.to_dict())
    if isinstance(exc, (ValueError, BangumiError)):
        return _dump(
            {
                "error": True,
                "code": type(exc).__name__,
                "message": str(exc),
            }
        )
    return _dump(
        {
            "error": True,
            "code": type(exc).__name__,
            "message": f"Unexpected error: {exc}",
        }
    )


def _resolve_username(username: str | None, config: BangumiConfig) -> str:
    resolved = (username or "").strip() or config.default_username
    if not resolved:
        raise ValueError(
            "username is required (or set BANGUMI_DEFAULT_USERNAME in the environment)."
        )
    return resolved


def create_server(
    *,
    config: BangumiConfig | None = None,
    client: BangumiClient | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    streamable_http_path: str = "/mcp",
) -> Any:
    """Create and configure the Bangumi MCP server instance (supports mcp 2.x MCPServer & 1.x FastMCP)."""
    cfg = config or (client.config if client is not None else BangumiConfig.from_env())
    bgm = client or BangumiClient(config=cfg)
    cache = CollectionLibraryCache(ttl_seconds=cfg.cache_ttl)

    instructions = (
        "Bangumi (bgm.tv) API v0 MCP Server. "
        "Public read-only tools (search, subjects, episodes, calendar, characters, persons, "
        "user public collections, full sync, batch deduplication, indices) work without a token. "
        "Personal read/write tools require BANGUMI_ACCESS_TOKEN."
    )
    if _MCP_V2:
        mcp = _BaseMCPServer(
            name="bangumi-mcp",
            instructions=instructions,
        )
    else:  # pragma: no cover - mcp 1.x
        mcp = _BaseMCPServer(
            name="bangumi-mcp",
            instructions=instructions,
            host=host,
            port=port,
            streamable_http_path=streamable_http_path,
        )

    # ==================================================================
    # 1. Public Read-Only Tools (No Token Required)
    # ==================================================================

    @mcp.tool()
    async def search_subjects(
        keyword: str,
        subject_types: list[str | int] | None = None,
        sort: Literal["match", "heat", "rank", "score"] = "match",
        tags: list[str] | None = None,
        meta_tags: list[str] | None = None,
        air_date: list[str] | None = None,
        rating: list[str] | None = None,
        rating_count: list[str] | None = None,
        rank: list[str] | None = None,
        nsfw: bool | None = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        """Search Bangumi subjects (POST /v0/search/subjects).

        Args:
            keyword: Search query (Japanese, Chinese, or English title/keyword).
            subject_types: Optional filter list, e.g. ["anime"], ["book", "game"], or ints [1,2,3,4,6].
            sort: Sort order: "match" (default), "heat", "rank", or "score".
            tags: User tags filter (AND logic), e.g. ["科幻", "原创"].
            meta_tags: Public wiki meta tags (AND logic; prefix "-" to exclude, e.g. ["-科幻"]).
            air_date: Date range constraints (YYYY-MM-DD), e.g. [">=2024-01-01", "<2025-01-01"].
            rating: Score constraints, e.g. [">=8.0", "<9.5"].
            rating_count: Vote count constraints, e.g. [">=500"].
            rank: Rank constraints, e.g. [">=1", "<=200"].
            nsfw: Optional NSFW filter (ignored by Bangumi when unauthenticated).
            limit: Results per page (1-50, default 15).
            offset: Pagination offset (default 0).
        """
        try:
            if sort not in VALID_SUBJECT_SORTS:
                raise ValueError(f"sort must be one of {VALID_SUBJECT_SORTS}")
            parsed_types = parse_subject_types(subject_types)
            raw = await bgm.search_subjects(
                keyword,
                sort=sort,
                subject_types=parsed_types,
                tags=tags,
                meta_tags=meta_tags,
                air_date=air_date,
                rating=rating,
                rating_count=rating_count,
                rank=rank,
                nsfw=nsfw,
                limit=min(max(limit, 1), 50),
                offset=max(offset, 0),
            )
            items = [format_subject_summary(s) for s in (raw.get("data") or [])]
            return _dump(
                {
                    "total": raw.get("total", len(items)),
                    "limit": raw.get("limit", limit),
                    "offset": raw.get("offset", offset),
                    "count": len(items),
                    "items": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def browse_subjects(
        subject_type: str | int = "anime",
        sort: Literal["date", "rank"] | None = "rank",
        year: int | None = None,
        month: int | None = None,
        cat: int | None = None,
        platform: str | None = None,
        series: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> str:
        """Browse Bangumi subjects by type, year/month, or rank (GET /v0/subjects).

        Args:
            subject_type: "book"(1), "anime"(2), "music"(3), "game"(4), or "real"(6).
            sort: "rank" or "date".
            year: Optional release year, e.g. 2024.
            month: Optional release month (1-12).
            cat: Optional Bangumi SubjectCategory integer (e.g. anime: 1=TV, 2=OVA, 3=Movie, 5=WEB).
            platform: Platform filter (game subjects only).
            series: Series flag (book subjects only).
            limit: Results per page (1-50, default 20).
            offset: Pagination offset (default 0).
        """
        try:
            st = parse_subject_type(subject_type)
            if sort is not None and sort not in VALID_BROWSE_SORTS:
                raise ValueError(f"sort must be one of {VALID_BROWSE_SORTS}")
            raw = await bgm.browse_subjects(
                st,
                cat=cat,
                series=series,
                platform=platform,
                sort=sort,
                year=year,
                month=month,
                limit=min(max(limit, 1), 50),
                offset=max(offset, 0),
            )
            items = [format_subject_summary(s) for s in (raw.get("data") or [])]
            return _dump(
                {
                    "total": raw.get("total", len(items)),
                    "limit": raw.get("limit", limit),
                    "offset": raw.get("offset", offset),
                    "count": len(items),
                    "items": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_subject(subject_id: int) -> str:
        """Get compact, structured details for a Bangumi subject (GET /v0/subjects/{subject_id})."""
        try:
            raw = await bgm.get_subject(subject_id)
            return _dump(format_subject_detail(raw))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_subject_persons(subject_id: int, limit: int = 30) -> str:
        """Get staff/creators/studios associated with a subject (GET /v0/subjects/{subject_id}/persons)."""
        try:
            raw = await bgm.get_subject_persons(subject_id)
            items = [format_related_person(p) for p in raw[: max(limit, 1)]]
            return _dump(
                {
                    "subject_id": subject_id,
                    "total": len(raw),
                    "returned": len(items),
                    "persons": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_subject_characters(subject_id: int, limit: int = 30) -> str:
        """Get characters and their voice actors for a subject (GET /v0/subjects/{subject_id}/characters)."""
        try:
            raw = await bgm.get_subject_characters(subject_id)
            items = [format_related_character(c) for c in raw[: max(limit, 1)]]
            return _dump(
                {
                    "subject_id": subject_id,
                    "total": len(raw),
                    "returned": len(items),
                    "characters": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_subject_relations(subject_id: int, limit: int = 30) -> str:
        """Get related subjects (sequels, prequels, manga/novel adaptations, spin-offs) (GET /v0/subjects/{subject_id}/subjects)."""
        try:
            raw = await bgm.get_subject_relations(subject_id)
            items = [format_related_subject(r) for r in raw[: max(limit, 1)]]
            return _dump(
                {
                    "subject_id": subject_id,
                    "total": len(raw),
                    "returned": len(items),
                    "relations": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_episodes(
        subject_id: int,
        ep_type: str | int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """List episodes for a subject (GET /v0/episodes).

        Args:
            subject_id: Bangumi subject ID.
            ep_type: Optional filter: main(0), sp(1), op(2), ed(3), pv(4), mad(5), other(6).
            limit: Results per page (1-200, default 100).
            offset: Pagination offset (default 0).
        """
        try:
            parsed_ep_type = parse_episode_type(ep_type) if ep_type is not None else None
            raw = await bgm.get_episodes(
                subject_id,
                ep_type=parsed_ep_type,
                limit=min(max(limit, 1), 200),
                offset=max(offset, 0),
            )
            items = [format_episode(e) for e in (raw.get("data") or [])]
            return _dump(
                {
                    "subject_id": subject_id,
                    "total": raw.get("total", len(items)),
                    "limit": raw.get("limit", limit),
                    "offset": raw.get("offset", offset),
                    "count": len(items),
                    "episodes": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_episode(episode_id: int) -> str:
        """Get detailed info for a single episode (GET /v0/episodes/{episode_id})."""
        try:
            raw = await bgm.get_episode(episode_id)
            return _dump(format_episode(raw, include_desc=True))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_calendar(weekday: str | int | None = None) -> str:
        """Get Bangumi weekly airing broadcast calendar (GET /calendar).

        Args:
            weekday: Optional filter: 1-7 (Mon-Sun), "monday".."sunday", "周一".."周日", or "today".
        """
        try:
            wd = parse_weekday(weekday) if weekday is not None else None
            raw = await bgm.get_calendar()
            days = format_calendar(raw, weekday_filter=wd)
            return _dump({"days": days})
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def search_characters(
        keyword: str,
        nsfw: bool | None = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        """Search Bangumi characters (POST /v0/search/characters)."""
        try:
            raw = await bgm.search_characters(
                keyword,
                nsfw=nsfw,
                limit=min(max(limit, 1), 50),
                offset=max(offset, 0),
            )
            items = [format_character_summary(c) for c in (raw.get("data") or [])]
            return _dump(
                {
                    "total": raw.get("total", len(items)),
                    "count": len(items),
                    "characters": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_character(
        character_id: int,
        include_subjects: bool = True,
        include_persons: bool = True,
        relation_limit: int = 20,
    ) -> str:
        """Get character details, optionally with related subjects and voice actors."""
        try:
            detail = format_character_detail(await bgm.get_character(character_id))
            cap = max(relation_limit, 1)
            if include_subjects:
                subj = await bgm.get_character_subjects(character_id)
                detail["related_subjects"] = [format_related_subject(s) for s in subj[:cap]]
                detail["related_subjects_total"] = len(subj)
            if include_persons:
                persons = await bgm.get_character_persons(character_id)
                detail["related_persons"] = [
                    {
                        k: v
                        for k, v in {
                            "id": p.get("id"),
                            "name": p.get("name"),
                            "subject_id": p.get("subject_id"),
                            "subject_name": p.get("subject_name"),
                            "subject_name_cn": p.get("subject_name_cn"),
                            "staff": p.get("staff"),
                            "url": f"{BGM_WEB}/person/{p.get('id')}" if p.get("id") else None,
                        }.items()
                        if v is not None and v != ""
                    }
                    for p in persons[:cap]
                ]
                detail["related_persons_total"] = len(persons)
            return _dump(detail)
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def search_persons(
        keyword: str,
        career: list[str] | None = None,
        limit: int = 15,
        offset: int = 0,
    ) -> str:
        """Search real-world persons/studios (voice actors, directors, mangaka, etc.) (POST /v0/search/persons).

        Args:
            keyword: Person or studio name.
            career: Optional career filters (AND logic): producer, mangaka, artist, seiyu, writer, illustrator, actor.
            limit: Results per page (1-50, default 15).
            offset: Pagination offset.
        """
        try:
            if career:
                invalid = [c for c in career if c not in VALID_PERSON_CAREERS]
                if invalid:
                    raise ValueError(
                        f"Invalid career(s) {invalid}. Valid values: {VALID_PERSON_CAREERS}"
                    )
            raw = await bgm.search_persons(
                keyword,
                career=career,
                limit=min(max(limit, 1), 50),
                offset=max(offset, 0),
            )
            items = [format_person_summary(p) for p in (raw.get("data") or [])]
            return _dump(
                {
                    "total": raw.get("total", len(items)),
                    "count": len(items),
                    "persons": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_person(
        person_id: int,
        include_subjects: bool = True,
        include_characters: bool = True,
        relation_limit: int = 20,
    ) -> str:
        """Get person/studio details, optionally with related subjects and voiced characters."""
        try:
            detail = format_person_detail(await bgm.get_person(person_id))
            cap = max(relation_limit, 1)
            if include_subjects:
                subj = await bgm.get_person_subjects(person_id)
                detail["related_subjects"] = [format_related_subject(s) for s in subj[:cap]]
                detail["related_subjects_total"] = len(subj)
            if include_characters:
                chars = await bgm.get_person_characters(person_id)
                detail["related_characters"] = [
                    {
                        k: v
                        for k, v in {
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "subject_id": c.get("subject_id"),
                            "subject_name": c.get("subject_name"),
                            "subject_name_cn": c.get("subject_name_cn"),
                            "staff": c.get("staff"),
                            "url": f"{BGM_WEB}/character/{c.get('id')}" if c.get("id") else None,
                        }.items()
                        if v is not None and v != ""
                    }
                    for c in chars[:cap]
                ]
                detail["related_characters_total"] = len(chars)
            return _dump(detail)
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_user(username: str | None = None) -> str:
        """Get public profile for a Bangumi user (GET /v0/users/{username})."""
        try:
            uname = _resolve_username(username, cfg)
            raw = await bgm.get_user(uname)
            return _dump(format_user(raw))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_user_collections(
        username: str | None = None,
        subject_type: str | int | None = None,
        collection_type: str | int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> str:
        """Query a single page of a user's collections (GET /v0/users/{username}/collections).

        Args:
            username: Bangumi username (falls back to BANGUMI_DEFAULT_USERNAME).
            subject_type: Optional filter: book(1), anime(2), music(3), game(4), real(6).
            collection_type: Optional filter: wish(1), collect(2), doing(3), on_hold(4), dropped(5).
            limit: Items per page (1-50, default 30).
            offset: Pagination offset (default 0).
        """
        try:
            uname = _resolve_username(username, cfg)
            st = parse_subject_type(subject_type) if subject_type is not None else None
            ct = parse_collection_type(collection_type) if collection_type is not None else None
            raw = await bgm.get_user_collections(
                uname,
                subject_type=st,
                collection_type=ct,
                limit=min(max(limit, 1), 50),
                offset=max(offset, 0),
            )
            items = [format_user_collection(it) for it in (raw.get("data") or [])]
            return _dump(
                {
                    "username": uname,
                    "total": raw.get("total", len(items)),
                    "limit": raw.get("limit", limit),
                    "offset": raw.get("offset", offset),
                    "count": len(items),
                    "items": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_user_subject_collection(
        subject_id: int,
        username: str | None = None,
    ) -> str:
        """Get a user's collection record for a single subject (GET /v0/users/{username}/collections/{subject_id})."""
        try:
            uname = _resolve_username(username, cfg)
            raw = await bgm.get_user_subject_collection(uname, subject_id)
            return _dump(format_user_collection(raw, compact=False))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def sync_user_collections(
        username: str | None = None,
        subject_types: list[str | int] | None = None,
        include_favorites: bool = False,
        include_items: bool = True,
        max_items_returned: int = 100,
        refresh: bool = False,
        output_path: str | None = None,
    ) -> str:
        """Fetch all paginated collections across all 5 subject types (book/anime/music/game/real) with status statistics.

        Args:
            username: Bangumi username (falls back to BANGUMI_DEFAULT_USERNAME).
            subject_types: Optional subset of types (defaults to all 5: book, anime, music, game, real).
            include_favorites: Also fetch user's favorite characters and persons.
            include_items: Include compact item records in the tool output (False returns stats only).
            max_items_returned: Cap returned items in MCP response to avoid flooding context (default 100; full dataset is still cached and written if output_path is set).
            refresh: Bypass in-memory cache and re-fetch from Bangumi.
            output_path: Optional local JSON file path to save the full snapshot.
        """
        try:
            uname = _resolve_username(username, cfg)
            parsed_types = parse_subject_types(subject_types)
            full = await svc_sync_user_collections(
                bgm,
                uname,
                subject_types=parsed_types,
                include_user=True,
                include_favorites=include_favorites,
                compact=True,
                cache=cache,
                refresh=refresh,
                output_path=output_path,
            )
            response: dict[str, Any] = {
                "fetched_at": full["fetched_at"],
                "username": full["username"],
                "user": full.get("user"),
                "total_collections": full["total_collections"],
                "overall_by_status": full["overall_by_status"],
                "summary_by_type": full["summary_by_type"],
            }
            if "saved_to" in full:
                response["saved_to"] = full["saved_to"]
            if include_items:
                items = full["collections"]
                cap = max(max_items_returned, 0)
                response["items_returned"] = min(len(items), cap)
                response["truncated"] = len(items) > cap
                response["collections"] = items[:cap]
            if include_favorites:
                response["favorite_characters_count"] = len(full.get("favorite_characters") or [])
                response["favorite_persons_count"] = len(full.get("favorite_persons") or [])
                response["favorite_characters"] = (full.get("favorite_characters") or [])[:50]
                response["favorite_persons"] = (full.get("favorite_persons") or [])[:50]
            return _dump(response)
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def check_user_collections(
        items: list[str | int],
        username: str | None = None,
        subject_types: list[str | int] | None = None,
        resolve_unmatched_via_search: bool = True,
        refresh: bool = False,
    ) -> str:
        """Batch-check candidate titles or subject_ids against a user's Bangumi collections for recommendation deduplication.

        Returns each candidate's collection status (collect/doing/wish/on_hold/dropped/uncollected),
        user rating, episode progress, and comment so you never recommend already-watched or dropped titles.

        Args:
            items: List of Bangumi subject IDs (int/numeric string) and/or titles (CN/JP/EN).
            username: Bangumi username (falls back to BANGUMI_DEFAULT_USERNAME).
            subject_types: Optional subset of types to pull (e.g. ["anime"] for faster anime-only dedup; omit for all 5 types).
            resolve_unmatched_via_search: If a title isn't found directly in the library, resolve its subject_id via Bangumi search and re-check (default True).
            refresh: Bypass the 5-minute collection cache.
        """
        try:
            uname = _resolve_username(username, cfg)
            parsed_types = parse_subject_types(subject_types)
            report = await svc_check_user_collections(
                bgm,
                uname,
                items,
                subject_types=parsed_types,
                resolve_unmatched_via_search=resolve_unmatched_via_search,
                cache=cache,
                refresh=refresh,
            )
            return _dump(report)
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_user_favorites(
        username: str | None = None,
        kind: Literal["characters", "persons", "both"] = "both",
        limit: int = 30,
        offset: int = 0,
    ) -> str:
        """Get a user's favorited characters and/or persons."""
        try:
            uname = _resolve_username(username, cfg)
            lim = min(max(limit, 1), 50)
            off = max(offset, 0)
            result: dict[str, Any] = {"username": uname}
            if kind in ("characters", "both"):
                raw_c = await bgm.get_user_character_collections(uname, limit=lim, offset=off)
                result["characters"] = {
                    "total": raw_c.get("total", 0),
                    "items": [format_character_summary(c) for c in (raw_c.get("data") or [])],
                }
            if kind in ("persons", "both"):
                raw_p = await bgm.get_user_person_collections(uname, limit=lim, offset=off)
                result["persons"] = {
                    "total": raw_p.get("total", 0),
                    "items": [format_person_summary(p) for p in (raw_p.get("data") or [])],
                }
            return _dump(result)
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_index(
        index_id: int,
        include_subjects: bool = True,
        subject_type: str | int | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> str:
        """Get a Bangumi curated Index (目录) and optionally its subjects."""
        try:
            idx_raw = await bgm.get_index(index_id)
            out = format_index(idx_raw)
            if include_subjects:
                st = parse_subject_type(subject_type) if subject_type is not None else None
                subj_raw = await bgm.get_index_subjects(
                    index_id,
                    subject_type=st,
                    limit=min(max(limit, 1), 50),
                    offset=max(offset, 0),
                )
                items = [format_index_subject(s) for s in (subj_raw.get("data") or [])]
                out["subjects_total"] = subj_raw.get("total", len(items))
                out["subjects"] = items
            return _dump(out)
        except Exception as exc:
            return _error_payload(exc)

    # ==================================================================
    # 2. Authenticated Read/Write Tools (Require BANGUMI_ACCESS_TOKEN)
    # ==================================================================

    @mcp.tool()
    async def get_me() -> str:
        """Get the currently authenticated Bangumi user profile (GET /v0/me). Requires BANGUMI_ACCESS_TOKEN."""
        try:
            raw = await bgm.get_me()
            return _dump(format_user(raw))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def upsert_collection(
        subject_id: int,
        collection_type: str | int | None = None,
        rate: int | None = None,
        comment: str | None = None,
        tags: list[str] | None = None,
        private: bool | None = None,
        ep_status: int | None = None,
        vol_status: int | None = None,
        create_if_missing: bool = True,
    ) -> str:
        """Add or update the authenticated user's collection for a subject (POST/PATCH /v0/users/-/collections/{subject_id}).

        Requires BANGUMI_ACCESS_TOKEN.

        Args:
            subject_id: Target Bangumi subject ID.
            collection_type: Optional status: wish(1), collect(2), doing(3), on_hold(4), dropped(5).
            rate: Score 1-10, or 0 to remove rating.
            comment: Short review text.
            tags: List of tags (pass [] to clear all tags; tags cannot contain spaces).
            private: True to mark collection private (visible only to yourself).
            ep_status: Book chapter progress only (for anime episodes use update_episode_status/batch_update_episodes).
            vol_status: Book volume progress only.
            create_if_missing: True uses POST (upsert), False uses PATCH (update existing only).
        """
        try:
            ct = parse_collection_type(collection_type) if collection_type is not None else None
            if rate is not None and not (0 <= rate <= 10):
                raise ValueError("rate must be an integer between 0 and 10 (0 clears rating).")
            if tags is not None and any(" " in t for t in tags):
                raise ValueError("Bangumi tags cannot contain spaces.")
            await bgm.upsert_user_collection(
                subject_id,
                collection_type=ct,
                rate=rate,
                ep_status=ep_status,
                vol_status=vol_status,
                comment=comment,
                private=private,
                tags=tags,
                create_if_missing=create_if_missing,
            )
            cache.invalidate()
            return _dump(
                {
                    "ok": True,
                    "subject_id": subject_id,
                    "method": "POST" if create_if_missing else "PATCH",
                    "status": COLLECTION_TYPES.get(ct) if ct else None,
                    "status_zh": COLLECTION_TYPE_LABELS_ZH.get(ct) if ct else None,
                    "rate": rate,
                    "url": f"{BGM_WEB}/subject/{subject_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def get_episode_progress(
        subject_id: int | None = None,
        episode_id: int | None = None,
        ep_type: str | int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """Read the authenticated user's episode watch progress for a subject or single episode.

        Requires BANGUMI_ACCESS_TOKEN. Pass either subject_id or episode_id.
        """
        try:
            if episode_id is not None:
                raw = await bgm.get_user_episode(episode_id)
                return _dump(format_user_episode(raw))
            if subject_id is None:
                raise ValueError("Provide either subject_id or episode_id.")
            parsed_ep_type = parse_episode_type(ep_type) if ep_type is not None else None
            raw = await bgm.get_user_subject_episodes(
                subject_id,
                episode_type=parsed_ep_type,
                limit=min(max(limit, 1), 1000),
                offset=max(offset, 0),
            )
            items = [format_user_episode(e) for e in (raw.get("data") or [])]
            return _dump(
                {
                    "subject_id": subject_id,
                    "total": raw.get("total", len(items)),
                    "count": len(items),
                    "episodes": items,
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def update_episode_status(
        episode_id: int,
        status: str | int = "done",
    ) -> str:
        """Update watch status for a single episode (PUT /v0/users/-/collections/-/episodes/{episode_id}).

        Requires BANGUMI_ACCESS_TOKEN.

        Args:
            episode_id: Target episode ID.
            status: none(0), wish(1), done(2, default), or dropped(3).
        """
        try:
            st = parse_episode_collection_type(status)
            await bgm.update_user_episode(episode_id, st)
            return _dump(
                {
                    "ok": True,
                    "episode_id": episode_id,
                    "watch_status": EPISODE_COLLECTION_TYPES[st],
                    "watch_status_zh": EPISODE_COLLECTION_LABELS_ZH[st],
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def batch_update_episodes(
        subject_id: int,
        episode_ids: list[int],
        status: str | int = "done",
    ) -> str:
        """Batch update watch status for multiple episodes of a subject (PATCH /v0/users/-/collections/{subject_id}/episodes).

        Requires BANGUMI_ACCESS_TOKEN. Recalculates subject completion automatically.

        Args:
            subject_id: Subject ID owning the episodes.
            episode_ids: Non-empty list of episode IDs to update.
            status: none(0), wish(1), done(2, default), or dropped(3).
        """
        try:
            if not episode_ids:
                raise ValueError("episode_ids must be a non-empty list of integers.")
            st = parse_episode_collection_type(status)
            await bgm.batch_update_user_episodes(subject_id, episode_ids, st)
            return _dump(
                {
                    "ok": True,
                    "subject_id": subject_id,
                    "updated_count": len(episode_ids),
                    "episode_ids": episode_ids,
                    "watch_status": EPISODE_COLLECTION_TYPES[st],
                    "watch_status_zh": EPISODE_COLLECTION_LABELS_ZH[st],
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def set_character_collection(
        character_id: int,
        collect: bool = True,
    ) -> str:
        """Collect (favorite) or uncollect a character for the authenticated user. Requires BANGUMI_ACCESS_TOKEN."""
        try:
            if collect:
                await bgm.collect_character(character_id)
            else:
                await bgm.uncollect_character(character_id)
            return _dump(
                {
                    "ok": True,
                    "character_id": character_id,
                    "collected": collect,
                    "url": f"{BGM_WEB}/character/{character_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def set_person_collection(
        person_id: int,
        collect: bool = True,
    ) -> str:
        """Collect (favorite) or uncollect a person/studio for the authenticated user. Requires BANGUMI_ACCESS_TOKEN."""
        try:
            if collect:
                await bgm.collect_person(person_id)
            else:
                await bgm.uncollect_person(person_id)
            return _dump(
                {
                    "ok": True,
                    "person_id": person_id,
                    "collected": collect,
                    "url": f"{BGM_WEB}/person/{person_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def create_index(
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a new Bangumi Index (目录) and optionally set its title and description. Requires BANGUMI_ACCESS_TOKEN."""
        try:
            raw = await bgm.create_index(title=title, description=description)
            return _dump(format_index(raw))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def update_index(
        index_id: int,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        """Edit a Bangumi Index's title and/or description (PUT /v0/indices/{index_id}). Requires BANGUMI_ACCESS_TOKEN."""
        try:
            if title is None and description is None:
                raise ValueError("Provide at least one of title or description.")
            raw = await bgm.update_index(index_id, title=title, description=description)
            return _dump(format_index(raw))
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def add_index_subject(
        index_id: int,
        subject_id: int,
        sort: int | None = None,
        comment: str | None = None,
    ) -> str:
        """Add a subject to a Bangumi Index (POST /v0/indices/{index_id}/subjects). Requires BANGUMI_ACCESS_TOKEN."""
        try:
            await bgm.add_index_subject(index_id, subject_id, sort=sort, comment=comment)
            return _dump(
                {
                    "ok": True,
                    "index_id": index_id,
                    "subject_id": subject_id,
                    "action": "added",
                    "url": f"{BGM_WEB}/index/{index_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def update_index_subject(
        index_id: int,
        subject_id: int,
        sort: int | None = None,
        comment: str | None = None,
    ) -> str:
        """Update a subject's sort order or comment inside an Index (PUT /v0/indices/{index_id}/subjects/{subject_id}). Requires BANGUMI_ACCESS_TOKEN."""
        try:
            await bgm.update_index_subject(index_id, subject_id, sort=sort, comment=comment)
            return _dump(
                {
                    "ok": True,
                    "index_id": index_id,
                    "subject_id": subject_id,
                    "action": "updated",
                    "url": f"{BGM_WEB}/index/{index_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def remove_index_subject(
        index_id: int,
        subject_id: int,
    ) -> str:
        """Remove a subject from a Bangumi Index (DELETE /v0/indices/{index_id}/subjects/{subject_id}). Requires BANGUMI_ACCESS_TOKEN."""
        try:
            await bgm.remove_index_subject(index_id, subject_id)
            return _dump(
                {
                    "ok": True,
                    "index_id": index_id,
                    "subject_id": subject_id,
                    "action": "removed",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    @mcp.tool()
    async def set_index_collection(
        index_id: int,
        collect: bool = True,
    ) -> str:
        """Collect (bookmark) or uncollect a Bangumi Index for the authenticated user. Requires BANGUMI_ACCESS_TOKEN."""
        try:
            if collect:
                await bgm.collect_index(index_id)
            else:
                await bgm.uncollect_index(index_id)
            return _dump(
                {
                    "ok": True,
                    "index_id": index_id,
                    "collected": collect,
                    "url": f"{BGM_WEB}/index/{index_id}",
                }
            )
        except Exception as exc:
            return _error_payload(exc)

    return mcp
