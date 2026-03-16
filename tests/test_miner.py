"""
ae-miner: 砂金掘りエンジンのコアロジック テストスペック

BDD Scenarios:
  1. scan_logs: mtime変更のあるファイルのみを処理対象として返す
  2. read_diff: last_read_lineからEOFまでの差分テキストを取得する
  3. process_log (SKIP): LLMがSKIPを返した場合、last_read_lineを進めずmtimeのみ更新
  4. process_log (INSERT): LLMがINSERTを返した場合、ae-saveに流し込みカーソルを進める
  5. process_log (UPDATE): LLMがUPDATEを返した場合、ae-saveに流し込みカーソルを進める
  6. process_log (混合): SKIP+INSERTが混在するLLMレスポンスを正しく処理する
  7. archive_stale_logs: TTL超過ファイルをarchive/へ移動しカーソルを削除する
  8. エッジケース: 空ファイル、途中削除ファイル等への耐性
"""

import json
import os
import time

import pytest


# === Helper ===

def _write_log_file(log_dir, filename, lines):
    """テスト用のログファイルを作成する"""
    filepath = os.path.join(str(log_dir), filename)
    with open(filepath, "w") as f:
        for line in lines:
            f.write(line + "\n")
    return filepath


def _set_mtime(filepath, mtime):
    """ファイルのmtimeを指定値に設定する"""
    os.utime(filepath, (mtime, mtime))


# === BDD Scenario 1: scan_logs ===

class TestScanLogs:
    def test_detects_new_file(self, tmp_log_dir, tmp_cursor_path):
        """カーソルに未登録の新規ファイルを検出する"""
        from engram.cursor import CursorManager
        from engram.miner import scan_logs

        _write_log_file(tmp_log_dir, "session_new_log.txt", ["line1", "line2"])

        cm = CursorManager(tmp_cursor_path)
        targets = scan_logs(str(tmp_log_dir), cm)

        assert len(targets) == 1
        assert targets[0]["filename"] == "session_new_log.txt"

    def test_detects_modified_file(self, tmp_log_dir, tmp_cursor_path):
        """mtimeが更新されたファイルを検出する"""
        from engram.cursor import CursorManager
        from engram.miner import scan_logs

        filepath = _write_log_file(tmp_log_dir, "session_mod_log.txt", ["line1"])
        old_mtime = os.path.getmtime(filepath)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_mod_log.txt", last_read_line=1, last_checked_mtime=old_mtime)

        # ファイルを更新（mtimeを進める）
        with open(filepath, "a") as f:
            f.write("line2\n")

        targets = scan_logs(str(tmp_log_dir), cm)
        assert len(targets) == 1

    def test_skips_unchanged_file(self, tmp_log_dir, tmp_cursor_path):
        """mtimeが変わっていないファイルはスキップする"""
        from engram.cursor import CursorManager
        from engram.miner import scan_logs

        filepath = _write_log_file(tmp_log_dir, "session_same_log.txt", ["line1"])
        current_mtime = os.path.getmtime(filepath)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_same_log.txt", last_read_line=1, last_checked_mtime=current_mtime)

        targets = scan_logs(str(tmp_log_dir), cm)
        assert len(targets) == 0

    def test_ignores_non_log_files(self, tmp_log_dir, tmp_cursor_path):
        """_log.txt で終わらないファイルは無視する"""
        from engram.cursor import CursorManager
        from engram.miner import scan_logs

        _write_log_file(tmp_log_dir, "readme.md", ["# README"])
        _write_log_file(tmp_log_dir, "session_abc_log.txt", ["line1"])

        cm = CursorManager(tmp_cursor_path)
        targets = scan_logs(str(tmp_log_dir), cm)

        filenames = [t["filename"] for t in targets]
        assert "readme.md" not in filenames
        assert "session_abc_log.txt" in filenames

    def test_ignores_archive_directory(self, tmp_log_dir, tmp_cursor_path):
        """archive/ サブディレクトリ内のファイルはスキャン対象外"""
        from engram.cursor import CursorManager
        from engram.miner import scan_logs

        archive_dir = os.path.join(str(tmp_log_dir), "archive")
        os.makedirs(archive_dir, exist_ok=True)
        _write_log_file(tmp_log_dir, "session_active_log.txt", ["line1"])
        # archive内にもログ風ファイルを配置
        filepath_archive = os.path.join(archive_dir, "session_old_log.txt")
        with open(filepath_archive, "w") as f:
            f.write("old line\n")

        cm = CursorManager(tmp_cursor_path)
        targets = scan_logs(str(tmp_log_dir), cm)

        filenames = [t["filename"] for t in targets]
        assert "session_old_log.txt" not in filenames
        assert "session_active_log.txt" in filenames


# === BDD Scenario 2: read_diff ===

class TestReadDiff:
    def test_reads_from_line_zero(self, tmp_log_dir):
        """last_read_line=0の場合、ファイル全体を返す"""
        from engram.miner import read_diff

        filepath = _write_log_file(tmp_log_dir, "log.txt", ["line1", "line2", "line3"])
        diff = read_diff(filepath, last_read_line=0)

        assert "line1" in diff
        assert "line2" in diff
        assert "line3" in diff

    def test_reads_only_new_lines(self, tmp_log_dir):
        """last_read_line以降の行のみを返す"""
        from engram.miner import read_diff

        filepath = _write_log_file(tmp_log_dir, "log.txt", [f"line{i}" for i in range(1, 11)])
        diff = read_diff(filepath, last_read_line=5)

        assert "line5" not in diff  # 5行目は既読
        assert "line6" in diff
        assert "line10" in diff

    def test_returns_empty_for_fully_read_file(self, tmp_log_dir):
        """全行が既読の場合、空文字列を返す"""
        from engram.miner import read_diff

        filepath = _write_log_file(tmp_log_dir, "log.txt", ["line1", "line2"])
        diff = read_diff(filepath, last_read_line=2)

        assert diff == ""

    def test_returns_empty_for_empty_file(self, tmp_log_dir):
        """空ファイルの場合、空文字列を返す"""
        from engram.miner import read_diff

        filepath = os.path.join(str(tmp_log_dir), "empty.txt")
        with open(filepath, "w") as f:
            pass

        diff = read_diff(filepath, last_read_line=0)
        assert diff == ""


# === BDD Scenario 3: process_log (SKIP) ===

class TestProcessLogSkip:
    def test_skip_does_not_advance_last_read_line(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_skip):
        """LLMがSKIPを返した場合、last_read_lineは進まない"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_skip_log.txt", ["line1", "line2", "line3"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_skip_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_skip, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_skip_log.txt")
        assert cursor["last_read_line"] == 0  # 進んでいない

    def test_skip_updates_mtime(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_skip):
        """LLMがSKIPを返した場合でも、mtimeは現在の値に更新される"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_skip_log.txt", ["line1"])
        current_mtime = os.path.getmtime(filepath)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_skip_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_skip, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_skip_log.txt")
        assert cursor["last_checked_mtime"] == current_mtime


# === BDD Scenario 4: process_log (INSERT) ===

class TestProcessLogInsert:
    def test_insert_advances_last_read_line(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """LLMがINSERTを返した場合、last_read_lineが末尾まで進む"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_ins_log.txt", ["line1", "line2", "line3"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_ins_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_ins_log.txt")
        assert cursor["last_read_line"] == 3

    def test_insert_updates_mtime(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """LLMがINSERTを返した場合、mtimeが更新される"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_ins_log.txt", ["line1"])
        current_mtime = os.path.getmtime(filepath)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_ins_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_ins_log.txt")
        assert cursor["last_checked_mtime"] == current_mtime

    def test_insert_saves_to_db(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """LLMがINSERTを返した場合、DBにレコードが保存される"""
        from engram.cursor import CursorManager
        from engram.miner import process_log
        from engram.db import get_table

        filepath = _write_log_file(tmp_log_dir, "session_ins_log.txt", ["line1"])

        cm = CursorManager(tmp_cursor_path)
        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path)

        table = get_table(db_path=tmp_db_path)
        records = table.to_pandas()
        assert len(records) >= 1


# === BDD Scenario 4b: process_log (recall_fn) ===

class TestProcessLogRecallFn:
    def test_recall_fn_is_called_during_process_log(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """process_log実行時にrecall_fnが呼ばれる"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_recall_log.txt", ["line1", "line2"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_recall_log.txt", last_read_line=0, last_checked_mtime=0.0)

        call_count = {"n": 0}

        def mock_recall_fn(query, **kwargs):
            call_count["n"] += 1
            return []

        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path, recall_fn=mock_recall_fn)

        assert call_count["n"] >= 1  # recall_fnが呼ばれた

    def test_recall_fn_none_uses_default(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """recall_fn=Noneの場合、デフォルトのengram.recall.search_memoriesが使われる（エラーにならない）"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_recall_default_log.txt", ["line1"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_recall_default_log.txt", last_read_line=0, last_checked_mtime=0.0)

        # recall_fn を省略（None）してもエラーにならない
        process_log(filepath, cm, mock_llm_insert, db_path=tmp_db_path, recall_fn=None)

        cursor = cm.get_cursor("session_recall_default_log.txt")
        assert cursor["last_read_line"] == 1


# === BDD Scenario 5: process_log (UPDATE) ===

class TestProcessLogUpdate:
    def test_update_advances_last_read_line(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_update_factory):
        """LLMがUPDATEを返した場合、last_read_lineが末尾まで進む"""
        from engram.cursor import CursorManager
        from engram.miner import process_log
        from engram.save import save_memories, generate_memory_id

        # まずDBに既存レコードを1件用意
        existing_payload = [
            {
                "action": "INSERT",
                "target_id": None,
                "payload": {
                    "event": "既存イベント",
                    "context": "既存コンテキスト",
                    "core_lessons": "既存教訓",
                    "category": "debugging",
                    "tags": ["test"],
                    "related_files": [],
                    "session_id": "session_existing",
                },
                "entities": [],
                "relations": [],
            }
        ]
        save_memories(existing_payload, db_path=tmp_db_path)
        existing_id = generate_memory_id("session_existing", "既存イベント")

        filepath = _write_log_file(tmp_log_dir, "session_upd_log.txt", ["line1", "line2"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_upd_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_update_factory(existing_id), db_path=tmp_db_path)

        cursor = cm.get_cursor("session_upd_log.txt")
        assert cursor["last_read_line"] == 2


# === BDD Scenario 6: process_log (混合) ===

class TestProcessLogMixed:
    def test_mixed_skip_and_insert(self, tmp_log_dir, tmp_cursor_path, tmp_db_path):
        """SKIP+INSERTが混在するレスポンスでは、INSERTがあるためlast_read_lineを進める"""
        def mock_llm_mixed(messages):
            return json.dumps([
                {"action": "SKIP", "reason": "前半は作業中"},
                {
                    "action": "INSERT",
                    "target_id": None,
                    "payload": {
                        "event": "混合テストイベント",
                        "context": "混合テストコンテキスト",
                        "core_lessons": "混合テスト教訓",
                        "category": "debugging",
                        "tags": ["test"],
                        "related_files": [],
                        "session_id": "session_mixed",
                    },
                    "entities": [],
                    "relations": [],
                },
            ], ensure_ascii=False)

        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_mix_log.txt", ["line1", "line2", "line3"])
        current_mtime = os.path.getmtime(filepath)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_mix_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_mixed, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_mix_log.txt")
        # INSERT があるので行は進む
        assert cursor["last_read_line"] == 3
        # mtimeも更新される
        assert cursor["last_checked_mtime"] == current_mtime

    def test_all_skip_does_not_advance(self, tmp_log_dir, tmp_cursor_path, tmp_db_path):
        """全アクションがSKIPの場合、last_read_lineは進まない"""
        def mock_llm_all_skip(messages):
            return json.dumps([
                {"action": "SKIP", "reason": "理由1"},
                {"action": "SKIP", "reason": "理由2"},
            ], ensure_ascii=False)

        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_allskip_log.txt", ["line1", "line2"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_allskip_log.txt", last_read_line=0, last_checked_mtime=0.0)

        process_log(filepath, cm, mock_llm_all_skip, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_allskip_log.txt")
        assert cursor["last_read_line"] == 0


# === BDD Scenario 7: archive_stale_logs ===

class TestArchiveStaleLogs:
    def test_moves_stale_file_to_archive(self, tmp_log_dir, tmp_archive_dir, tmp_cursor_path):
        """TTL超過ファイルがarchive/へ移動される（判定基準はファイルのmtime）"""
        from engram.cursor import CursorManager
        from engram.miner import archive_stale_logs

        filepath = _write_log_file(tmp_log_dir, "session_stale_log.txt", ["old line"])
        # ファイルのmtimeを8日前に設定（TTL判定基準はファイルのmtime）
        old_file_mtime = time.time() - (8 * 86400)
        _set_mtime(filepath, old_file_mtime)

        cm = CursorManager(tmp_cursor_path)
        # cursor の last_checked_mtime は現在時刻にセット（ファイルmtimeのみが古い状態を強制）
        cm.update_cursor("session_stale_log.txt", last_read_line=1, last_checked_mtime=time.time())

        archive_stale_logs(str(tmp_log_dir), str(tmp_archive_dir), cm, ttl_days=7)

        assert not os.path.exists(filepath)
        assert os.path.exists(os.path.join(str(tmp_archive_dir), "session_stale_log.txt"))

    def test_removes_cursor_after_archive(self, tmp_log_dir, tmp_archive_dir, tmp_cursor_path):
        """アーカイブ後にcursor.jsonからエントリが削除される"""
        from engram.cursor import CursorManager
        from engram.miner import archive_stale_logs

        filepath = _write_log_file(tmp_log_dir, "session_stale_log.txt", ["old line"])
        old_file_mtime = time.time() - (8 * 86400)
        _set_mtime(filepath, old_file_mtime)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_stale_log.txt", last_read_line=1, last_checked_mtime=time.time())

        archive_stale_logs(str(tmp_log_dir), str(tmp_archive_dir), cm, ttl_days=7)

        assert "session_stale_log.txt" not in cm.list_cursors()

    def test_does_not_archive_fresh_file(self, tmp_log_dir, tmp_archive_dir, tmp_cursor_path):
        """TTL未満のファイルはアーカイブされない（判定基準はファイルのmtime）"""
        from engram.cursor import CursorManager
        from engram.miner import archive_stale_logs

        filepath = _write_log_file(tmp_log_dir, "session_fresh_log.txt", ["new line"])
        # ファイルのmtimeは現在時刻のまま（デフォルト）

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_fresh_log.txt", last_read_line=1, last_checked_mtime=time.time())

        archive_stale_logs(str(tmp_log_dir), str(tmp_archive_dir), cm, ttl_days=7)

        assert os.path.exists(filepath)
        assert "session_fresh_log.txt" in cm.list_cursors()

    def test_creates_archive_dir_if_not_exists(self, tmp_log_dir, tmp_cursor_path):
        """archive/ディレクトリが存在しない場合、自動作成する"""
        from engram.cursor import CursorManager
        from engram.miner import archive_stale_logs

        archive_dir = os.path.join(str(tmp_log_dir), "archive")
        # archive_dirは作らない

        filepath = _write_log_file(tmp_log_dir, "session_stale_log.txt", ["old line"])
        old_file_mtime = time.time() - (8 * 86400)
        _set_mtime(filepath, old_file_mtime)

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_stale_log.txt", last_read_line=1, last_checked_mtime=time.time())

        archive_stale_logs(str(tmp_log_dir), archive_dir, cm, ttl_days=7)

        assert os.path.isdir(archive_dir)
        assert os.path.exists(os.path.join(archive_dir, "session_stale_log.txt"))


# === BDD Scenario 8: エッジケース ===

class TestEdgeCases:
    def test_process_log_with_no_diff_is_noop(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """差分が0行の場合、LLMを呼ばずに何もしない"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_noop_log.txt", ["line1", "line2"])

        cm = CursorManager(tmp_cursor_path)
        # 既に2行まで読み済み
        cm.update_cursor("session_noop_log.txt", last_read_line=2, last_checked_mtime=0.0)

        call_count = {"n": 0}
        def counting_llm(messages):
            call_count["n"] += 1
            return mock_llm_insert(messages)

        process_log(filepath, cm, counting_llm, db_path=tmp_db_path)

        assert call_count["n"] == 0  # LLMは呼ばれない

    def test_process_log_file_deleted_during_processing(self, tmp_log_dir, tmp_cursor_path, tmp_db_path, mock_llm_insert):
        """処理対象ファイルが存在しない場合、エラーにならず安全にスキップする"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        nonexistent_path = os.path.join(str(tmp_log_dir), "session_gone_log.txt")

        cm = CursorManager(tmp_cursor_path)

        # 例外が出なければOK
        process_log(nonexistent_path, cm, mock_llm_insert, db_path=tmp_db_path)

    def test_llm_returns_invalid_json(self, tmp_log_dir, tmp_cursor_path, tmp_db_path):
        """LLMが不正なJSONを返した場合、エラーにならずlast_read_lineもlast_checked_mtimeも更新しない（次回再試行）"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_badjson_log.txt", ["line1"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_badjson_log.txt", last_read_line=0, last_checked_mtime=0.0)

        def bad_llm(messages):
            return "これはJSONではない"

        process_log(filepath, cm, bad_llm, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_badjson_log.txt")
        assert cursor["last_read_line"] == 0  # 進んでいない
        assert cursor["last_checked_mtime"] == 0.0  # mtimeも更新されない

    def test_llm_returns_empty_array(self, tmp_log_dir, tmp_cursor_path, tmp_db_path):
        """LLMが空配列を返した場合、エラーにならずlast_read_lineもlast_checked_mtimeも更新しない（次回再試行）"""
        from engram.cursor import CursorManager
        from engram.miner import process_log

        filepath = _write_log_file(tmp_log_dir, "session_empty_log.txt", ["line1"])

        cm = CursorManager(tmp_cursor_path)
        cm.update_cursor("session_empty_log.txt", last_read_line=0, last_checked_mtime=0.0)

        def empty_llm(messages):
            return "[]"

        process_log(filepath, cm, empty_llm, db_path=tmp_db_path)

        cursor = cm.get_cursor("session_empty_log.txt")
        assert cursor["last_read_line"] == 0
        assert cursor["last_checked_mtime"] == 0.0  # mtimeも更新されない


# === BDD Scenario 9: sanitize_terminal_output ===

class TestSanitizeTerminalOutput:
    """scriptコマンドの生ログからANSIエスケープシーケンスを除去する"""

    def test_strips_ansi_color_codes(self):
        from engram.miner import sanitize_terminal_output
        raw = "\x1b[38;2;215;119;87mHello\x1b[39m World"
        assert sanitize_terminal_output(raw) == "Hello World"

    def test_strips_csi_sequences(self):
        from engram.miner import sanitize_terminal_output
        raw = "\x1b[?2004h\x1b[?1004hSome text\x1b[0m"
        assert sanitize_terminal_output(raw) == "Some text"

    def test_strips_osc_sequences(self):
        from engram.miner import sanitize_terminal_output
        raw = "\x1b]0;title\x07content"
        assert sanitize_terminal_output(raw) == "content"

    def test_strips_control_chars(self):
        from engram.miner import sanitize_terminal_output
        raw = "hello\x00\x01\x02world"
        assert sanitize_terminal_output(raw) == "helloworld"

    def test_preserves_tabs_and_newlines(self):
        from engram.miner import sanitize_terminal_output
        raw = "line1\n\tindented\nline3"
        assert sanitize_terminal_output(raw) == "line1\n\tindented\nline3"

    def test_collapses_excessive_blank_lines(self):
        from engram.miner import sanitize_terminal_output
        raw = "a\n\n\n\n\nb"
        assert sanitize_terminal_output(raw) == "a\n\nb"

    def test_real_claude_code_output(self):
        """ユーザーが報告した実際のClaude Code出力を処理できる"""
        from engram.miner import sanitize_terminal_output
        raw = (
            "\x1b[?2004h\x1b[?1004h\x1b[>1u\x1b[?25l\x1b[>0q\x1b[c\x1b[<u"
            "\x1b[?1004l\x1b[?2004l\x1b[?2026h"
            "\x1b[38;2;215;119;87m╭───\x1b[1CClaude\x1b[1CCode\x1b[1C"
            "\x1b[38;2;153;153;153mv2.1.74\x1b[1C"
            "\x1b[38;2;215;119;87m────╮\x1b[39m"
        )
        result = sanitize_terminal_output(raw)
        assert "Claude" in result
        assert "v2.1.74" in result
        assert "\x1b" not in result
