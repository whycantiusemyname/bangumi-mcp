"""LLM-friendly response dehydration/compaction helpers for Bangumi API v0 payloads."""

from __future__ import annotations

from typing import Any

from .constants import (
    CHARACTER_TYPES,
    COLLECTION_TYPE_LABELS_ZH,
    COLLECTION_TYPES,
    EPISODE_COLLECTION_LABELS_ZH,
    EPISODE_COLLECTION_TYPES,
    EPISODE_TYPES,
    PERSON_TYPES,
    SUBJECT_TYPE_LABELS_ZH,
    SUBJECT_TYPES,
)

BGM_WEB = "https://bgm.tv"


def _prune(data: dict[str, Any]) -> dict[str, Any]:
    """Drop None and empty string/list/dict values to keep outputs compact."""
    return {
        k: v
        for k, v in data.items()
        if v is not None and v != "" and v != [] and v != {}
    }


def _truncate(text: str | None, max_len: int) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def _pick_image(images: dict[str, Any] | None) -> str | None:
    if not isinstance(images, dict):
        return None
    for key in ("common", "medium", "large", "small", "grid"):
        val = images.get(key)
        if val:
            return str(val)
    return None


def _compact_infobox(infobox: list[dict[str, Any]] | None, max_items: int = 20) -> dict[str, Any] | None:
    if not infobox or not isinstance(infobox, list):
        return None
    result: dict[str, Any] = {}
    for entry in infobox[:max_items]:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        val = entry.get("value")
        if not key or val is None:
            continue
        if isinstance(val, str):
            result[str(key)] = val
        elif isinstance(val, list):
            flattened: list[str] = []
            for item in val[:10]:
                if isinstance(item, dict):
                    k_part = item.get("k")
                    v_part = item.get("v")
                    if k_part and v_part:
                        flattened.append(f"{k_part}: {v_part}")
                    elif v_part:
                        flattened.append(str(v_part))
                elif item:
                    flattened.append(str(item))
            if flattened:
                result[str(key)] = flattened
    return result or None


def format_subject_summary(raw: dict[str, Any], *, max_summary_len: int = 200) -> dict[str, Any]:
    """Compact representation of Subject or SlimSubject for search/browse lists."""
    sid = raw.get("id")
    stype = raw.get("type")
    rating = raw.get("rating") if isinstance(raw.get("rating"), dict) else None
    score = rating.get("score") if rating else raw.get("score")
    rank = rating.get("rank") if rating else raw.get("rank")
    votes = rating.get("total") if rating else None

    tags_raw = raw.get("tags") or []
    tags = [t["name"] for t in tags_raw[:8] if isinstance(t, dict) and t.get("name")]

    summary_text = raw.get("short_summary") or raw.get("summary")

    return _prune(
        {
            "id": sid,
            "type": SUBJECT_TYPES.get(stype, stype),
            "name": raw.get("name"),
            "name_cn": raw.get("name_cn"),
            "date": raw.get("date"),
            "platform": raw.get("platform"),
            "score": score,
            "rank": rank if rank else None,
            "votes": votes,
            "eps": raw.get("total_episodes") or raw.get("eps") or None,
            "volumes": raw.get("volumes") or None,
            "tags": tags,
            "meta_tags": (raw.get("meta_tags") or [])[:8],
            "summary": _truncate(summary_text, max_summary_len),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
        }
    )


def format_subject_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """Dehydrated yet rich subject detail."""
    sid = raw.get("id")
    stype = raw.get("type")
    rating = raw.get("rating") if isinstance(raw.get("rating"), dict) else {}
    collection = raw.get("collection") if isinstance(raw.get("collection"), dict) else {}
    tags_raw = raw.get("tags") or []
    tags = [
        {"name": t["name"], "count": t.get("count", 0)}
        for t in tags_raw[:15]
        if isinstance(t, dict) and t.get("name")
    ]

    return _prune(
        {
            "id": sid,
            "type": SUBJECT_TYPES.get(stype, stype),
            "type_zh": SUBJECT_TYPE_LABELS_ZH.get(stype),
            "name": raw.get("name"),
            "name_cn": raw.get("name_cn"),
            "date": raw.get("date"),
            "platform": raw.get("platform"),
            "nsfw": raw.get("nsfw") if raw.get("nsfw") else None,
            "eps": raw.get("eps") or None,
            "total_episodes": raw.get("total_episodes") or None,
            "volumes": raw.get("volumes") or None,
            "rating": _prune(
                {
                    "score": rating.get("score"),
                    "rank": rating.get("rank") or None,
                    "votes": rating.get("total"),
                }
            ),
            "collection_stats": collection or None,
            "meta_tags": (raw.get("meta_tags") or [])[:12],
            "tags": tags,
            "summary": _truncate(raw.get("summary"), 1000),
            "infobox": _compact_infobox(raw.get("infobox"), max_items=24),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
        }
    )


def format_related_person(raw: dict[str, Any]) -> dict[str, Any]:
    pid = raw.get("id")
    return _prune(
        {
            "id": pid,
            "name": raw.get("name"),
            "relation": raw.get("relation"),
            "eps": raw.get("eps"),
            "career": raw.get("career"),
            "type": PERSON_TYPES.get(raw.get("type"), raw.get("type")),
            "url": f"{BGM_WEB}/person/{pid}" if pid else None,
        }
    )


def format_related_character(raw: dict[str, Any]) -> dict[str, Any]:
    cid = raw.get("id")
    actors = [
        _prune({"id": a.get("id"), "name": a.get("name")})
        for a in (raw.get("actors") or [])[:5]
        if isinstance(a, dict)
    ]
    return _prune(
        {
            "id": cid,
            "name": raw.get("name"),
            "relation": raw.get("relation"),
            "type": CHARACTER_TYPES.get(raw.get("type"), raw.get("type")),
            "actors": actors,
            "url": f"{BGM_WEB}/character/{cid}" if cid else None,
        }
    )


def format_related_subject(raw: dict[str, Any]) -> dict[str, Any]:
    sid = raw.get("id")
    stype = raw.get("type")
    return _prune(
        {
            "id": sid,
            "type": SUBJECT_TYPES.get(stype, stype),
            "name": raw.get("name"),
            "name_cn": raw.get("name_cn"),
            "relation": raw.get("relation") or raw.get("staff"),
            "eps": raw.get("eps"),
            "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
        }
    )


def format_episode(raw: dict[str, Any], *, include_desc: bool = False) -> dict[str, Any]:
    eid = raw.get("id")
    etype = raw.get("type")
    return _prune(
        {
            "id": eid,
            "subject_id": raw.get("subject_id"),
            "type": EPISODE_TYPES.get(etype, etype),
            "ep": raw.get("ep"),
            "sort": raw.get("sort"),
            "name": raw.get("name"),
            "name_cn": raw.get("name_cn"),
            "airdate": raw.get("airdate"),
            "duration": raw.get("duration"),
            "comment_count": raw.get("comment") or None,
            "desc": _truncate(raw.get("desc"), 600 if include_desc else 160) if include_desc else None,
            "url": f"{BGM_WEB}/ep/{eid}" if eid else None,
        }
    )


def format_user_episode(raw: dict[str, Any]) -> dict[str, Any]:
    ep = raw.get("episode") if isinstance(raw.get("episode"), dict) else {}
    status_code = raw.get("type")
    item = format_episode(ep, include_desc=False)
    item["watch_status"] = EPISODE_COLLECTION_TYPES.get(status_code, status_code)
    item["watch_status_zh"] = EPISODE_COLLECTION_LABELS_ZH.get(status_code)
    if raw.get("updated_at"):
        item["updated_at"] = raw["updated_at"]
    return _prune(item)


def format_calendar(raw_days: list[dict[str, Any]], weekday_filter: int | None = None) -> list[dict[str, Any]]:
    days_out: list[dict[str, Any]] = []
    for day in raw_days:
        wd = day.get("weekday") or {}
        wd_id = wd.get("id")
        if weekday_filter is not None and wd_id != weekday_filter:
            continue
        items_out: list[dict[str, Any]] = []
        for item in day.get("items") or []:
            sid = item.get("id")
            rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
            collection = item.get("collection") if isinstance(item.get("collection"), dict) else {}
            items_out.append(
                _prune(
                    {
                        "id": sid,
                        "name": item.get("name"),
                        "name_cn": item.get("name_cn"),
                        "air_date": item.get("air_date"),
                        "score": rating.get("score"),
                        "rank": item.get("rank") or None,
                        "doing": collection.get("doing"),
                        "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
                    }
                )
            )
        days_out.append(
            {
                "weekday_id": wd_id,
                "weekday_en": wd.get("en"),
                "weekday_cn": wd.get("cn"),
                "count": len(items_out),
                "items": items_out,
            }
        )
    return days_out


def format_character_summary(raw: dict[str, Any], *, max_summary_len: int = 200) -> dict[str, Any]:
    cid = raw.get("id")
    stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
    return _prune(
        {
            "id": cid,
            "name": raw.get("name"),
            "type": CHARACTER_TYPES.get(raw.get("type"), raw.get("type")),
            "gender": raw.get("gender"),
            "collects": stat.get("collects"),
            "summary": _truncate(raw.get("summary"), max_summary_len),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/character/{cid}" if cid else None,
        }
    )


def format_character_detail(raw: dict[str, Any]) -> dict[str, Any]:
    cid = raw.get("id")
    stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
    birth = None
    if raw.get("birth_mon") and raw.get("birth_day"):
        birth = (
            f"{raw['birth_year']}-{raw['birth_mon']:02d}-{raw['birth_day']:02d}"
            if raw.get("birth_year")
            else f"{raw['birth_mon']:02d}-{raw['birth_day']:02d}"
        )
    return _prune(
        {
            "id": cid,
            "name": raw.get("name"),
            "type": CHARACTER_TYPES.get(raw.get("type"), raw.get("type")),
            "gender": raw.get("gender"),
            "birthday": birth,
            "stat": stat or None,
            "summary": _truncate(raw.get("summary"), 1000),
            "infobox": _compact_infobox(raw.get("infobox"), max_items=18),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/character/{cid}" if cid else None,
        }
    )


def format_person_summary(raw: dict[str, Any], *, max_summary_len: int = 200) -> dict[str, Any]:
    pid = raw.get("id")
    return _prune(
        {
            "id": pid,
            "name": raw.get("name"),
            "type": PERSON_TYPES.get(raw.get("type"), raw.get("type")),
            "career": raw.get("career"),
            "summary": _truncate(raw.get("short_summary") or raw.get("summary"), max_summary_len),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/person/{pid}" if pid else None,
        }
    )


def format_person_detail(raw: dict[str, Any]) -> dict[str, Any]:
    pid = raw.get("id")
    stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
    birth = None
    if raw.get("birth_mon") and raw.get("birth_day"):
        birth = (
            f"{raw['birth_year']}-{raw['birth_mon']:02d}-{raw['birth_day']:02d}"
            if raw.get("birth_year")
            else f"{raw['birth_mon']:02d}-{raw['birth_day']:02d}"
        )
    return _prune(
        {
            "id": pid,
            "name": raw.get("name"),
            "type": PERSON_TYPES.get(raw.get("type"), raw.get("type")),
            "career": raw.get("career"),
            "gender": raw.get("gender"),
            "birthday": birth,
            "stat": stat or None,
            "summary": _truncate(raw.get("summary"), 1000),
            "infobox": _compact_infobox(raw.get("infobox"), max_items=18),
            "image": _pick_image(raw.get("images")),
            "url": f"{BGM_WEB}/person/{pid}" if pid else None,
        }
    )


def format_user(raw: dict[str, Any]) -> dict[str, Any]:
    username = raw.get("username")
    avatar = raw.get("avatar") if isinstance(raw.get("avatar"), dict) else {}
    return _prune(
        {
            "id": raw.get("id"),
            "username": username,
            "nickname": raw.get("nickname"),
            "sign": _truncate(raw.get("sign"), 200),
            "user_group": raw.get("user_group"),
            "avatar": avatar.get("medium") or avatar.get("large"),
            "url": f"{BGM_WEB}/user/{username}" if username else None,
        }
    )


def format_user_collection(raw: dict[str, Any], *, compact: bool = True) -> dict[str, Any]:
    sid = raw.get("subject_id")
    stype = raw.get("subject_type")
    ctype = raw.get("type")
    subject = raw.get("subject") if isinstance(raw.get("subject"), dict) else {}

    out: dict[str, Any] = {
        "subject_id": sid,
        "subject_type": SUBJECT_TYPES.get(stype, stype),
        "status": COLLECTION_TYPES.get(ctype, ctype),
        "status_zh": COLLECTION_TYPE_LABELS_ZH.get(ctype),
        "rate": raw.get("rate") or None,
        "ep_status": raw.get("ep_status") or None,
        "vol_status": raw.get("vol_status") or None,
        "tags": raw.get("tags") or None,
        "comment": _truncate(raw.get("comment"), 240 if compact else 800),
        "private": True if raw.get("private") else None,
        "updated_at": raw.get("updated_at"),
        "name": subject.get("name"),
        "name_cn": subject.get("name_cn"),
        "date": subject.get("date"),
        "subject_score": subject.get("score"),
        "subject_rank": subject.get("rank") or None,
        "eps": subject.get("eps") or None,
        "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
    }
    return _prune(out)


def format_index(raw: dict[str, Any]) -> dict[str, Any]:
    iid = raw.get("id")
    creator = raw.get("creator") if isinstance(raw.get("creator"), dict) else {}
    stat = raw.get("stat") if isinstance(raw.get("stat"), dict) else {}
    return _prune(
        {
            "id": iid,
            "title": raw.get("title"),
            "desc": _truncate(raw.get("desc"), 600),
            "total": raw.get("total"),
            "creator": _prune(
                {"username": creator.get("username"), "nickname": creator.get("nickname")}
            ),
            "stat": stat or None,
            "nsfw": True if raw.get("nsfw") else None,
            "created_at": raw.get("created_at"),
            "updated_at": raw.get("updated_at"),
            "url": f"{BGM_WEB}/index/{iid}" if iid else None,
        }
    )


def format_index_subject(raw: dict[str, Any]) -> dict[str, Any]:
    sid = raw.get("id")
    stype = raw.get("type")
    return _prune(
        {
            "id": sid,
            "type": SUBJECT_TYPES.get(stype, stype),
            "name": raw.get("name"),
            "date": raw.get("date"),
            "comment": _truncate(raw.get("comment"), 240),
            "added_at": raw.get("added_at"),
            "url": f"{BGM_WEB}/subject/{sid}" if sid else None,
        }
    )
