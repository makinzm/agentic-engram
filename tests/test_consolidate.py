"""Memory Consolidation のテスト."""

import json
import os
import pytest
import numpy as np

from engram.consolidate import find_similar_clusters, process_cluster, _parse_decision
from engram.prompts_consolidate import build_consolidation_prompt


# === テストヘルパー ===

def _insert_test_memories(db_path, memories):
    """テスト用メモリをDBに挿入する。"""
    from engram.db import insert_records
    from engram.embedder import embed_text

    records = []
    for mem in memories:
        tags_str = " ".join(mem.get("tags", []) or [])
        text = f"{mem['event']} {mem.get('context', '')} {tags_str}"
        records.append({
            "id": mem["id"],
            "vector": embed_text(text),
            "event": mem["event"],
            "context": mem.get("context", ""),
            "core_lessons": mem.get("core_lessons", ""),
            "category": mem.get("category", ""),
            "tags": mem.get("tags", []),
            "related_files": mem.get("related_files", []),
            "session_id": mem.get("session_id", "test"),
            "timestamp": None,
            "entities_json": "[]",
            "relations_json": "[]",
            "occurrence_count": mem.get("occurrence_count", 1),
        })
    insert_records(records, db_path)


# === _parse_decision tests ===

class TestParseDecision:
    """LLMレスポンスからのJSON抽出."""

    def test_parse_clean_json(self):
        resp = '{"action": "MERGE", "merged_memory": {"event": "test"}}'
        result = _parse_decision(resp)
        assert result["action"] == "MERGE"

    def test_parse_json_with_markdown_fences(self):
        resp = '```json\n{"action": "KEEP"}\n```'
        result = _parse_decision(resp)
        assert result["action"] == "KEEP"

    def test_parse_json_with_surrounding_text(self):
        resp = 'Here is my decision:\n{"action": "MERGE", "merged_memory": {"event": "x"}}\nDone.'
        result = _parse_decision(resp)
        assert result["action"] == "MERGE"

    def test_parse_no_json_raises(self):
        with pytest.raises(ValueError, match="No JSON"):
            _parse_decision("No JSON here")

    def test_parse_nested_json(self):
        resp = '{"action": "SKILL", "merged_memory": {"event": "x", "tags": ["a"]}, "skill": {"name": "test", "title": "Test", "content": "# Test"}}'
        result = _parse_decision(resp)
        assert result["action"] == "SKILL"
        assert result["skill"]["name"] == "test"


# === build_consolidation_prompt tests ===

class TestBuildConsolidationPrompt:
    """統合プロンプト構築."""

    def test_returns_system_and_user_messages(self):
        memories = [
            {"id": "a", "event": "test1", "context": "", "core_lessons": "", "category": "debug", "tags": [], "related_files": [], "occurrence_count": 1},
            {"id": "b", "event": "test2", "context": "", "core_lessons": "", "category": "debug", "tags": [], "related_files": [], "occurrence_count": 1},
        ]
        messages = build_consolidation_prompt(memories, 2)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_skill_option_excluded_when_count_below_3(self):
        memories = [{"id": "a", "event": "test", "occurrence_count": 1}]
        messages = build_consolidation_prompt(memories, 2)
        user_content = messages[1]["content"]
        assert "SKILL" not in user_content

    def test_skill_option_included_when_count_3_or_more(self):
        memories = [{"id": "a", "event": "test", "occurrence_count": 3}]
        messages = build_consolidation_prompt(memories, 3)
        user_content = messages[1]["content"]
        assert "SKILL" in user_content

    def test_memories_formatted_in_prompt(self):
        memories = [
            {"id": "a", "event": "ESLint v10 broke", "context": "npm", "core_lessons": "pin versions", "category": "config", "tags": ["eslint"], "related_files": ["package.json"], "occurrence_count": 2},
        ]
        messages = build_consolidation_prompt(memories, 2)
        assert "ESLint v10 broke" in messages[1]["content"]
        assert "出現2回" in messages[1]["content"]


# === find_similar_clusters tests ===

class TestFindSimilarClusters:
    """類似クラスタ検出."""

    def test_identical_memories_form_cluster(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "ESLint v10 broke CI because of semver caret", "category": "config"},
            {"id": "b" * 64, "event": "ESLint v10 broke CI due to semver caret allowing major upgrade", "category": "config"},
        ])
        clusters = find_similar_clusters(db_path, threshold=0.85)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_different_memories_no_cluster(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "ESLint v10 broke CI because of semver caret", "category": "config"},
            {"id": "b" * 64, "event": "Playwright screenshot test failed on font rendering", "category": "testing"},
        ])
        clusters = find_similar_clusters(db_path, threshold=0.90)
        assert len(clusters) == 0

    def test_empty_db_returns_empty(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        clusters = find_similar_clusters(db_path, threshold=0.90)
        assert clusters == []

    def test_single_record_returns_empty(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "test", "category": "debug"},
        ])
        clusters = find_similar_clusters(db_path, threshold=0.90)
        assert clusters == []

    def test_occurrence_count_preserved(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "ESLint v10 broke", "category": "config", "occurrence_count": 2},
            {"id": "b" * 64, "event": "ESLint v10 broke CI", "category": "config", "occurrence_count": 1},
        ])
        clusters = find_similar_clusters(db_path, threshold=0.85)
        assert len(clusters) == 1
        counts = [m.get("occurrence_count", 1) for m in clusters[0]]
        assert sorted(counts) == [1, 2]

    def test_threshold_affects_clustering(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "ESLint v10 broke CI because of semver caret", "category": "config"},
            {"id": "b" * 64, "event": "ESLint v10 broke CI due to semver caret upgrade", "category": "config"},
        ])
        # 高い閾値ではクラスタ化される
        clusters_high = find_similar_clusters(db_path, threshold=0.85)
        # 極端に高い閾値ではクラスタ化されない可能性
        clusters_extreme = find_similar_clusters(db_path, threshold=0.999)
        assert len(clusters_high) >= len(clusters_extreme)


# === process_cluster tests ===

class TestProcessCluster:
    """クラスタ処理."""

    def test_keep_decision_no_changes(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "test1", "category": "debug"},
            {"id": "b" * 64, "event": "test2", "category": "debug"},
        ])
        cluster = [
            {"id": "a" * 64, "event": "test1", "category": "debug", "occurrence_count": 1},
            {"id": "b" * 64, "event": "test2", "category": "debug", "occurrence_count": 1},
        ]
        llm_fn = lambda msgs: '{"action": "KEEP"}'
        result = process_cluster(cluster, llm_fn, db_path)
        assert result["action"] == "KEEP"

        # DB に変更なし
        from engram.db import get_table
        t = get_table(db_path)
        assert t.count_rows() == 2

    def test_merge_deletes_old_and_inserts_new(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "ESLint v10 broke", "context": "npm", "core_lessons": "pin", "category": "config", "tags": ["eslint"], "related_files": ["package.json"]},
            {"id": "b" * 64, "event": "ESLint v10 CI failure", "context": "npm", "core_lessons": "pin versions", "category": "config", "tags": ["eslint", "ci"], "related_files": ["package.json"]},
        ])
        cluster = [
            {"id": "a" * 64, "event": "ESLint v10 broke", "context": "npm", "core_lessons": "pin", "category": "config", "tags": ["eslint"], "related_files": ["package.json"], "occurrence_count": 1},
            {"id": "b" * 64, "event": "ESLint v10 CI failure", "context": "npm", "core_lessons": "pin versions", "category": "config", "tags": ["eslint", "ci"], "related_files": ["package.json"], "occurrence_count": 1},
        ]

        merged_response = json.dumps({
            "action": "MERGE",
            "merged_memory": {
                "event": "ESLint v10 broke CI due to semver caret",
                "context": "npm package management",
                "core_lessons": "Pin major versions with ~",
                "category": "config",
                "tags": ["eslint", "ci", "semver"],
                "related_files": ["package.json"],
                "entities": ["ESLint"],
                "relations": [],
            }
        })
        llm_fn = lambda msgs: merged_response

        result = process_cluster(cluster, llm_fn, db_path)
        assert result["action"] == "MERGE"
        assert len(result["deleted_ids"]) == 2
        assert result["total_occurrence_count"] == 2

        # DB: 元の2件が削除され、新しい1件が追加
        from engram.db import get_table
        t = get_table(db_path)
        assert t.count_rows() == 1

    def test_dry_run_does_not_modify_db(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "test1", "category": "debug"},
            {"id": "b" * 64, "event": "test2", "category": "debug"},
        ])
        cluster = [
            {"id": "a" * 64, "event": "test1", "category": "debug", "occurrence_count": 1},
            {"id": "b" * 64, "event": "test2", "category": "debug", "occurrence_count": 1},
        ]
        merged_response = json.dumps({"action": "MERGE", "merged_memory": {"event": "merged", "context": "", "core_lessons": "", "category": "debug", "tags": [], "related_files": [], "entities": [], "relations": []}})
        llm_fn = lambda msgs: merged_response

        result = process_cluster(cluster, llm_fn, db_path, dry_run=True)
        assert result["action"] == "MERGE"

        from engram.db import get_table
        t = get_table(db_path)
        assert t.count_rows() == 2  # 変更なし

    def test_skill_writes_file(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        skills_dir = str(tmp_path / "skills")
        _insert_test_memories(db_path, [
            {"id": "a" * 64, "event": "test1", "category": "debug", "occurrence_count": 2},
            {"id": "b" * 64, "event": "test2", "category": "debug", "occurrence_count": 1},
        ])
        cluster = [
            {"id": "a" * 64, "event": "test1", "category": "debug", "occurrence_count": 2},
            {"id": "b" * 64, "event": "test2", "category": "debug", "occurrence_count": 1},
        ]
        skill_response = json.dumps({
            "action": "SKILL",
            "merged_memory": {"event": "merged", "context": "", "core_lessons": "", "category": "debug", "tags": [], "related_files": [], "entities": [], "relations": []},
            "skill": {"name": "test-skill", "title": "テストスキル", "content": "## 概要\nテスト"}
        })
        llm_fn = lambda msgs: skill_response

        result = process_cluster(cluster, llm_fn, db_path, skills_dir=skills_dir)
        assert result["action"] == "SKILL"
        assert result["skill_name"] == "test-skill"

        # スキルファイルが存在する
        skill_path = os.path.join(skills_dir, "test-skill.md")
        assert os.path.exists(skill_path)
        content = open(skill_path).read()
        assert "テストスキル" in content

    def test_llm_error_returns_error_action(self, tmp_path):
        db_path = str(tmp_path / "test_db")
        cluster = [
            {"id": "a" * 64, "event": "test", "category": "debug", "occurrence_count": 1},
        ]
        llm_fn = lambda msgs: (_ for _ in ()).throw(RuntimeError("LLM failed"))

        result = process_cluster(cluster, llm_fn, db_path)
        assert result["action"] == "ERROR"
