"""Codex CLI JSONL パーサー.

~/.codex/sessions/ 配下の JSONL ログを読み取り、
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

# スキップ対象の event_msg type
_SKIP_EVENT_TYPES = frozenset({
    "task_started",
    "turn_started",
    "task_complete",
    "turn_complete",
    "token_count",
    "agent_message_delta",
    "agent_reasoning_delta",
    "agent_reasoning_raw_content",
    "agent_reasoning_raw_content_delta",
    "agent_reasoning_section_break",
    "session_configured",
    "mcp_startup_update",
    "mcp_startup_complete",
    "exec_command_output_delta",
    "exec_approval_request",
    "patch_apply_begin",
    "patch_apply_end",
    "turn_diff",
    "shutdown_complete",
    "stream_error",
    "deprecation_notice",
    "background_event",
})


_SYSTEM_TEXT_PREFIXES = (
    "<",                    # <permissions>, <environment_context>, etc.
    "# AGENTS.md",          # AGENTS.md instructions block
    "## Skills",            # Skills section from AGENTS.md
)


def _is_system_text(text: str) -> bool:
    """システムプロンプト由来のテキストか判定する。"""
    return text.startswith(_SYSTEM_TEXT_PREFIXES)


def _format_entry(entry: dict) -> List[str]:
    """1つのJSONLエントリをフォーマット済み行のリストに変換する。"""
    entry_type = entry.get("type", "")

    if entry_type == "session_meta":
        return []

    if entry_type == "turn_context":
        return []

    if entry_type == "response_item":
        payload = entry.get("payload", {})
        return _format_response_item(payload)

    if entry_type == "event_msg":
        payload = entry.get("payload", {})
        return _format_event_msg(payload)

    return []


def _format_response_item(payload: dict) -> List[str]:
    """response_item をフォーマットする。"""
    role = payload.get("role", "")
    item_type = payload.get("type", "")

    # developer ロールはシステムプロンプト → スキップ
    if role == "developer":
        return []

    # reasoning → スキップ
    if item_type == "reasoning":
        return []

    if item_type == "message":
        content_items = payload.get("content", [])
        lines: List[str] = []
        for ci in content_items:
            ci_type = ci.get("type", "")
            if ci_type == "input_text" and role == "user":
                text = ci.get("text", "")
                # AGENTS.md やシステムプロンプトの大きなテキストはスキップ
                if text and len(text) < 5000 and not _is_system_text(text):
                    lines.append(f"[USER] {text}")
            elif ci_type == "output_text" and role == "assistant":
                text = ci.get("text", "")
                if text:
                    lines.append(f"[ASSISTANT] {text}")
        return lines

    if item_type == "local_shell_call":
        action = payload.get("action", {})
        cmd = action.get("command", [])
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = str(cmd)
        return [f"[TOOL] Shell({cmd_str[:200]})"]

    if item_type == "function_call":
        name = payload.get("name", "unknown")
        return [f"[TOOL] {name}"]

    return []


def _format_event_msg(payload: dict) -> List[str]:
    """event_msg をフォーマットする。

    注意: response_item と event_msg で同じメッセージが重複記録されるため、
    event_msg 側の user_message / agent_message はスキップし、
    response_item 側のみを採用する。
    """
    event_type = payload.get("type", "")

    if event_type in _SKIP_EVENT_TYPES:
        return []

    # user_message / agent_message は response_item 側と重複するためスキップ
    if event_type in ("user_message", "agent_message"):
        return []

    if event_type == "exec_command_begin":
        command = payload.get("command", "")
        if isinstance(command, list):
            command = " ".join(command)
        return [f"[TOOL] Shell({str(command)[:200]})"]

    if event_type == "exec_command_end":
        exit_code = payload.get("exit_code", "")
        output = payload.get("aggregated_output", "")
        if output:
            return [f"[TOOL_RESULT] exit={exit_code} {output[:500]}"]
        return []

    # その他のイベントはスキップ
    return []


class CodexParser:
    """Codex CLI JSONL ログパーサー."""

    def __init__(self, base_dir: str = "~/.codex/sessions") -> None:
        self._base_dir = os.path.expanduser(base_dir)

    def scan(self, cursor_manager: CursorManager) -> List[Dict[str, Any]]:
        """base_dir 配下の全 **/*.jsonl を再帰的にスキャンし、処理対象を返す。"""
        targets: List[Dict[str, Any]] = []
        pattern = os.path.join(self._base_dir, "**", "*.jsonl")

        for filepath in glob.glob(pattern, recursive=True):
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
