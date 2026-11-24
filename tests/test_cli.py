"""Unit tests for bangumi-mcp and bangumi-cli argument parsing, HTTP token guard, and error handling."""

from __future__ import annotations

import json

import pytest

from bangumi_mcp.cli import (
    build_cli_parser,
    build_mcp_parser,
    main_cli,
    resolve_mcp_runtime_config,
)
from bangumi_mcp.config import BangumiConfig


def test_mcp_parser_and_http_token_isolation() -> None:
    parser = build_mcp_parser()
    cfg_with_tok = BangumiConfig(access_token="secret-tok")

    # stdio keeps token
    args_stdio = parser.parse_args([])
    assert resolve_mcp_runtime_config(args_stdio, cfg_with_tok).access_token == "secret-tok"

    # streamable-http strips token by default (read-only safe mode)
    args_http_default = parser.parse_args(["--transport", "streamable-http"])
    assert resolve_mcp_runtime_config(args_http_default, cfg_with_tok).access_token is None

    # explicit opt-in on loopback host preserves token
    args_http_loopback = parser.parse_args(
        ["--transport", "streamable-http", "--host", "127.0.0.1", "--allow-token-over-http"]
    )
    assert resolve_mcp_runtime_config(args_http_loopback, cfg_with_tok).access_token == "secret-tok"

    # explicit opt-in on non-loopback host MUST be rejected
    args_http_remote = parser.parse_args(
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--allow-token-over-http"]
    )
    with pytest.raises(ValueError, match="non-loopback"):
        resolve_mcp_runtime_config(args_http_remote, cfg_with_tok)


def test_cli_parser_subcommands() -> None:
    parser = build_cli_parser()

    sync_args = parser.parse_args(["sync", "alice", "--types", "anime", "game", "-o", "out.json", "--favorites"])
    assert sync_args.command == "sync"
    assert sync_args.username == "alice"
    assert sync_args.types == ["anime", "game"]
    assert sync_args.output == "out.json"
    assert sync_args.favorites is True

    check_args = parser.parse_args(["check", "-u", "alice", "命运石之门", "328609", "--no-search"])
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


def test_cli_missing_file_returns_clean_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    code = main_cli(["check", "-u", "alice", "--file", "nonexistent_file_xyz_999.txt"])
    assert code == 1
    captured = capsys.readouterr()
    err = json.loads(captured.err.strip())
    assert err["error"] is True
    assert "nonexistent_file_xyz_999.txt" in err["message"]
