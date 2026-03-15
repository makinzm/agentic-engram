"""
Kuzu Graph DB テスト

BDD Scenarios:
  1. get_graph_db: 存在しないパスで呼ぶとDB+スキーマが作成される
  2. Entity MERGE: 同名Entityを2回syncしても1ノード、mention_count=2
  3. Relation MERGE: 同じsource-target-typeのRelationは重複しない
  4. Memory-Entity紐づけ: sync後にMENTIONSエッジが正しく作成される
  5. 削除: remove_from_graphでMemoryと関連エッジが削除される
  6. Entity mention_count: 削除後にデクリメントされる
  7. 空グラフ: find_related_memoriesは空リストを返す
  8. is_graph_available: パスが存在しない場合False
  9. save_memories + graph_path: INSERTでグラフにも同期される
  10. save_memories graph_path=None: グラフ同期が発生しない（V1互換）
"""

import datetime
import json
import os
import shutil
import tempfile

import pytest


# === BDD Scenario 1: get_graph_db ===

class TestGetGraphDb:
    def test_creates_db_and_schema_at_nonexistent_path(self, tmp_graph_path):
        """存在しないパスで呼ぶとDB+スキーマが作成される"""
        from engram.graph import get_graph_db

        assert not os.path.exists(tmp_graph_path)
        db = get_graph_db(tmp_graph_path)
        assert db is not None
        assert os.path.exists(tmp_graph_path)

    def test_schema_tables_exist_after_init(self, tmp_graph_path):
        """初期化後にEntity, Memory, MENTIONS, RELATES_TOが存在する"""
        import kuzu
        from engram.graph import get_graph_db

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)

        # Entity ノードテーブルにクエリ可能
        result = conn.execute("MATCH (e:Entity) RETURN count(e)")
        assert result.has_next()

        # Memory ノードテーブルにクエリ可能
        result = conn.execute("MATCH (m:Memory) RETURN count(m)")
        assert result.has_next()

    def test_idempotent_schema_creation(self, tmp_graph_path):
        """2回呼んでもエラーにならない"""
        from engram.graph import get_graph_db

        db1 = get_graph_db(tmp_graph_path)
        db2 = get_graph_db(tmp_graph_path)
        assert db1 is not None
        assert db2 is not None


# === BDD Scenario 2: Entity MERGE ===

class TestEntityMerge:
    def test_same_entity_twice_results_in_one_node_with_count_2(self, tmp_graph_path):
        """同名Entityを2回syncしても1ノード、mention_count=2"""
        import kuzu
        from engram.graph import get_graph_db, sync_to_graph

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_001",
            event="event 1",
            category="debugging",
            timestamp=ts,
            entities=["Python"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        sync_to_graph(
            memory_id="mem_002",
            event="event 2",
            category="debugging",
            timestamp=ts,
            entities=["Python"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)
        result = conn.execute(
            "MATCH (e:Entity {name: $name}) RETURN e.mention_count",
            {"name": "Python"},
        )
        row = result.get_next()
        assert row[0] == 2


# === BDD Scenario 3: Relation MERGE ===

class TestRelationMerge:
    def test_same_relation_not_duplicated(self, tmp_graph_path):
        """同じsource-target-typeのRelationは重複しない"""
        import kuzu
        from engram.graph import get_graph_db, sync_to_graph

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)
        relations = [{"source": "A", "target": "B", "type": "USES"}]

        sync_to_graph(
            memory_id="mem_001",
            event="event 1",
            category="debugging",
            timestamp=ts,
            entities=["A", "B"],
            relations=relations,
            graph_path=tmp_graph_path,
        )

        # Same memory re-synced (idempotent)
        sync_to_graph(
            memory_id="mem_001",
            event="event 1 updated",
            category="debugging",
            timestamp=ts,
            entities=["A", "B"],
            relations=relations,
            graph_path=tmp_graph_path,
        )

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)
        result = conn.execute(
            "MATCH ()-[r:RELATES_TO]->() RETURN count(r)"
        )
        row = result.get_next()
        assert row[0] == 1


# === BDD Scenario 4: Memory-Entity MENTIONS ===

class TestMentionsEdge:
    def test_mentions_edges_created_after_sync(self, tmp_graph_path):
        """sync後にMENTIONSエッジが正しく作成される"""
        import kuzu
        from engram.graph import get_graph_db, sync_to_graph

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_001",
            event="event about Python and Rust",
            category="debugging",
            timestamp=ts,
            entities=["Python", "Rust"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)
        result = conn.execute(
            "MATCH (m:Memory {id: $mid})-[:MENTIONS]->(e:Entity) "
            "RETURN e.name ORDER BY e.name",
            {"mid": "mem_001"},
        )
        names = []
        while result.has_next():
            names.append(result.get_next()[0])

        assert names == ["Python", "Rust"]


# === BDD Scenario 5: remove_from_graph ===

class TestRemoveFromGraph:
    def test_removes_memory_and_edges(self, tmp_graph_path):
        """remove_from_graphでMemoryと関連エッジが削除される"""
        import kuzu
        from engram.graph import get_graph_db, sync_to_graph, remove_from_graph

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_001",
            event="event",
            category="debugging",
            timestamp=ts,
            entities=["X", "Y"],
            relations=[{"source": "X", "target": "Y", "type": "USES"}],
            graph_path=tmp_graph_path,
        )

        remove_from_graph("mem_001", tmp_graph_path)

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)

        # Memory deleted
        result = conn.execute("MATCH (m:Memory {id: $mid}) RETURN count(m)", {"mid": "mem_001"})
        assert result.get_next()[0] == 0

        # MENTIONS edges deleted
        result = conn.execute("MATCH ()-[r:MENTIONS]->() RETURN count(r)")
        assert result.get_next()[0] == 0

        # RELATES_TO edges for this memory deleted
        result = conn.execute(
            "MATCH ()-[r:RELATES_TO {memory_id: $mid}]->() RETURN count(r)",
            {"mid": "mem_001"},
        )
        assert result.get_next()[0] == 0

    def test_remove_nonexistent_memory_is_noop(self, tmp_graph_path):
        """存在しないmemory_idの削除はエラーにならない"""
        from engram.graph import get_graph_db, remove_from_graph

        get_graph_db(tmp_graph_path)  # init schema
        remove_from_graph("nonexistent_id", tmp_graph_path)  # should not raise


# === BDD Scenario 6: Entity mention_count decrement ===

class TestMentionCountDecrement:
    def test_mention_count_decremented_after_remove(self, tmp_graph_path):
        """削除後にmention_countがデクリメントされる"""
        import kuzu
        from engram.graph import get_graph_db, sync_to_graph, remove_from_graph

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        # 2つのmemoryが同じentityを参照
        sync_to_graph(
            memory_id="mem_001",
            event="event 1",
            category="debugging",
            timestamp=ts,
            entities=["Python"],
            relations=[],
            graph_path=tmp_graph_path,
        )
        sync_to_graph(
            memory_id="mem_002",
            event="event 2",
            category="debugging",
            timestamp=ts,
            entities=["Python"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)

        # mention_count = 2
        result = conn.execute(
            "MATCH (e:Entity {name: $name}) RETURN e.mention_count",
            {"name": "Python"},
        )
        assert result.get_next()[0] == 2

        # 1つ削除
        remove_from_graph("mem_001", tmp_graph_path)

        result = conn.execute(
            "MATCH (e:Entity {name: $name}) RETURN e.mention_count",
            {"name": "Python"},
        )
        assert result.get_next()[0] == 1


# === BDD Scenario 7: 空グラフ ===

class TestEmptyGraph:
    def test_find_related_memories_returns_empty_list(self, tmp_graph_path):
        """空のグラフでfind_related_memoriesは空リストを返す"""
        from engram.graph import get_graph_db, find_related_memories

        get_graph_db(tmp_graph_path)
        result = find_related_memories(["Python"], tmp_graph_path)
        assert result == []


# === BDD Scenario 8: is_graph_available ===

class TestIsGraphAvailable:
    def test_returns_false_for_nonexistent_path(self):
        """パスが存在しない場合False"""
        from engram.graph import is_graph_available

        assert is_graph_available("/tmp/nonexistent_graph_path_xyz") is False

    def test_returns_true_for_valid_graph(self, tmp_graph_path):
        """有効なグラフパスでTrue"""
        from engram.graph import get_graph_db, is_graph_available

        get_graph_db(tmp_graph_path)
        assert is_graph_available(tmp_graph_path) is True


# === BDD Scenario 9: save_memories + graph_path ===

class TestSaveMemoriesWithGraph:
    def test_insert_syncs_to_graph(self, tmp_graph_path):
        """save_memories with graph_path syncs to graph on INSERT"""
        import kuzu
        from engram.save import save_memories
        from engram.graph import get_graph_db

        db_path = os.path.join(tempfile.mkdtemp(), "test_vector_db")

        payload = [
            {
                "action": "INSERT",
                "payload": {
                    "event": "graph sync test event",
                    "context": "test context",
                    "core_lessons": "test lessons",
                    "category": "debugging",
                    "tags": ["test"],
                    "related_files": [],
                    "session_id": "session_graph_001",
                },
                "entities": ["TestEntity"],
                "relations": [],
            }
        ]

        result = save_memories(payload, db_path=db_path, graph_path=tmp_graph_path)
        assert result["inserted"] == 1

        # Verify graph has the memory and entity
        db = get_graph_db(tmp_graph_path)
        conn = kuzu.Connection(db)

        result = conn.execute("MATCH (m:Memory) RETURN count(m)")
        assert result.get_next()[0] == 1

        result = conn.execute("MATCH (e:Entity {name: $name}) RETURN e.mention_count", {"name": "TestEntity"})
        assert result.get_next()[0] == 1

        # Cleanup
        if os.path.exists(db_path):
            shutil.rmtree(db_path)


# === BDD Scenario 10: save_memories graph_path=None (V1互換) ===

class TestSaveMemoriesV1Compat:
    def test_graph_path_none_does_not_sync(self, tmp_graph_path):
        """graph_path=None ではグラフ同期が発生しない"""
        from engram.save import save_memories

        db_path = os.path.join(tempfile.mkdtemp(), "test_vector_db_v1")

        payload = [
            {
                "action": "INSERT",
                "payload": {
                    "event": "v1 compat test",
                    "context": "test",
                    "core_lessons": "test",
                    "category": "debugging",
                    "tags": [],
                    "related_files": [],
                    "session_id": "session_v1",
                },
                "entities": [],
                "relations": [],
            }
        ]

        # No graph_path (default None) - should work exactly as V1
        result = save_memories(payload, db_path=db_path)
        assert result["inserted"] == 1

        # Graph DB should not exist at tmp_graph_path
        assert not os.path.exists(tmp_graph_path)

        # Cleanup
        if os.path.exists(db_path):
            shutil.rmtree(db_path)


# === Additional: get_entity_neighborhood, get_graph_stats, find_related_memories ===

class TestFindRelatedMemories:
    def test_finds_memories_via_entity(self, tmp_graph_path):
        """エンティティ経由でメモリを検索できる"""
        from engram.graph import sync_to_graph, find_related_memories

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_find_1",
            event="Python debugging",
            category="debugging",
            timestamp=ts,
            entities=["Python", "debugger"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        sync_to_graph(
            memory_id="mem_find_2",
            event="Rust compilation",
            category="debugging",
            timestamp=ts,
            entities=["Rust"],
            relations=[],
            graph_path=tmp_graph_path,
        )

        results = find_related_memories(["Python"], tmp_graph_path)
        memory_ids = [r["id"] for r in results]
        assert "mem_find_1" in memory_ids
        assert "mem_find_2" not in memory_ids

    def test_finds_memories_via_multi_hop(self, tmp_graph_path):
        """RELATES_TO経由で多段ホップのメモリを検索できる"""
        from engram.graph import sync_to_graph, find_related_memories

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_hop_1",
            event="event about B",
            category="debugging",
            timestamp=ts,
            entities=["B"],
            relations=[{"source": "A", "target": "B", "type": "USES"}],
            graph_path=tmp_graph_path,
        )

        # Search from A (not directly mentioned in any memory)
        results = find_related_memories(["A"], tmp_graph_path, max_hops=2)
        memory_ids = [r["id"] for r in results]
        assert "mem_hop_1" in memory_ids


class TestGetEntityNeighborhood:
    def test_returns_entity_and_neighbors(self, tmp_graph_path):
        """エンティティの周辺グラフを返す"""
        from engram.graph import sync_to_graph, get_entity_neighborhood

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_nb_1",
            event="event about Python",
            category="debugging",
            timestamp=ts,
            entities=["Python", "FastAPI"],
            relations=[{"source": "Python", "target": "FastAPI", "type": "USES"}],
            graph_path=tmp_graph_path,
        )

        result = get_entity_neighborhood("Python", tmp_graph_path)
        assert result["entity"] == "Python"
        assert len(result["memories"]) > 0
        assert len(result["related_entities"]) > 0


class TestGetGraphStats:
    def test_returns_stats(self, tmp_graph_path):
        """ノード数、エッジ数、トップエンティティ等の統計を返す"""
        from engram.graph import sync_to_graph, get_graph_stats

        ts = datetime.datetime(2026, 3, 15, 10, 0, 0)

        sync_to_graph(
            memory_id="mem_stats_1",
            event="stats test",
            category="debugging",
            timestamp=ts,
            entities=["Python", "Rust"],
            relations=[{"source": "Python", "target": "Rust", "type": "COMPLEMENTS"}],
            graph_path=tmp_graph_path,
        )

        stats = get_graph_stats(tmp_graph_path)
        assert stats["memory_count"] >= 1
        assert stats["entity_count"] >= 2
        assert stats["mentions_count"] >= 2
        assert stats["relates_to_count"] >= 1
        assert len(stats["top_entities"]) > 0

    def test_empty_graph_stats(self, tmp_graph_path):
        """空グラフでも統計を返す"""
        from engram.graph import get_graph_db, get_graph_stats

        get_graph_db(tmp_graph_path)
        stats = get_graph_stats(tmp_graph_path)
        assert stats["memory_count"] == 0
        assert stats["entity_count"] == 0
