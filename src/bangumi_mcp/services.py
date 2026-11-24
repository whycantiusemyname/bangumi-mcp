"""Higher-level Bangumi domain services: full collection sync, caching, and batch deduplication."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import BangumiClient, BangumiError
from .constants import (
    COLLECTION_TYPE_LABELS_ZH,
    COLLECTION_TYPES,
    SUBJECT_TYPES,
)
from .formatters import (
    BGM_WEB,
    format_character_summary,
    format_person_summary,
    format_subject_summary,
    format_user,
    format_user_collection,
)

ALL_SUBJECT_TYPE_IDS: tuple[int, ...] = (1, 2, 3, 4, 6)

_NORM_STRIP_RE = re.compile(
    r"[\s\-—–_·・•:：;；!！?？,，.。、'\"`~～/\\|()（）\[\]【】「」『』《》<>〈〉★☆♥♡+]+"
)
_EXPLICIT_ID_RE = re.compile(r"^(?:id:|#)(\d+)$", re.IGNORECASE)
_SEASON_TOKEN_RE = re.compile(
    r"(?:"
    r"第\s*[二三四五六七八九十2-9]\s*[季期部章]"
    r"|season\s*[2-9]"
    r"|part\s*[2-9]"
    r"|cour\s*[2-9]"
    r"|(?<![a-z0-9])(?:ii|iii|iv|ova|oad|movie|剧场版|总集篇|外传|前篇|后篇|完结篇)(?![a-z0-9])"
    r"|(?<=\D)[2-9]$"
    r")",
    re.IGNORECASE,
)


def normalize_title(text: str | None) -> str:
    """Normalize anime/book/game titles for resilient cross-punctuation matching."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).strip().lower()
    return _NORM_STRIP_RE.sub("", s)


def _extract_season_markers(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    s = unicodedata.normalize("NFKC", text).strip().lower()
    return tuple(sorted({m.group(0).strip() for m in _SEASON_TOKEN_RE.finditer(s)}))


@dataclass(frozen=True)
class CachedCollectionLibrary:
    """Normalized, read-only cached snapshot of a user's collections with prebuilt lookup indices."""

    username: str
    subject_types: tuple[int, ...]
    fetched_at: str
    collections: list[dict[str, Any]]
    summary_by_type: dict[str, Any]
    overall_by_status: dict[str, int]
    complete: bool
    warnings: list[str]
    by_id: dict[int, dict[str, Any]]
    by_norm: dict[str, list[dict[str, Any]]]
    norm_entries: list[tuple[str, tuple[str, ...], dict[str, Any]]]


def _build_collection_indices(
    collections: list[dict[str, Any]],
) -> tuple[
    dict[int, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[tuple[str, tuple[str, ...], dict[str, Any]]],
]:
    by_id: dict[int, dict[str, Any]] = {}
    by_norm: dict[str, list[dict[str, Any]]] = {}
    norm_entries: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []

    for item in collections:
        sid = item.get("subject_id")
        if isinstance(sid, int):
            by_id[sid] = item
        seen_norms_for_item: set[str] = set()
        for title_field in ("name_cn", "name"):
            raw_title = item.get(title_field)
            norm = normalize_title(raw_title)
            if norm and norm not in seen_norms_for_item:
                seen_norms_for_item.add(norm)
                by_norm.setdefault(norm, []).append(item)
                norm_entries.append((norm, _extract_season_markers(raw_title), item))

    return by_id, by_norm, norm_entries


class CollectionLibraryCache:
    """In-memory TTL cache with epoch invalidation and concurrent in-flight coalescing."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[tuple[str, tuple[int, ...]], tuple[float, CachedCollectionLibrary]] = {}
        self._inflight: dict[tuple[str, tuple[int, ...]], asyncio.Task[CachedCollectionLibrary]] = {}
        self._generation: int = 0

    @property
    def generation(self) -> int:
        return self._generation

    def get(self, username: str, subject_types: tuple[int, ...]) -> CachedCollectionLibrary | None:
        if self.ttl_seconds <= 0:
            return None
        key = (username.lower(), subject_types)
        entry = self._store.get(key)
        if not entry:
            return None
        ts, data = entry
        if time.monotonic() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        return data

    def set_if_fresh(
        self,
        username: str,
        subject_types: tuple[int, ...],
        data: CachedCollectionLibrary,
        *,
        expected_generation: int,
    ) -> None:
        if self.ttl_seconds <= 0 or not data.complete:
            return
        if self._generation != expected_generation:
            # A write/invalidation occurred while this fetch was in flight; do not cache stale data
            return
        key = (username.lower(), subject_types)
        self._store[key] = (time.monotonic(), data)

    def invalidate(self, username: str | None = None) -> None:
        self._generation += 1
        if username is None:
            self._store.clear()
            return
        low = username.lower()
        for key in [k for k in self._store if k[0] == low]:
            self._store.pop(key, None)

    async def get_or_fetch(
        self,
        username: str,
        subject_types: tuple[int, ...],
        fetcher: Any,
        *,
        refresh: bool = False,
    ) -> CachedCollectionLibrary:
        if not refresh:
            cached = self.get(username, subject_types)
            if cached is not None:
                return cached

        key = (username.lower(), subject_types)
        if not refresh and key in self._inflight:
            return await self._inflight[key]

        gen_before = self._generation

        async def _run() -> CachedCollectionLibrary:
            lib = await fetcher()
            self.set_if_fresh(username, subject_types, lib, expected_generation=gen_before)
            return lib

        task = asyncio.create_task(_run())
        if not refresh:
            self._inflight[key] = task
        try:
            return await task
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)


@dataclass(frozen=True)
class PageFetchResult:
    items: list[dict[str, Any]]
    total_reported: int
    complete: bool
    warnings: list[str]


async def _fetch_all_pages(
    fetch_page: Any,
    *,
    page_size: int = 50,
    page_delay: float = 0.2,
    max_pages: int = 200,
    label: str = "items",
) -> PageFetchResult:
    """Offset paginator resilient to upstream short intermediate pages.

    Bangumi counts collections first, fetches a page slice, then omits items whose linked
    subject/character/person record is missing. Therefore len(batch) < limit does NOT imply
    EOF; we advance by offset + limit until offset >= total_reported.
    """
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    offset = 0
    total_reported: int | None = None
    consecutive_empty = 0
    complete = True

    for page_idx in range(max_pages):
        page = await fetch_page(limit=page_size, offset=offset)
        if not isinstance(page, dict):
            complete = False
            warnings.append(f"{label}: unexpected non-object page response at offset {offset}.")
            break

        if total_reported is None:
            raw_total = page.get("total")
            if not isinstance(raw_total, int) or raw_total < 0:
                complete = False
                warnings.append(f"{label}: missing/invalid total metadata at offset {offset}.")
                total_reported = 0
            else:
                total_reported = raw_total

        batch = page.get("data")
        if not isinstance(batch, list):
            complete = False
            warnings.append(f"{label}: missing/invalid data array at offset {offset}.")
            break

        if batch:
            consecutive_empty = 0
            items.extend(batch)
        else:
            consecutive_empty += 1

        step = page_size
        raw_limit = page.get("limit")
        if isinstance(raw_limit, int) and raw_limit > 0:
            step = raw_limit
        offset += step

        if offset >= total_reported:
            break

        if consecutive_empty >= 2:
            complete = False
            warnings.append(
                f"{label}: stopped early after {consecutive_empty} consecutive empty pages "
                f"at offset {offset}/{total_reported}."
            )
            break

        if page_idx + 1 >= max_pages:
            complete = False
            warnings.append(
                f"{label}: reached max_pages={max_pages} cap at offset {offset}/{total_reported}."
            )
            break

        if page_delay > 0:
            await asyncio.sleep(page_delay)

    final_total = int(total_reported or 0)
    if complete and offset < final_total:
        complete = False
        warnings.append(
            f"{label}: pagination ended at offset {offset} below reported total {final_total}."
        )

    return PageFetchResult(
        items=items,
        total_reported=final_total,
        complete=complete,
        warnings=warnings,
    )


async def _fetch_collection_library(
    client: BangumiClient,
    username: str,
    type_ids: tuple[int, ...],
    *,
    page_size: int = 50,
    compact: bool = True,
) -> tuple[CachedCollectionLibrary, list[dict[str, Any]]]:
    all_raw: list[dict[str, Any]] = []
    summary_by_type: dict[str, Any] = {}
    overall_by_status: dict[str, int] = {name: 0 for name in COLLECTION_TYPES.values()}
    all_warnings: list[str] = []
    all_complete = True

    capped_page_size = min(max(page_size, 1), 50)
    for idx, st_id in enumerate(type_ids):
        st_name = SUBJECT_TYPES[st_id]
        res = await _fetch_all_pages(
            lambda limit, offset, _st=st_id: client.get_user_collections(
                username,
                subject_type=_st,
                limit=limit,
                offset=offset,
            ),
            page_size=capped_page_size,
            page_delay=client.config.page_delay,
            label=st_name,
        )
        if not res.complete:
            all_complete = False
        all_warnings.extend(res.warnings)

        by_status: dict[str, int] = {}
        for it in res.items:
            st_key = COLLECTION_TYPES.get(it.get("type"), str(it.get("type")))
            by_status[st_key] = by_status.get(st_key, 0) + 1
            if st_key in overall_by_status:
                overall_by_status[st_key] += 1

        type_summary: dict[str, Any] = {
            "total_reported": res.total_reported,
            "fetched": len(res.items),
            "complete": res.complete,
            "by_status": by_status,
        }
        if res.complete and len(res.items) < res.total_reported:
            type_summary["skipped_unavailable"] = res.total_reported - len(res.items)
        summary_by_type[st_name] = type_summary
        all_raw.extend(res.items)

        if client.config.page_delay > 0 and idx + 1 < len(type_ids):
            await asyncio.sleep(client.config.page_delay)

    tz_cn = timezone(timedelta(hours=8))
    compacted = [format_user_collection(it, compact=True) for it in all_raw]
    by_id, by_norm, norm_entries = _build_collection_indices(compacted)
    lib = CachedCollectionLibrary(
        username=username,
        subject_types=type_ids,
        fetched_at=datetime.now(tz_cn).isoformat(timespec="seconds"),
        collections=compacted,
        summary_by_type=summary_by_type,
        overall_by_status={k: v for k, v in overall_by_status.items() if v > 0},
        complete=all_complete,
        warnings=all_warnings,
        by_id=by_id,
        by_norm=by_norm,
        norm_entries=norm_entries,
    )
    return lib, (compacted if compact else all_raw)


async def sync_user_collections(
    client: BangumiClient,
    username: str,
    *,
    subject_types: list[int] | None = None,
    include_user: bool = True,
    include_favorites: bool = False,
    compact: bool = True,
    page_size: int = 50,
    cache: CollectionLibraryCache | None = None,
    refresh: bool = False,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch full paginated collections across requested subject types (all 5 by default).

    Cache stores only the normalized collection library (never user profile, favorites, or
    export metadata) and never caches incomplete snapshots.
    """
    type_ids = tuple(subject_types) if subject_types else ALL_SUBJECT_TYPE_IDS

    if cache is not None and compact:
        lib = await cache.get_or_fetch(
            username,
            type_ids,
            lambda: _fetch_lib_only(client, username, type_ids, page_size=page_size),
            refresh=refresh,
        )
        collections_out = lib.collections
    else:
        lib, collections_out = await _fetch_collection_library(
            client, username, type_ids, page_size=page_size, compact=compact
        )

    user_raw = await client.get_user(username) if include_user else None

    warnings = list(lib.warnings)
    complete = lib.complete
    fav_chars_res: PageFetchResult | None = None
    fav_persons_res: PageFetchResult | None = None
    if include_favorites:
        fav_chars_res = await _fetch_all_pages(
            lambda limit, offset: client.get_user_character_collections(
                username, limit=limit, offset=offset
            ),
            page_size=50,
            page_delay=client.config.page_delay,
            max_pages=40,
            label="favorite_characters",
        )
        fav_persons_res = await _fetch_all_pages(
            lambda limit, offset: client.get_user_person_collections(
                username, limit=limit, offset=offset
            ),
            page_size=50,
            page_delay=client.config.page_delay,
            max_pages=40,
            label="favorite_persons",
        )
        if not fav_chars_res.complete or not fav_persons_res.complete:
            complete = False
        warnings.extend(fav_chars_res.warnings)
        warnings.extend(fav_persons_res.warnings)

    payload: dict[str, Any] = {
        "fetched_at": lib.fetched_at,
        "username": username,
        "user": (format_user(user_raw) if (user_raw and compact) else user_raw),
        "complete": complete,
        "total_collections": len(collections_out),
        "overall_by_status": dict(lib.overall_by_status),
        "summary_by_type": dict(lib.summary_by_type),
        "collections": list(collections_out),
    }
    if warnings:
        payload["warnings"] = warnings
    if include_favorites and fav_chars_res is not None and fav_persons_res is not None:
        payload["favorite_characters"] = (
            [format_character_summary(c) for c in fav_chars_res.items]
            if compact
            else fav_chars_res.items
        )
        payload["favorite_persons"] = (
            [format_person_summary(p) for p in fav_persons_res.items]
            if compact
            else fav_persons_res.items
        )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["saved_to"] = str(out.resolve())

    return payload


async def _fetch_lib_only(
    client: BangumiClient,
    username: str,
    type_ids: tuple[int, ...],
    *,
    page_size: int = 50,
) -> CachedCollectionLibrary:
    lib, _ = await _fetch_collection_library(
        client, username, type_ids, page_size=page_size, compact=True
    )
    return lib


def _find_conservative_fuzzy_matches(
    norm_query: str,
    query_seasons: tuple[str, ...],
    norm_entries: list[tuple[str, tuple[str, ...], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Conservative substring matching that avoids cross-season false positives."""
    if len(norm_query) < 3:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    seen_ids: set[int] = set()
    for norm_title, title_seasons, item in norm_entries:
        if len(norm_title) < 3:
            continue
        # Never confuse season 1 with season 2 / OVA / movie
        if query_seasons != title_seasons:
            continue
        if norm_query in norm_title or norm_title in norm_query:
            shorter = min(len(norm_query), len(norm_title))
            longer = max(len(norm_query), len(norm_title))
            if shorter / longer >= 0.65:
                sid = item.get("subject_id")
                if isinstance(sid, int) and sid in seen_ids:
                    continue
                if isinstance(sid, int):
                    seen_ids.add(sid)
                scored.append((longer - shorter, item))

    if not scored:
        return []
    scored.sort(key=lambda pair: pair[0])
    best_diff = scored[0][0]
    return [item for diff, item in scored if diff == best_diff]


def _format_match_result(
    query: int | str,
    item: dict[str, Any],
    *,
    matched_by: str,
    other_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = item.get("status")
    status_zh = item.get("status_zh") or (
        COLLECTION_TYPE_LABELS_ZH.get(item.get("type"))
        if isinstance(item.get("type"), int)
        else None
    )
    out: dict[str, Any] = {
        "query": query,
        "collected": True,
        "status": status,
        "status_zh": status_zh,
        "matched_by": matched_by,
        "subject_id": item.get("subject_id"),
        "subject_type": item.get("subject_type"),
        "name": item.get("name"),
        "name_cn": item.get("name_cn"),
        "rate": item.get("rate"),
        "ep_status": item.get("ep_status"),
        "tags": item.get("tags"),
        "comment": item.get("comment"),
        "url": item.get("url") or f"{BGM_WEB}/subject/{item.get('subject_id')}",
    }
    if other_matches:
        out["ambiguous"] = True
        out["other_matches"] = [
            {
                k: v
                for k, v in {
                    "subject_id": m.get("subject_id"),
                    "subject_type": m.get("subject_type"),
                    "status": m.get("status"),
                    "status_zh": m.get("status_zh"),
                    "name": m.get("name"),
                    "name_cn": m.get("name_cn"),
                    "rate": m.get("rate"),
                }.items()
                if v is not None and v != ""
            }
            for m in other_matches[:5]
        ]
    return {k: v for k, v in out.items() if v is not None and v != "" and v != []}


def _parse_id_query(raw_query: int | str) -> tuple[int | None, bool]:
    """Return (parsed_id, is_strict_id).

    - Python int or explicit 'id:123'/'#123' -> strict subject_id.
    - Pure digit string with >= 4 digits -> likely subject_id (CLI convenience), checked by ID first.
    - Short pure digit string like '86' -> NOT treated as strict ID (could be title '86');
      still checked in by_id only if exact match, else falls through to title/search.
    """
    if isinstance(raw_query, int) and not isinstance(raw_query, bool):
        return raw_query, True
    s = str(raw_query).strip()
    m = _EXPLICIT_ID_RE.match(s)
    if m:
        return int(m.group(1)), True
    if s.isdigit():
        return int(s), len(s) >= 4
    return None, False


def _pick_identity_from_search(
    query_str: str, hits: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str]:
    """Resolve the canonical subject identity from search hits BEFORE checking collections.

    Never picks a lower-ranked hit just because it happens to be in the user's collection.
    """
    if not hits:
        return None, "none"
    norm_q = normalize_title(query_str)
    query_seasons = _extract_season_markers(query_str)

    # Prefer exact normalized title hit with matching season markers
    for hit in hits:
        for field in ("name_cn", "name"):
            raw_title = hit.get(field)
            if normalize_title(raw_title) == norm_q and _extract_season_markers(raw_title) == query_seasons:
                return hit, "exact_search"

    # Otherwise trust only the #1 ranked search hit
    return hits[0], "top_search"


async def check_user_collections(
    client: BangumiClient,
    username: str,
    items: list[int | str],
    *,
    subject_types: list[int] | None = None,
    resolve_unmatched_via_search: bool = True,
    cache: CollectionLibraryCache | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Batch-check candidate subject IDs or titles against a user's Bangumi collections.

    Separates subject identity resolution from collection status lookup:
    1. Explicit IDs (`int`, `id:123`, `#123`, or >=4-digit numeric string) lookup `by_id`.
    2. Title queries check exact normalized library titles (surfacing ambiguity if multiple types share a name),
       then conservative same-season fuzzy matching.
    3. Remaining titles optionally resolve canonical identity via Bangumi search (batch-deduplicated),
       then look up THAT canonical subject_id in `by_id`. Search errors return `status="unknown"` rather
       than falsely claiming `uncollected`.
    """
    type_ids = tuple(subject_types) if subject_types else ALL_SUBJECT_TYPE_IDS
    if cache is not None:
        lib = await cache.get_or_fetch(
            username,
            type_ids,
            lambda: _fetch_lib_only(client, username, type_ids),
            refresh=refresh,
        )
    else:
        lib = await _fetch_lib_only(client, username, type_ids)

    results: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    uncollected_queries: list[int | str] = []
    unknown_queries: list[int | str] = []
    search_memo: dict[str, tuple[list[dict[str, Any]] | None, str | None]] = {}

    for raw_query in items:
        parsed_id, is_strict_id = _parse_id_query(raw_query)

        # 1. Strict subject_id lookup
        if is_strict_id and parsed_id is not None:
            if parsed_id in lib.by_id:
                entry = _format_match_result(raw_query, lib.by_id[parsed_id], matched_by="subject_id")
                st = str(entry.get("status") or "collected")
                status_counts[st] = status_counts.get(st, 0) + 1
                results.append(entry)
            else:
                status_counts["uncollected"] = status_counts.get("uncollected", 0) + 1
                uncollected_queries.append(raw_query)
                results.append(
                    {
                        "query": raw_query,
                        "collected": False,
                        "status": "uncollected",
                        "status_zh": "未收藏",
                        "subject_id": parsed_id,
                        "url": f"{BGM_WEB}/subject/{parsed_id}",
                    }
                )
            continue

        # 2. Title lookup (exact normalized -> conservative same-season fuzzy)
        query_str = str(raw_query).strip()
        norm_q = normalize_title(query_str)
        query_seasons = _extract_season_markers(query_str)

        exact_hits = lib.by_norm.get(norm_q) if norm_q else None
        if exact_hits:
            entry = _format_match_result(
                raw_query,
                exact_hits[0],
                matched_by="exact_title",
                other_matches=exact_hits[1:] if len(exact_hits) > 1 else None,
            )
            st = str(entry.get("status") or "collected")
            status_counts[st] = status_counts.get(st, 0) + 1
            results.append(entry)
            continue

        fuzzy_hits = (
            _find_conservative_fuzzy_matches(norm_q, query_seasons, lib.norm_entries)
            if norm_q
            else []
        )
        if len(fuzzy_hits) == 1:
            entry = _format_match_result(raw_query, fuzzy_hits[0], matched_by="fuzzy_title")
            st = str(entry.get("status") or "collected")
            status_counts[st] = status_counts.get(st, 0) + 1
            results.append(entry)
            continue

        # 3. Optional search-assisted identity resolution (batch-deduplicated)
        resolved_candidate: dict[str, Any] | None = None
        if resolve_unmatched_via_search and query_str:
            memo_key = norm_q or query_str.lower()
            if memo_key not in search_memo:
                try:
                    search_resp = await client.search_subjects(
                        query_str,
                        subject_types=list(subject_types) if subject_types else None,
                        limit=5,
                    )
                    search_memo[memo_key] = ((search_resp or {}).get("data") or [], None)
                except (BangumiError, Exception) as exc:
                    search_memo[memo_key] = (None, str(exc))

            hits, search_err = search_memo[memo_key]
            if search_err is not None:
                status_counts["unknown"] = status_counts.get("unknown", 0) + 1
                unknown_queries.append(raw_query)
                results.append(
                    {
                        "query": raw_query,
                        "collected": None,
                        "status": "unknown",
                        "status_zh": "核验失败",
                        "error": f"Search resolution failed: {search_err}",
                    }
                )
                continue

            canonical_hit, _ = _pick_identity_from_search(query_str, hits or [])
            if canonical_hit is not None:
                resolved_candidate = format_subject_summary(canonical_hit, max_summary_len=120)
                hit_id = canonical_hit.get("id")
                if isinstance(hit_id, int) and hit_id in lib.by_id:
                    entry = _format_match_result(
                        raw_query,
                        lib.by_id[hit_id],
                        matched_by="search_resolved",
                    )
                    st = str(entry.get("status") or "collected")
                    status_counts[st] = status_counts.get(st, 0) + 1
                    results.append(entry)
                    continue

        # Not found in collection library
        status_counts["uncollected"] = status_counts.get("uncollected", 0) + 1
        uncollected_queries.append(raw_query)
        uncollected_entry: dict[str, Any] = {
            "query": raw_query,
            "collected": False,
            "status": "uncollected",
            "status_zh": "未收藏",
        }
        if resolved_candidate is not None:
            uncollected_entry["resolved_candidate"] = resolved_candidate
        if len(fuzzy_hits) > 1:
            uncollected_entry["possible_library_matches"] = [
                {
                    "subject_id": m.get("subject_id"),
                    "name": m.get("name"),
                    "name_cn": m.get("name_cn"),
                    "status": m.get("status"),
                }
                for m in fuzzy_hits[:5]
            ]
        results.append(uncollected_entry)

    collected_count = len(items) - len(uncollected_queries) - len(unknown_queries)
    report: dict[str, Any] = {
        "username": username,
        "library_total": len(lib.collections),
        "library_complete": lib.complete,
        "checked_count": len(items),
        "collected_count": collected_count,
        "uncollected_count": len(uncollected_queries),
        "unknown_count": len(unknown_queries),
        "status_counts": status_counts,
        "uncollected_items": uncollected_queries,
        "results": results,
    }
    if unknown_queries:
        report["unknown_items"] = unknown_queries
    if lib.warnings:
        report["warnings"] = list(lib.warnings)
    return report
