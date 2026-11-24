"""Unit tests for bangumi-mcp and bangumi-cli argument parsing and commands."""

from __future__ import annotations

from bangumi_mcp.cli import build_cli_parser, build_mcp_parser


def test_mcp_parser_defaults_and_http_args() -> None:
    parser = build_mcp_parser()
    args_default = parser.parse_args([])
    assert args_default.transport == "stdio"
    assert args_default.host == "127.0.0.1"
    assert args_default.port == 8765
    assert args_default.path == "/mcp"

    args_http = parser.parse_args(
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000", "--path", "/bgm"]
    )
    assert args_http.transport == "streamable-http"
    assert args_http.host == "0.0.0.0"
    assert args_http.port == 9000
    assert args_http.path == "/bgm"


def test_cli_parser_subcommands() -> None:
    parser = build_cli_parser()

    sync_args = parser.parse_args(["sync", "alice", "--types", "anime", "game", "-o", "out.json", "--favorites"])
    assert sync_args.command == "sync"
    assert sync_args.username == "alice"
    assert sync_args.types == ["anime", "game"]
    assert sync_args.output == "out.json"
    assert sync_args.favorites is True

    check_args = parser.parse_args(["check", "alice", "命运石之门", "328609", "--no-search"])
    assert check_args.command == "check"
    assert check_args.username == "alice"
    assert check_args.items == ["命运石之门", "328609"]
    assert check_args.no_search is True

    cal_args = parser.parse_args(["calendar", "--weekday", "today"])
    assert cal_args.command == "calendar"
    assert cal_args.weekday == "today"

    search_args = parser.parse_args(["search", "Frieren", "--types", "anime", "--sort", "rank", "--limit", "5"])
    assert search_args.command == "search"
    assert search_args.keyword == "Frieren"
    assert search_args.sort == "rank"
    assert search_args.limit == 5
