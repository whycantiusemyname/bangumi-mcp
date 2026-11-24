"""Higher-level Bangumi domain services: full collection sync, caching, and batch deduplication."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import BangumiClient
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


def normalize_title(text: str | None) -> str:
    """Normalize anime/book/game titles for resilient cross-punctuation matching."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).strip().lower()
    return _NORM_STRIP_RE.sub("", s)


class CollectionLibraryCache:
    """Simple in-memory TTL cache for full user collection snapshots."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[tuple[str, tuple[int, ...]], tuple[float, dict[str, Any]]] = {}

    def get(self, username: str, subject_types: tuple[int, ...]) -> dict[str, Any] | None:
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

    def set(self, username: str, subject_types: tuple[int, ...], data: dict[str, Any]) -> None:
        if self.ttl_seconds <= 0:
            return
        key = (username.lower(), subject_types)
        self._store[key] = (time.monotonic(), data)

    def invalidate(self, username: str | None = None) -> None:
        if username is None:
            self._store.clear()
            return
        low = username.lower()
        for key in [k for k in self._store if k[0] == low]:
            self._store.pop(key, None)


async def _fetch_all_pages(
    fetch_page: Any,
    *,
    page_size: int = 50,
    page_delay: float = 0.2,
    max_pages: int = 200,
) -> tuple[list[dict[str, Any]], int]:
    """Generic offset-based paginator for Bangumi Paged endpoints."""
    items: list[dict[str, Any]] = []
    offset = 0
    total_reported: int | None = None

    for page_idx in range(max_pages):
        page = await fetch_page(limit=page_size, offset=offset)
        if not page or not isinstance(page, dict):
            break
        if total_reported is None:
            total_reported = int(page.get("total", 0))
        batch = page.get("data") or []
        if not batch:
            break
        items.extend(batch)
        offset += len(batch)
        if offset >= total_reported or len(batch) < page_size:
            break
        if page_delay > 0 and page_idx + 1 < max_pages:
            await asyncio.sleep(page_delay)

    return items, int(total_reported or 0)


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

    Upgrades refresh_bangumi.py with async pagination, per-type/overall status breakdown,
    optional favorite characters/persons, caching, and optional JSON export.
    """
    type_ids = tuple(subject_types) if subject_types else ALL_SUBJECT_TYPE_IDS

    if cache is not None and not refresh and not include_favorites and output_path is None:
        cached = cache.get(username, type_ids)
        if cached is not None:
            return cached

    user_raw = await client.get_user(username) if include_user else None

    all_raw: list[dict[str, Any]] = []
    summary_by_type: dict[str, Any] = {}
    overall_by_status: dict[str, int] = {name: 0 for name in COLLECTION_TYPES.values()}

    for idx, st_id in enumerate(type_ids):
        st_name = SUBJECT_TYPES[st_id]
        items, total_reported = await _fetch_all_pages(
            lambda limit, offset, _st=st_id: client.get_user_collections(
                username,
                subject_type=_st,
                limit=limit,
                offset=offset,
            ),
            page_size=min(max(page_size, 1), 50),
            page_delay=client.config.page_delay,
        )
        by_status: dict[str, int] = {}
        for it in items:
            st_key = COLLECTION_TYPES.get(it.get("type"), str(it.get("type")))
            by_status[st_key] = by_status.get(st_key, 0) + 1
            if st_key in overall_by_status:
                overall_by_status[st_key] += 1

        summary_by_type[st_name] = {
            "total_reported": total_reported,
            "fetched": len(items),
            "by_status": by_status,
        }
        all_raw.extend(items)
        if client.config.page_delay > 0 and idx + 1 < len(type_ids):
            await asyncio.sleep(client.config.page_delay)

    fav_chars_raw: list[dict[str, Any]] = []
    fav_persons_raw: list[dict[str, Any]] = []
    if include_favorites:
        fav_chars_raw, _ = await _fetch_all_pages(
            lambda limit, offset: client.get_user_character_collections(
                username, limit=limit, offset=offset
            ),
            page_size=50,
            page_delay=client.config.page_delay,
            max_pages=20,
        )
        fav_persons_raw, _ = await _fetch_all_pages(
            lambda limit, offset: client.get_user_person_collections(
                username, limit=limit, offset=offset
            ),
            page_size=50,
            page_delay=client.config.page_delay,
            max_pages=20,
        )

    tz_cn = timezone(timedelta(hours=8))
    collections_out = (
        [format_user_collection(it, compact=True) for it in all_raw] if compact else all_raw
    )
    payload: dict[str, Any] = {
        "fetched_at": datetime.now(tz_cn).isoformat(timespec="seconds"),
        "username": username,
        "user": (format_user(user_raw) if (user_raw and compact) else user_raw),
        "total_collections": len(collections_out),
        "overall_by_status": {k: v for k, v in overall_by_status.items() if v > 0},
        "summary_by_type": summary_by_type,
        "collections": collections_out,
    }
    if include_favorites:
        payload["favorite_characters"] = (
            [format_character_summary(c) for c in fav_chars_raw] if compact else fav_chars_raw
        )
        payload["favorite_persons"] = (
            [format_person_summary(p) for p in fav_persons_raw] if compact else fav_persons_raw
        )

    if cache is not None and compact:
        cache.set(username, type_ids, payload)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["saved_to"] = str(out.resolve())

    return payload


def _build_collection_indices(
    collections: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, list[dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
    """Build fast lookup maps by subject_id and normalized titles."""
    by_id: dict[int, dict[str, Any]] = {}
    by_norm: dict[str, list[dict[str, Any]]] = {}
    norm_pairs: list[tuple[str, dict[str, Any]]] = []

    for item in collections:
        sid = item.get("subject_id")
        if isinstance(sid, int):
            by_id[sid] = item
        for title_field in ("name_cn", "name"):
            raw_title = item.get(title_field)
            norm = normalize_title(raw_title)
            if norm:
                by_norm.setdefault(norm, []).append(item)
                norm_pairs.append((norm, item))

    return by_id, by_norm, norm_pairs


def _find_fuzzy_title_match(
    norm_query: str, norm_pairs: list[tuple[str, dict[str, Any]]]
) -> dict[str, Any] | None:
    """Conservative substring matching when exact normalized title doesn't match."""
    if len(norm_query) < 2:
        return None
    candidates: list[tuple[int, dict[str, Any]]] = []
    for norm_title, item in norm_pairs:
        if len(norm_title) < 2:
            continue
        if norm_query in norm_title or norm_title in norm_query:
            # Prefer tightest length ratio to avoid matching a 2-char word against a 30-char title
            shorter = min(len(norm_query), len(norm_title))
            longer = max(len(norm_query), len(norm_title))
            if shorter / longer >= 0.45:
                candidates.append((longer - shorter, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def _format_match_result(
    query: int | str,
    item: dict[str, Any],
    *,
    matched_by: str,
) -> dict[str, Any]:
    status = item.get("status")
    status_zh = item.get("status_zh") or (
        COLLECTION_TYPE_LABELS_ZH.get(item.get("type")) if isinstance(item.get("type"), int) else None
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
    return {k: v for k, v in out.items() if v is not None and v != "" and v != []}


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
    """Batch-check candidate subject IDs or titles against a user's Bangumi collection library.

    Designed for recommendation deduplication: labels each item as collect/doing/wish/
    on_hold/dropped/uncollected with user score/progress/comment so an LLM never recommends
    something the user has already watched or dropped.
    """
    snapshot = await sync_user_collections(
        client,
        username,
        subject_types=subject_types,
        include_user=False,
        include_favorites=False,
        compact=True,
        cache=cache,
        refresh=refresh,
    )
    collections = snapshot.get("collections") or []
    by_id, by_norm, norm_pairs = _build_collection_indices(collections)

    results: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    uncollected_queries: list[int | str] = []

    for raw_query in items:
        matched_item: dict[str, Any] | None = None
        matched_by: str = ""
        resolved_candidate: dict[str, Any] | None = None

        # 1. Subject ID direct lookup
        parsed_id: int | None = None
        if isinstance(raw_query, int) and not isinstance(raw_query, bool):
            parsed_id = raw_query
        elif isinstance(raw_query, str) and raw_query.strip().isdigit():
            parsed_id = int(raw_query.strip())

        if parsed_id is not None:
            if parsed_id in by_id:
                matched_item = by_id[parsed_id]
                matched_by = "subject_id"
        else:
            query_str = str(raw_query).strip()
            norm_q = normalize_title(query_str)

            # 2. Exact normalized title lookup
            if norm_q and norm_q in by_norm:
                matched_item = by_norm[norm_q][0]
                matched_by = "exact_title"

            # 3. Conservative fuzzy title containment lookup
            if matched_item is None and norm_q:
                fuzzy = _find_fuzzy_title_match(norm_q, norm_pairs)
                if fuzzy is not None:
                    matched_item = fuzzy
                    matched_by = "fuzzy_title"

            # 4. Optional fallback: resolve canonical subject_id via Bangumi search API
            if matched_item is None and resolve_unmatched_via_search and query_str:
                try:
                    search_resp = await client.search_subjects(
                        query_str,
                        subject_types=subject_types,
                        limit=5,
                    )
                    hits = (search_resp or {}).get("data") or []
                    if hits:
                        resolved_candidate = format_subject_summary(hits[0], max_summary_len=120)
                        for hit in hits:
                            hit_id = hit.get("id")
                            if isinstance(hit_id, int) and hit_id in by_id:
                                matched_item = by_id[hit_id]
                                matched_by = "search_resolved"
                                break
                except Exception:
                    # Search fallback is best-effort; never fail the whole batch
                    pass

        if matched_item is not None:
            entry = _format_match_result(raw_query, matched_item, matched_by=matched_by)
            status_key = str(entry.get("status") or "collected")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            results.append(entry)
        else:
            status_counts["uncollected"] = status_counts.get("uncollected", 0) + 1
            uncollected_queries.append(raw_query)
            uncollected_entry: dict[str, Any] = {
                "query": raw_query,
                "collected": False,
                "status": "uncollected",
                "status_zh": "未收藏",
            }
            if parsed_id is not None:
                uncollected_entry["subject_id"] = parsed_id
                uncollected_entry["url"] = f"{BGM_WEB}/subject/{parsed_id}"
            elif resolved_candidate is not None:
                uncollected_entry["resolved_candidate"] = resolved_candidate
            results.append(uncollected_entry)

    collected_count = len(items) - len(uncollected_queries)
    return {
        "username": username,
        "library_total": len(collections),
        "checked_count": len(items),
        "collected_count": collected_count,
        "uncollected_count": len(uncollected_queries),
        "status_counts": status_counts,
        "uncollected_items": uncollected_queries,
        "results": results,
    }
