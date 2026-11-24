"""Command-line interfaces: `bangumi-mcp` (MCP server) and `bangumi-cli` (utility CLI)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .client import BangumiClient, BangumiError
from .config import BangumiConfig
from .constants import parse_subject_types, parse_weekday
from .formatters import (
    format_calendar,
    format_subject_detail,
    format_subject_summary,
    format_user,
)
from .server import create_server
from .services import check_user_collections, sync_user_collections


def _print_json(data: object) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


# ----------------------------------------------------------------------
# `bangumi-mcp` entrypoint (MCP Server: stdio or streamable-http)
# ----------------------------------------------------------------------


def build_mcp_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bangumi-mcp",
        description="Run the Bangumi API v0 MCP Server (stdio or streamable-http).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport protocol (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for streamable-http transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port for streamable-http transport (default: 8765).",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP endpoint path for streamable-http transport (default: /mcp).",
    )
    return parser


def main_mcp(argv: Sequence[str] | None = None) -> int:
    parser = build_mcp_parser()
    args = parser.parse_args(argv)
    server = create_server(
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
    )
    if args.transport == "streamable-http":
        try:
            server.run(
                transport="streamable-http",
                host=args.host,
                port=args.port,
                streamable_http_path=args.path,
            )
        except TypeError:  # pragma: no cover - mcp 1.x FastMCP takes host/port in __init__
            server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
    return 0


# ----------------------------------------------------------------------
# `bangumi-cli` entrypoint (Direct CLI for sync / dedup / quick queries)
# ----------------------------------------------------------------------


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bangumi-cli",
        description="Lightweight CLI for Bangumi API v0 (collection sync, batch dedup, search, calendar).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser(
        "sync",
        help="Fetch all paginated collections for a user across all 5 subject types.",
    )
    p_sync.add_argument(
        "username",
        nargs="?",
        help="Bangumi username (or set BANGUMI_DEFAULT_USERNAME).",
    )
    p_sync.add_argument(
        "--types",
        nargs="+",
        help="Subset of subject types, e.g. anime book game (default: all 5).",
    )
    p_sync.add_argument(
        "-o",
        "--output",
        help="Optional output JSON file path.",
    )
    p_sync.add_argument(
        "--favorites",
        action="store_true",
        help="Also fetch favorite characters and persons.",
    )
    p_sync.add_argument(
        "--raw",
        action="store_true",
        help="Keep raw Bangumi API payloads instead of compacted LLM-friendly objects.",
    )

    # check (dedup)
    p_check = sub.add_parser(
        "check",
        help="Batch-check titles or subject IDs against a user's collections to avoid duplicate recommendations.",
    )
    p_check.add_argument(
        "username",
        help="Bangumi username to check against.",
    )
    p_check.add_argument(
        "items",
        nargs="*",
        help="Candidate subject IDs or titles.",
    )
    p_check.add_argument(
        "--file",
        help="Text file with one candidate title or subject ID per line.",
    )
    p_check.add_argument(
        "--types",
        nargs="+",
        help="Subset of subject types to fetch, e.g. anime.",
    )
    p_check.add_argument(
        "--no-search",
        action="store_true",
        help="Disable fallback Bangumi search resolution for unmatched titles.",
    )

    # search
    p_search = sub.add_parser("search", help="Search Bangumi subjects.")
    p_search.add_argument("keyword", help="Search query.")
    p_search.add_argument("--types", nargs="+", help="Filter by subject types, e.g. anime game.")
    p_search.add_argument(
        "--sort",
        choices=("match", "heat", "rank", "score"),
        default="match",
    )
    p_search.add_argument("--limit", type=int, default=10)

    # subject
    p_subj = sub.add_parser("subject", help="Show compact details for a subject ID.")
    p_subj.add_argument("subject_id", type=int)

    # calendar
    p_cal = sub.add_parser("calendar", help="Show Bangumi weekly airing calendar.")
    p_cal.add_argument(
        "--weekday",
        help="Optional weekday filter: 1-7, monday-sunday, 周一-周日, or today.",
    )

    # user
    p_user = sub.add_parser("user", help="Show public profile for a Bangumi user.")
    p_user.add_argument("username", nargs="?", help="Bangumi username.")

    # me
    sub.add_parser("me", help="Show authenticated user profile (requires BANGUMI_ACCESS_TOKEN).")

    return parser


async def _run_cli_async(args: argparse.Namespace, config: BangumiConfig) -> int:
    async with BangumiClient(config=config) as client:
        if args.command == "sync":
            username = args.username or config.default_username
            if not username:
                raise ValueError("username is required (pass argument or set BANGUMI_DEFAULT_USERNAME).")
            types = parse_subject_types(args.types) if args.types else None
            payload = await sync_user_collections(
                client,
                username,
                subject_types=types,
                include_user=True,
                include_favorites=args.favorites,
                compact=not args.raw,
                output_path=args.output,
            )
            if args.output:
                summary = {
                    "username": payload["username"],
                    "total_collections": payload["total_collections"],
                    "overall_by_status": payload["overall_by_status"],
                    "summary_by_type": payload["summary_by_type"],
                    "saved_to": payload["saved_to"],
                }
                _print_json(summary)
            else:
                _print_json(payload)
            return 0

        if args.command == "check":
            candidates: list[int | str] = list(args.items or [])
            if args.file:
                lines = Path(args.file).read_text(encoding="utf-8").splitlines()
                candidates.extend([ln.strip() for ln in lines if ln.strip()])
            if not candidates:
                raise ValueError("Provide at least one candidate title/subject_id or --file.")
            types = parse_subject_types(args.types) if args.types else None
            report = await check_user_collections(
                client,
                args.username,
                candidates,
                subject_types=types,
                resolve_unmatched_via_search=not args.no_search,
            )
            _print_json(report)
            return 0

        if args.command == "search":
            types = parse_subject_types(args.types) if args.types else None
            raw = await client.search_subjects(
                args.keyword,
                sort=args.sort,
                subject_types=types,
                limit=min(max(args.limit, 1), 50),
            )
            _print_json(
                {
                    "total": raw.get("total", 0),
                    "items": [format_subject_summary(s) for s in (raw.get("data") or [])],
                }
            )
            return 0

        if args.command == "subject":
            raw = await client.get_subject(args.subject_id)
            _print_json(format_subject_detail(raw))
            return 0

        if args.command == "calendar":
            wd = parse_weekday(args.weekday) if args.weekday else None
            raw = await client.get_calendar()
            _print_json({"days": format_calendar(raw, weekday_filter=wd)})
            return 0

        if args.command == "user":
            username = args.username or config.default_username
            if not username:
                raise ValueError("username is required (pass argument or set BANGUMI_DEFAULT_USERNAME).")
            raw = await client.get_user(username)
            _print_json(format_user(raw))
            return 0

        if args.command == "me":
            raw = await client.get_me()
            _print_json(format_user(raw))
            return 0

    return 1


def main_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    config = BangumiConfig.from_env()
    try:
        return asyncio.run(_run_cli_async(args, config))
    except (ValueError, BangumiError) as exc:
        err = json.dumps({"error": True, "message": str(exc)}, ensure_ascii=False)
        sys.stderr.buffer.write((err + "\n").encode("utf-8"))
        return 1
