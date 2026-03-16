"""Codex CLI JSONL パーサーのテスト."""

import json
import os
import pytest

from engram.parsers.codex import CodexParser, _format_entry
from engram.cursor import CursorManager


# === ヘルパー ===

def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _make_response_item(role, content_items, item_type="message", **extra):
    payload = {"type": item_type, "role": role, "content": content_items, **extra}
    return {"timestamp": "2026-03-16T04:57:22.911Z", "type": "response_item", "payload": payload}


def _make_event_msg(event_type, **extra):
    return {"timestamp": "2026-03-16T04:57:22.911Z", "type": "event_msg", "payload": {"type": event_type, **extra}}


# === _format_entry tests ===

class TestFormatEntry:
    """Codex JSONL エントリのフォーマット."""

    def test_session_meta_skipped(self):
        entry = {"type": "session_meta", "payload": {"id": "abc"}}
        assert _format_entry(entry) == []

    def test_turn_context_skipped(self):
        entry = {"type": "turn_context", "payload": {"turn_id": "abc"}}
        assert _format_entry(entry) == []

    def test_user_message_from_response_item(self):
        entry = _make_response_item("user", [{"type": "input_text", "text": "Hello world"}])
        result = _format_entry(entry)
        assert result == ["[USER] Hello world"]

    def test_assistant_message_from_response_item(self):
        entry = _make_response_item("assistant", [{"type": "output_text", "text": "4"}])
        result = _format_entry(entry)
        assert result == ["[ASSISTANT] 4"]

    def test_developer_role_skipped(self):
        entry = _make_response_item("developer", [{"type": "input_text", "text": "system prompt"}])
        assert _format_entry(entry) == []

    def test_reasoning_skipped(self):
        entry = _make_response_item("assistant", [], item_type="reasoning")
        assert _format_entry(entry) == []

    def test_local_shell_call(self):
        entry = {
            "timestamp": "2026-03-16T04:57:22.911Z",
            "type": "response_item",
            "payload": {
                "type": "local_shell_call",
                "action": {"command": ["ls", "-la"]},
                "status": "completed",
            },
        }
        result = _format_entry(entry)
        assert result == ["[TOOL] Shell(ls -la)"]

    def test_function_call(self):
        entry = {
            "timestamp": "2026-03-16T04:57:22.911Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "read_file",
                "arguments": '{"path": "foo.py"}',
            },
        }
        result = _format_entry(entry)
        assert result == ["[TOOL] read_file"]

    def test_user_message_from_event_msg(self):
        entry = _make_event_msg("user_message", message="What is 2+2?")
        result = _format_entry(entry)
        assert result == ["[USER] What is 2+2?"]

    def test_agent_message_from_event_msg(self):
        entry = _make_event_msg("agent_message", message="The answer is 4.")
        result = _format_entry(entry)
        assert result == ["[ASSISTANT] The answer is 4."]

    def test_exec_command_begin(self):
        entry = _make_event_msg("exec_command_begin", command="git status")
        result = _format_entry(entry)
        assert result == ["[TOOL] Shell(git status)"]

    def test_exec_command_end_with_output(self):
        entry = _make_event_msg("exec_command_end", exit_code=0, aggregated_output="on branch main")
        result = _format_entry(entry)
        assert result == ["[TOOL_RESULT] exit=0 on branch main"]

    def test_skip_event_types(self):
        for event_type in ["task_started", "task_complete", "token_count", "agent_message_delta",
                           "shutdown_complete", "stream_error"]:
            entry = _make_event_msg(event_type)
            assert _format_entry(entry) == [], f"{event_type} should be skipped"

    def test_large_system_text_skipped(self):
        """AGENTS.md等の大きなシステムテキストはスキップされる."""
        big_text = "x" * 6000
        entry = _make_response_item("user", [{"type": "input_text", "text": big_text}])
        assert _format_entry(entry) == []

    def test_xml_tagged_text_skipped(self):
        """<permissions> 等のシステムタグ付きテキストはスキップ."""
        entry = _make_response_item("user", [{"type": "input_text", "text": "<permissions instructions>..."}])
        assert _format_entry(entry) == []


# === CodexParser tests ===

class TestCodexParserScan:
    """CodexParser.scan() のテスト."""

    def test_scan_finds_jsonl_files(self, tmp_path):
        session_dir = tmp_path / "2026" / "03" / "16"
        session_dir.mkdir(parents=True)
        f1 = session_dir / "rollout-2026-03-16T13-57-22-abc.jsonl"
        _write_jsonl(str(f1), [{"type": "session_meta", "payload": {}}])

        cm = CursorManager(str(tmp_path / "cursor.json"))
        parser = CodexParser(base_dir=str(tmp_path))
        targets = parser.scan(cm)
        assert len(targets) == 1
        assert targets[0]["filename"].endswith(".jsonl")

    def test_scan_skips_unchanged(self, tmp_path):
        session_dir = tmp_path / "2026" / "03" / "16"
        session_dir.mkdir(parents=True)
        f1 = session_dir / "rollout-abc.jsonl"
        _write_jsonl(str(f1), [{"type": "session_meta", "payload": {}}])

        cm = CursorManager(str(tmp_path / "cursor.json"))
        parser = CodexParser(base_dir=str(tmp_path))

        # 1回目: 対象あり
        targets = parser.scan(cm)
        assert len(targets) == 1

        # cursorを更新
        cursor_key = targets[0]["filename"]
        cm.update_cursor(cursor_key, last_read_line=1, last_checked_mtime=targets[0]["mtime"])

        # 2回目: 対象なし
        targets = parser.scan(cm)
        assert len(targets) == 0


class TestCodexParserReadDiff:
    """CodexParser.read_diff() のテスト."""

    def test_read_diff_formats_entries(self, tmp_path):
        f = tmp_path / "session.jsonl"
        entries = [
            {"type": "session_meta", "payload": {"id": "abc"}},
            _make_response_item("user", [{"type": "input_text", "text": "Hello"}]),
            _make_response_item("assistant", [{"type": "output_text", "text": "Hi there!"}]),
            _make_event_msg("exec_command_begin", command="ls"),
        ]
        _write_jsonl(str(f), entries)

        parser = CodexParser(base_dir=str(tmp_path))
        text, total_lines = parser.read_diff(str(f), 0)
        assert "[USER] Hello" in text
        assert "[ASSISTANT] Hi there!" in text
        assert "[TOOL] Shell(ls)" in text
        assert total_lines == 4

    def test_read_diff_respects_last_read_line(self, tmp_path):
        f = tmp_path / "session.jsonl"
        entries = [
            _make_response_item("user", [{"type": "input_text", "text": "First"}]),
            _make_response_item("user", [{"type": "input_text", "text": "Second"}]),
            _make_response_item("user", [{"type": "input_text", "text": "Third"}]),
        ]
        _write_jsonl(str(f), entries)

        parser = CodexParser(base_dir=str(tmp_path))
        text, total_lines = parser.read_diff(str(f), 2)
        assert "First" not in text
        assert "Second" not in text
        assert "[USER] Third" in text
        assert total_lines == 3

    def test_read_diff_handles_malformed_json(self, tmp_path):
        f = tmp_path / "session.jsonl"
        with open(str(f), "w") as fh:
            fh.write(json.dumps(_make_response_item("user", [{"type": "input_text", "text": "OK"}])) + "\n")
            fh.write("not json\n")
            fh.write(json.dumps(_make_response_item("user", [{"type": "input_text", "text": "Also OK"}])) + "\n")

        parser = CodexParser(base_dir=str(tmp_path))
        text, total_lines = parser.read_diff(str(f), 0)
        assert "[USER] OK" in text
        assert "[USER] Also OK" in text
        assert total_lines == 3
