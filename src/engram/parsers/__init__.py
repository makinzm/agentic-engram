"""パーサーレジストリ."""

from __future__ import annotations

from typing import Any

from engram.parsers.base import SessionParser
from engram.parsers.claude_code import ClaudeCodeParser
from engram.parsers.codex import CodexParser

PARSERS = {
    "claude-code": ClaudeCodeParser,
    "codex": CodexParser,
}


def get_parser(source: str, **kwargs: Any) -> SessionParser:
    """source 名に対応するパーサーインスタンスを返す。"""
    cls = PARSERS.get(source)
    if cls is None:
        raise ValueError(f"Unknown parser source: {source!r}. Available: {list(PARSERS.keys())}")
    return cls(**kwargs)
