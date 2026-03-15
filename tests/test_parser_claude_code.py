"""
Claude Code JSONL パーサー テストスペック

BDD Scenarios:
  1. scan: 新規JSONLファイルを検出する
  2. scan: 未変更ファイルをスキップする
  3. read_diff: user メッセージを [USER] 形式に変換する
  4. read_diff: assistant text を [ASSISTANT] 形式に変換する
  5. read_diff: assistant tool_use を [TOOL] 形式で要約する
  6. read_diff: thinking ブロックをスキップする
  7. read_diff: progress/system 行をスキップする
  8. read_diff: last_read_line 以降のみ読む
  9. read_diff: 壊れたJSON行をスキップしクラッシュしない
  10. process_log + parser: パーサー経由でLLM→save のE2Eテスト
"""

from __future__ import annotations

import json
import os

import pytest


# === Helper ===

def _write_jsonl(dir_path: str, filename: str, entries: list) -> str:
    """JSONLファイルを作成する。dir_path 配下に filename を書き込む。"""
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return filepath


def _make_user_entry(content: str, **extra) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "timestamp": "2026-03-12T10:00:00.000Z",
        "sessionId": "test-session",
        "uuid": "u1",
        **extra,
    }


def _make_assistant_entry(blocks: list, **extra) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
        "timestamp": "2026-03-12T10:01:00.000Z",
        "sessionId": "test-session",
        "uuid": "a1",
        **extra,
    }


def _make_progress_entry(**extra) -> dict:
    return {
        "type": "progress",
        "data": {"type": "hook_progress"},
        "timestamp": "2026-03-12T10:00:00.000Z",
        "sessionId": "test-session",
        "uuid": "p1",
        **extra,
    }


def _make_system_entry(**extra) -> dict:
    return {
        "type": "system",
        "timestamp": "2026-03-12T10:00:00.000Z",
        "sessionId": "test-session",
        "uuid": "s1",
        **extra,
    }


# === BDD Scenario 1: scan — 新規JSONLファイルを検出する ===

class TestScanNewFiles:
    def test_detects_new_jsonl_file(self, tmp_jsonl_dir, tmp_cursor_path):
        """カーソルに未登録のJSONLファイルを検出する"""
        from engram.cursor import CursorManager
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        _write_jsonl(project_dir, "12345.jsonl", [_make_user_entry("hello")])

        cm = CursorManager(tmp_cursor_path)
        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        targets = parser.scan(cm)

        assert len(targets) == 1
        assert targets[0]["filename"].endswith(".jsonl")
        assert "filepath" in targets[0]
        assert "mtime" in targets[0]

    def test_detects_multiple_projects(self, tmp_jsonl_dir, tmp_cursor_path):
        """複数プロジェクトの配下にあるJSONLを全て検出する"""
        from engram.cursor import CursorManager
        from engram.parsers.claude_code import ClaudeCodeParser

        proj_a = os.path.join(tmp_jsonl_dir, "-Users-test-projA")
        proj_b = os.path.join(tmp_jsonl_dir, "-Users-test-projB")
        _write_jsonl(proj_a, "aaa.jsonl", [_make_user_entry("a")])
        _write_jsonl(proj_b, "bbb.jsonl", [_make_user_entry("b")])

        cm = CursorManager(tmp_cursor_path)
        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        targets = parser.scan(cm)

        assert len(targets) == 2


# === BDD Scenario 2: scan — 未変更ファイルをスキップする ===

class TestScanSkipsUnchanged:
    def test_skips_unchanged_file(self, tmp_jsonl_dir, tmp_cursor_path):
        """mtimeが変わっていないファイルはスキップする"""
        from engram.cursor import CursorManager
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "12345.jsonl", [_make_user_entry("hi")])
        current_mtime = os.path.getmtime(filepath)

        # カーソルキーは相対パス
        cursor_key = os.path.relpath(filepath, tmp_jsonl_dir)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor(cursor_key, last_read_line=1, last_checked_mtime=current_mtime)

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        targets = parser.scan(cm)

        assert len(targets) == 0


# === BDD Scenario 3: read_diff — user メッセージ ===

class TestReadDiffUser:
    def test_formats_user_message(self, tmp_jsonl_dir):
        """user メッセージを [USER] 形式に変換する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_user_entry("テストを実行して"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, total_lines = parser.read_diff(filepath, last_read_line=0)

        assert "[USER] テストを実行して" in text
        assert total_lines == 1


# === BDD Scenario 4: read_diff — assistant text ===

class TestReadDiffAssistantText:
    def test_formats_assistant_text(self, tmp_jsonl_dir):
        """assistant text ブロックを [ASSISTANT] 形式に変換する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{"type": "text", "text": "テスト結果: 全て合格"}]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, total_lines = parser.read_diff(filepath, last_read_line=0)

        assert "[ASSISTANT] テスト結果: 全て合格" in text
        assert total_lines == 1


# === BDD Scenario 5: read_diff — assistant tool_use ===

class TestReadDiffToolUse:
    def test_formats_read_tool(self, tmp_jsonl_dir):
        """Read ツール呼び出しを [TOOL] Read(file_path) 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t1",
                "name": "Read",
                "input": {"file_path": "/src/main.py"},
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] Read(/src/main.py)" in text

    def test_formats_bash_tool(self, tmp_jsonl_dir):
        """Bash ツール呼び出しを [TOOL] Bash(command先頭100文字) 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        long_cmd = "python -m pytest tests/ -v --tb=short" + " " * 100
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t2",
                "name": "Bash",
                "input": {"command": long_cmd},
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] Bash(" in text
        # コマンドは100文字以内に切られる
        tool_line = [l for l in text.split("\n") if "[TOOL] Bash(" in l][0]
        # Bash(...) 部分のカッコ内を取得
        inner = tool_line.split("Bash(")[1].rstrip(")")
        assert len(inner) <= 100

    def test_formats_edit_tool(self, tmp_jsonl_dir):
        """Edit ツール呼び出しを [TOOL] Edit(file_path, old_string先頭50文字) 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t3",
                "name": "Edit",
                "input": {
                    "file_path": "/src/app.py",
                    "old_string": "def old_function():\n    pass" + "x" * 50,
                    "new_string": "def new_function():\n    return True",
                },
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] Edit(/src/app.py, " in text

    def test_formats_grep_tool(self, tmp_jsonl_dir):
        """Grep ツール呼び出しを [TOOL] Grep(pattern, path) 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t4",
                "name": "Grep",
                "input": {"pattern": "def test_", "path": "/src/"},
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] Grep(def test_, /src/)" in text

    def test_formats_write_tool(self, tmp_jsonl_dir):
        """Write ツール呼び出しを [TOOL] Write(file_path) 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t5",
                "name": "Write",
                "input": {"file_path": "/src/new_file.py", "content": "print('hello')"},
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] Write(/src/new_file.py)" in text

    def test_formats_unknown_tool(self, tmp_jsonl_dir):
        """未知のツール呼び出しを [TOOL] ToolName 形式で要約する"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([{
                "type": "tool_use",
                "id": "t6",
                "name": "CustomTool",
                "input": {"foo": "bar"},
            }]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[TOOL] CustomTool" in text


# === BDD Scenario 6: read_diff — thinking ブロックをスキップする ===

class TestReadDiffThinking:
    def test_skips_thinking_block(self, tmp_jsonl_dir):
        """thinking ブロックは出力に含まれない"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_assistant_entry([
                {"type": "thinking", "thinking": "内部思考テキスト"},
                {"type": "text", "text": "表示テキスト"},
            ]),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "内部思考テキスト" not in text
        assert "[ASSISTANT] 表示テキスト" in text


# === BDD Scenario 7: read_diff — progress/system 行をスキップする ===

class TestReadDiffSkipTypes:
    def test_skips_progress(self, tmp_jsonl_dir):
        """progress 行はスキップされる"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_progress_entry(),
            _make_user_entry("visible"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, total_lines = parser.read_diff(filepath, last_read_line=0)

        assert "hook_progress" not in text
        assert "[USER] visible" in text
        assert total_lines == 2

    def test_skips_system(self, tmp_jsonl_dir):
        """system 行はスキップされる"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_system_entry(),
            _make_user_entry("visible"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[USER] visible" in text

    def test_skips_file_history_snapshot(self, tmp_jsonl_dir):
        """file-history-snapshot 行はスキップされる"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            {"type": "file-history-snapshot", "snapshot": {}, "sessionId": "s1"},
            _make_user_entry("visible"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[USER] visible" in text

    def test_skips_queue_operation(self, tmp_jsonl_dir):
        """queue-operation 行はスキップされる"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            {"type": "queue-operation", "data": {}, "sessionId": "s1"},
            _make_user_entry("visible"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, _ = parser.read_diff(filepath, last_read_line=0)

        assert "[USER] visible" in text


# === BDD Scenario 8: read_diff — last_read_line 以降のみ読む ===

class TestReadDiffOffset:
    def test_reads_only_after_last_read_line(self, tmp_jsonl_dir):
        """last_read_line 以降の行のみをパースする"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_user_entry("old message"),
            _make_user_entry("new message"),
            _make_user_entry("newest message"),
        ])

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, total_lines = parser.read_diff(filepath, last_read_line=1)

        assert "old message" not in text
        assert "[USER] new message" in text
        assert "[USER] newest message" in text
        assert total_lines == 3


# === BDD Scenario 9: read_diff — 壊れたJSON行をスキップしクラッシュしない ===

class TestReadDiffBrokenJson:
    def test_skips_broken_json_line(self, tmp_jsonl_dir):
        """パース失敗行はスキップし、正常行は処理される"""
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = os.path.join(project_dir, "session.jsonl")
        os.makedirs(project_dir, exist_ok=True)
        with open(filepath, "w") as f:
            f.write("this is not json\n")
            f.write(json.dumps(_make_user_entry("valid message")) + "\n")

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)
        text, total_lines = parser.read_diff(filepath, last_read_line=0)

        assert "[USER] valid message" in text
        assert total_lines == 2


# === BDD Scenario 10: process_log + parser — E2Eテスト ===

class TestProcessLogWithParser:
    def test_parser_integrated_with_process_log(
        self, tmp_jsonl_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert
    ):
        """パーサー経由でprocess_logを呼び出し、LLM→saveが正しく動作する"""
        from engram.cursor import CursorManager
        from engram.miner import process_log
        from engram.parsers.claude_code import ClaudeCodeParser

        project_dir = os.path.join(tmp_jsonl_dir, "-Users-test-project")
        filepath = _write_jsonl(project_dir, "session.jsonl", [
            _make_user_entry("バグを修正して"),
            _make_assistant_entry([{"type": "text", "text": "修正しました"}]),
        ])

        cm = CursorManager(tmp_cursor_path)
        cursor_key = os.path.relpath(filepath, tmp_jsonl_dir)
        cm.update_cursor(cursor_key, last_read_line=0, last_checked_mtime=0.0)

        parser = ClaudeCodeParser(base_dir=tmp_jsonl_dir)

        def mock_recall(query, **kwargs):
            return []

        process_log(
            filepath,
            cm,
            mock_llm_insert,
            db_path=tmp_db_path,
            recall_fn=mock_recall,
            parser=parser,
        )

        cursor = cm.get_cursor(cursor_key)
        assert cursor["last_read_line"] == 2  # 2行読み済み

    def test_parser_none_uses_legacy_behavior(
        self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert
    ):
        """parser=None の場合は既存の text 形式の動作を維持する"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = os.path.join(str(tmp_log_dir), "session_legacy_log.txt")
        with open(filepath, "w") as f:
            f.write("line1\nline2\nline3\n")

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_legacy_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_legacy_log.txt")
        assert cursor["last_read_line"] == 3
