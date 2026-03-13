"""共通fixture"""

import json
import os
import shutil
import tempfile

import pytest


@pytest.fixture
def tmp_db_path():
    path = os.path.join(tempfile.mkdtemp(), "test_engram_db")
    yield path
    if os.path.exists(path):
        shutil.rmtree(path)


@pytest.fixture
def tmp_log_dir(tmp_path):
    """short-term-memory/ を模擬する一時ディレクトリ"""
    log_dir = tmp_path / "short-term-memory"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def tmp_archive_dir(tmp_log_dir):
    """archive/ を模擬する一時ディレクトリ（tmp_log_dir 配下に作成）"""
    archive_dir = tmp_log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


@pytest.fixture
def tmp_cursor_path(tmp_path):
    """cursor.json の一時パス"""
    return str(tmp_path / "cursor.json")


@pytest.fixture
def mock_llm_insert():
    """Agent 2のモック: 常にINSERTを1件返す"""
    def _llm_fn(messages):
        return json.dumps([
            {
                "action": "INSERT",
                "target_id": None,
                "payload": {
                    "event": "テストイベント",
                    "context": "テストコンテキスト",
                    "core_lessons": "テスト教訓",
                    "category": "debugging",
                    "tags": ["test"],
                    "related_files": [],
                    "session_id": "session_test",
                },
                "entities": [],
                "relations": [],
            }
        ], ensure_ascii=False)
    return _llm_fn


@pytest.fixture
def mock_llm_skip():
    """Agent 2のモック: 常にSKIPを返す"""
    def _llm_fn(messages):
        return json.dumps([
            {
                "action": "SKIP",
                "reason": "まだ作業中のため。",
            }
        ], ensure_ascii=False)
    return _llm_fn


@pytest.fixture
def mock_llm_update_factory():
    """target_idを受け取ってUPDATEモックを返すファクトリ"""
    def _factory(target_id):
        def _llm_fn(messages):
            return json.dumps([
                {
                    "action": "UPDATE",
                    "target_id": target_id,
                    "payload": {
                        "event": "既存イベント",
                        "context": "更新されたコンテキスト",
                        "core_lessons": "更新された教訓",
                        "category": "debugging",
                        "tags": ["test", "updated"],
                        "related_files": [],
                        "session_id": "session_existing",
                    },
                    "entities": [],
                    "relations": [],
                }
            ], ensure_ascii=False)
        return _llm_fn
    return _factory
