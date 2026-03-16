"""Claude Code JSONL パーサー.

~/.claude/projects/ 配下の JSONL ログを読み取り、
miner が処理できるフォーマットに変換する。
"""

from __future__ import annotations

import glob
import json
import logging
import os
from typing import Any, Dict, List, Tuple

from engram.cursor import CursorManager

logger = logging.getLogger(__name__)

# スキップ対象の type
_SKIP_TYPES = frozenset({
    "progress",
    "system",
    "file-history-snapshot",
    "queue-operation",
})


def _summarize_tool_use(name: str, input_data: dict) -> str:
    """tool_use ブロックを要約文字列に変換する。"""
    if name == "Read":
        fp = input_data.get("file_path", "")
        return f"Read({fp})"
    elif name == "Bash":
        cmd = input_data.get("command", "")
        return f"Bash({cmd[:100]})"
    elif name == "Edit":
        fp = input_data.get("file_path", "")
        old = input_data.get("old_string", "")
        return f"Edit({fp}, {old[:50]})"
    elif name == "Grep":
        pattern = input_data.get("pattern", "")
        path = input_data.get("path", "")
        return f"Grep({pattern}, {path})"
    elif name == "Write":
        fp = input_data.get("file_path", "")
        return f"Write({fp})"
    else:
        return name


def _format_entry(entry: dict) -> List[str]:
    """1つのJSONLエントリをフォーマット済み行のリストに変換する。

    スキップ対象のエントリは空リストを返す。
    """
    entry_type = entry.get("type", "")

    if entry_type in _SKIP_TYPES:
        return []

    message = entry.get("message", {})

    if entry_type == "user":
        content = message.get("content", "")
        if isinstance(content, str) and content:
            return [f"[USER] {content}"]
        return []

    if entry_type == "assistant":
        blocks = message.get("content", [])
        if not isinstance(blocks, list):
            return []

        lines: List[str] = []
        for block in blocks:
            block_type = block.get("type", "")

            if block_type == "thinking":
                continue  # skip thinking

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    lines.append(f"[ASSISTANT] {text}")

            elif block_type == "tool_use":
                name = block.get("name", "unknown")
                input_data = block.get("input", {})
                summary = _summarize_tool_use(name, input_data)
                lines.append(f"[TOOL] {summary}")

        return lines

    # 未知の type → スキップ
    return []


class ClaudeCodeParser:
    """Claude Code JSONL ログパーサー."""

    def __init__(self, base_dir: str = "~/.claude/projects") -> None:
        self._base_dir = os.path.expanduser(base_dir)

    def scan(self, cursor_manager: CursorManager) -> List[Dict[str, Any]]:
        """base_dir 配下の全 **/*.jsonl を再帰的にスキャンし、処理対象を返す。"""
        targets: List[Dict[str, Any]] = []
        pattern = os.path.join(self._base_dir, "**", "*.jsonl")

        for filepath in glob.glob(pattern, recursive=True):
            # subagents/ 配下はノイズが多いため除外
            if "/subagents/" in filepath:
                continue
            cursor_key = os.path.relpath(filepath, self._base_dir)
            current_mtime = os.path.getmtime(filepath)
            cursor = cursor_manager.get_cursor(cursor_key)

            if cursor["last_checked_mtime"] != 0.0 and cursor["last_checked_mtime"] == current_mtime:
                continue  # unchanged

            targets.append({
                "filename": cursor_key,
                "filepath": filepath,
                "mtime": current_mtime,
            })

        return targets

    def read_diff(self, filepath: str, last_read_line: int) -> Tuple[str, int]:
        """last_read_line 以降の JSONL を行単位で読み、フォーマット済みテキストを返す。

        Returns:
            (formatted_text, total_lines): total_lines はファイル全体の行数
        """
        formatted_parts: List[str] = []
        total_lines = 0

        with open(filepath, "r") as f:
            for i, raw_line in enumerate(f):
                total_lines = i + 1
                if i < last_read_line:
                    continue

                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.warning("JSONL parse error at line %d in %s", i + 1, filepath)
                    continue

                lines = _format_entry(entry)
                formatted_parts.extend(lines)

        return "\n".join(formatted_parts), total_lines
