"""
ae-console: 管理UIロジック層のテストスペック

BDD Scenarios:
  1. get_all_memories: テーブルが空なら空リスト、データがあれば全件返す
  2. get_stats: 件数・カテゴリ別分布を正しく返す
  3. delete_memory: 指定IDの記憶を削除できる
  4. delete_memory: 存在しないIDではFalseを返す
  5. get_all_memories: 返却dictにvectorフィールドを含めない
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from typing import Optional, List

import pytest


@pytest.fixture
def tmp_db_path():
    path = os.path.join(tempfile.mkdtemp(), "test_console_db")
    yield path
    if os.path.exists(path):
        shutil.rmtree(path)


def _seed_memories(db_path: str, count: int = 3, categories: Optional[List[str]] = None):
    """テスト用に記憶をDBに直接投入するヘルパー"""
    from engram.save import save_memories

    if categories is None:
        categories = ["debugging", "architecture", "debugging"]

    payload = []
    for i in range(count):
        payload.append(
            {
                "action": "INSERT",
                "target_id": None,
                "payload": {
                    "event": f"テストイベント{i}",
                    "context": f"コンテキスト{i}",
                    "core_lessons": f"教訓{i}",
                    "category": categories[i % len(categories)],
                    "tags": [f"tag{i}"],
                    "related_files": [f"file{i}.py"],
                    "session_id": f"session_{i}",
                },
                "entities": [],
                "relations": [],
            }
        )
    save_memories(payload, db_path=db_path)


# === Scenario 1: get_all_memories ===


class TestGetAllMemories:
    def test_empty_db_returns_empty_list(self, tmp_db_path):
        """テーブルが存在しない場合、空リストを返す"""
        from engram.console import get_all_memories

        result = get_all_memories(tmp_db_path)
        assert result == []

    def test_returns_all_records(self, tmp_db_path):
        """データがある場合、全件をdictのリストで返す"""
        from engram.console import get_all_memories

        _seed_memories(tmp_db_path, count=3)
        result = get_all_memories(tmp_db_path)
        assert len(result) == 3

    def test_records_contain_expected_fields(self, tmp_db_path):
        """返却されるdictに主要フィールドが含まれる"""
        from engram.console import get_all_memories

        _seed_memories(tmp_db_path, count=1, categories=["architecture"])
        result = get_all_memories(tmp_db_path)
        assert len(result) == 1
        rec = result[0]
        for field in ["id", "event", "context", "core_lessons", "category", "tags", "session_id"]:
            assert field in rec, f"Missing field: {field}"

    def test_records_do_not_contain_vector(self, tmp_db_path):
        """返却されるdictにvectorフィールドを含めない"""
        from engram.console import get_all_memories

        _seed_memories(tmp_db_path, count=1)
        result = get_all_memories(tmp_db_path)
        assert "vector" not in result[0]


# === Scenario 2: get_stats ===


class TestGetStats:
    def test_empty_db_returns_zero_stats(self, tmp_db_path):
        """テーブルが空なら total=0, categories={} を返す"""
        from engram.console import get_stats

        stats = get_stats(tmp_db_path)
        assert stats["total"] == 0
        assert stats["categories"] == {}

    def test_stats_with_data(self, tmp_db_path):
        """データがある場合、totalと正しいカテゴリ別分布を返す"""
        from engram.console import get_stats

        _seed_memories(tmp_db_path, count=3, categories=["debugging", "architecture", "debugging"])
        stats = get_stats(tmp_db_path)
        assert stats["total"] == 3
        assert stats["categories"]["debugging"] == 2
        assert stats["categories"]["architecture"] == 1

    def test_stats_single_category(self, tmp_db_path):
        """全記憶が同一カテゴリの場合"""
        from engram.console import get_stats

        _seed_memories(tmp_db_path, count=2, categories=["performance"])
        stats = get_stats(tmp_db_path)
        assert stats["total"] == 2
        assert stats["categories"] == {"performance": 2}


# === Scenario 3: delete_memory ===


class TestDeleteMemory:
    def test_delete_existing_memory(self, tmp_db_path):
        """存在するIDを指定して削除するとTrueを返し、件数が減る"""
        from engram.console import get_all_memories, delete_memory

        _seed_memories(tmp_db_path, count=2)
        memories = get_all_memories(tmp_db_path)
        assert len(memories) == 2

        target_id = memories[0]["id"]
        result = delete_memory(target_id, tmp_db_path)
        assert result is True

        remaining = get_all_memories(tmp_db_path)
        assert len(remaining) == 1
        assert all(m["id"] != target_id for m in remaining)

    def test_delete_nonexistent_memory_returns_false(self, tmp_db_path):
        """存在しないIDを指定するとFalseを返す"""
        from engram.console import delete_memory

        # 有効なSHA-256形式だが存在しないID
        fake_id = "a" * 64
        result = delete_memory(fake_id, tmp_db_path)
        assert result is False

    @pytest.mark.parametrize("invalid_id", [
        "",                      # 空文字
        "abc123",                # 短すぎる
        "G" * 64,                # 非16進数文字
        "a" * 63,                # 63文字（1文字不足）
        "a" * 65,                # 65文字（1文字超過）
        "A" * 64,                # 大文字16進数（不正）
    ])
    def test_delete_invalid_id_format_returns_false(self, tmp_db_path, invalid_id):
        """不正なID形式を指定するとFalseを返す（DBアクセスなし）"""
        from engram.console import delete_memory

        result = delete_memory(invalid_id, tmp_db_path)
        assert result is False

    def test_delete_all_memories_one_by_one(self, tmp_db_path):
        """全件を1件ずつ削除できる"""
        from engram.console import get_all_memories, delete_memory

        _seed_memories(tmp_db_path, count=3)
        memories = get_all_memories(tmp_db_path)

        for m in memories:
            assert delete_memory(m["id"], tmp_db_path) is True

        assert get_all_memories(tmp_db_path) == []
