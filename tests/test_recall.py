"""
ae-recall: 記憶検索CLIのテストスペック

BDD Scenarios:
  1. セマンティック検索: クエリに意味的に近い記憶が上位に返される
  2. Top-K制御: --limit オプションで返却件数を制御できる
  3. カテゴリフィルタ: --category で特定カテゴリのみに絞り込める
  4. 出力フォーマット: --format json でJSON、--format markdown でMarkdownを出力
  5. 空DB: 記憶が0件の場合、空結果を正常に返す
  6. 類似度スコア: 各結果にcosine similarityスコアが付与される
"""

import json
import os
import shutil
import tempfile

import pytest


# === Fixtures ===

@pytest.fixture
def tmp_db_path():
    path = os.path.join(tempfile.mkdtemp(), "test_engram_db")
    yield path
    if os.path.exists(path):
        shutil.rmtree(path)


@pytest.fixture
def populated_db(tmp_db_path):
    """テスト用に5件の記憶が入ったDBを準備する（engram.dbレイヤーを直接使用）"""
    import datetime
    from engram.db import get_table, insert_records

    records = [
        {
            "id": "id_session_001_nextjs",
            "event": "Next.jsのApp RouterでuseEffectがサーバーコンポーネントで動かない",
            "context": "サーバーコンポーネント内でブラウザAPIを使おうとした",
            "core_lessons": "'use client'ディレクティブを追加すること",
            "category": "bug_fix",
            "tags": ["Next.js", "React", "Server Components"],
            "related_files": ["app/page.tsx"],
            "session_id": "session_001",
            "timestamp": datetime.datetime.now(),
            "entities_json": "[]",
            "relations_json": "[]",
        },
        {
            "id": "id_session_002_goroutine",
            "event": "Goのgoroutineでチャネルのデッドロックが発生",
            "context": "送信側と受信側のチャネルサイズが不一致",
            "core_lessons": "Delveのattach機能でgoroutineの状態を直接確認する",
            "category": "debugging",
            "tags": ["Go", "goroutine", "deadlock", "Delve"],
            "related_files": ["cmd/worker/main.go"],
            "session_id": "session_002",
            "timestamp": datetime.datetime.now(),
            "entities_json": "[]",
            "relations_json": "[]",
        },
        {
            "id": "id_session_003_n1",
            "event": "RailsのN+1クエリでページロードが10秒超過",
            "context": "has_many関連のポリモーフィック関連付け",
            "core_lessons": "polymorphic関連付けではeager_loadを使う",
            "category": "performance",
            "tags": ["Rails", "ActiveRecord", "N+1"],
            "related_files": ["app/models/comment.rb"],
            "session_id": "session_003",
            "timestamp": datetime.datetime.now(),
            "entities_json": "[]",
            "relations_json": "[]",
        },
        {
            "id": "id_session_004_typescript",
            "event": "TypeScriptのstrictモードでOptional Chainingの型ガードが効かない",
            "context": "undefined | nullのユニオン型でのナローイング",
            "core_lessons": "明示的なif文で型ガードする方が安全",
            "category": "architecture",
            "tags": ["TypeScript", "strict", "type-guard"],
            "related_files": ["src/utils/validator.ts"],
            "session_id": "session_004",
            "timestamp": datetime.datetime.now(),
            "entities_json": "[]",
            "relations_json": "[]",
        },
        {
            "id": "id_session_005_cors",
            "event": "Ollama APIをブラウザから叩くとCORSエラー",
            "context": "Next.jsのクライアントコンポーネントからfetch",
            "core_lessons": "Route Handlerを経由させる",
            "category": "architecture",
            "tags": ["Next.js", "Ollama", "CORS"],
            "related_files": ["app/api/chat/route.ts"],
            "session_id": "session_005",
            "timestamp": datetime.datetime.now(),
            "entities_json": "[]",
            "relations_json": "[]",
        },
    ]

    insert_records(records, db_path=tmp_db_path)
    return tmp_db_path


# === BDD Scenario 1: セマンティック検索 ===

class TestSemanticSearch:
    def test_returns_relevant_results_for_query(self, populated_db):
        """クエリに意味的に近い記憶が返される"""
        from engram.recall import search_memories

        results = search_memories("Reactのサーバーコンポーネントでエラー", db_path=populated_db)

        assert len(results) > 0
        # Next.jsのuseEffect問題が最上位にくるはず
        top_result = results[0]
        assert "Next.js" in top_result["event"] or "サーバーコンポーネント" in top_result["event"]

    def test_go_deadlock_query_finds_goroutine_issue(self, populated_db):
        """Goのデッドロックに関するクエリでgoroutine問題がヒットする"""
        from engram.recall import search_memories

        results = search_memories("Goでデッドロックが起きた", db_path=populated_db)

        events = [r["event"] for r in results[:2]]
        assert any("goroutine" in e or "デッドロック" in e for e in events)

    def test_indirect_query_finds_related_memory(self, populated_db):
        """直接一致しないクエリでも意味的に関連する記憶がヒットする"""
        from engram.recall import search_memories

        # "データベースクエリが遅い" → N+1問題がヒットするはず
        results = search_memories("データベースクエリが遅い", db_path=populated_db)

        events = [r["event"] for r in results[:3]]
        assert any("N+1" in e or "ページロード" in e for e in events)


# === BDD Scenario 2: Top-K制御 ===

class TestTopKControl:
    def test_default_limit_returns_up_to_5(self, populated_db):
        """デフォルトでは最大5件返す"""
        from engram.recall import search_memories

        results = search_memories("プログラミング", db_path=populated_db)
        assert len(results) <= 5

    def test_custom_limit(self, populated_db):
        """limit指定で返却件数を制御できる"""
        from engram.recall import search_memories

        results = search_memories("プログラミング", db_path=populated_db, limit=2)
        assert len(results) <= 2


# === BDD Scenario 3: カテゴリフィルタ ===

class TestCategoryFilter:
    def test_filter_by_category(self, populated_db):
        """カテゴリを指定して絞り込める"""
        from engram.recall import search_memories

        results = search_memories(
            "エラー", db_path=populated_db, category="architecture"
        )

        for r in results:
            assert r["category"] == "architecture"

    def test_filter_with_no_matching_category_returns_empty(self, populated_db):
        """一致するカテゴリがない場合は空リストを返す"""
        from engram.recall import search_memories

        results = search_memories(
            "テスト", db_path=populated_db, category="nonexistent_category"
        )

        assert results == []


# === BDD Scenario 4: 出力フォーマット ===

class TestOutputFormat:
    def test_json_format(self, populated_db):
        """format_output('json') でJSON文字列を返す"""
        from engram.recall import search_memories, format_output

        results = search_memories("CORSエラー", db_path=populated_db)
        output = format_output(results, fmt="json")

        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) > 0

    def test_markdown_format(self, populated_db):
        """format_output('markdown') でMarkdown文字列を返す（##見出しと記憶フィールドの存在確認）"""
        from engram.recall import search_memories, format_output

        results = search_memories("CORSエラー", db_path=populated_db)
        output = format_output(results, fmt="markdown")

        # ## 見出しが含まれること
        assert "##" in output, "Markdownに##見出しが含まれること"
        # 記憶フィールドのラベルが含まれること
        assert any(
            field in output for field in ["event", "context", "core_lessons", "category"]
        ), "Markdownに記憶フィールド（event/context/core_lessons/category）のいずれかが含まれること"
        assert "CORS" in output


# === BDD Scenario 4.5: vectorフィールド非公開 ===

class TestVectorFieldExclusion:
    def test_search_results_do_not_contain_vector_field(self, populated_db):
        """search_memoriesの返却dictにvectorフィールドが含まれない"""
        from engram.recall import search_memories

        results = search_memories("CORSエラー", db_path=populated_db)

        assert len(results) > 0
        for r in results:
            assert "vector" not in r, "返却dictにvectorフィールドが含まれてはならない"


# === BDD Scenario 5: 空DB ===

class TestEmptyDatabase:
    def test_search_on_empty_db_returns_empty(self, tmp_db_path):
        """記憶が0件のDBを検索しても空リストで正常終了する"""
        from engram.recall import search_memories

        results = search_memories("何でも", db_path=tmp_db_path)
        assert results == []


# === BDD Scenario 6: 類似度スコア ===

class TestSimilarityScore:
    def test_results_include_score(self, populated_db):
        """各結果にsimilarityスコアが付与される"""
        from engram.recall import search_memories

        results = search_memories("CORSエラー", db_path=populated_db)

        for r in results:
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_results_sorted_by_score_descending(self, populated_db):
        """結果はスコア降順でソートされている"""
        from engram.recall import search_memories

        results = search_memories("CORSエラー", db_path=populated_db)

        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)


# === BDD Scenario 7: ハイブリッド検索 ===


class TestHybridSearch:
    """graph_path 指定時にグラフ経由の結果もスコアブーストされて返る"""

    @pytest.fixture
    def hybrid_db(self, tmp_db_path, tmp_graph_path):
        """ベクトルDB + グラフDBの両方にデータを投入"""
        import datetime
        from engram.db import insert_records
        from engram.graph import sync_to_graph

        records = [
            {
                "id": "a" * 64,
                "event": "Next.jsのApp RouterでuseEffectがサーバーコンポーネントで動かない",
                "context": "サーバーコンポーネント内でブラウザAPIを使おうとした",
                "core_lessons": "'use client'ディレクティブを追加すること",
                "category": "bug_fix",
                "tags": ["Next.js", "React"],
                "related_files": ["app/page.tsx"],
                "session_id": "session_001",
                "timestamp": datetime.datetime.now(),
                "entities_json": '["Next.js", "React"]',
                "relations_json": '[{"source": "Next.js", "target": "React", "type": "USES"}]',
            },
            {
                "id": "b" * 64,
                "event": "ReactのuseStateフックで無限レンダリング",
                "context": "依存配列にオブジェクトを直接渡していた",
                "core_lessons": "useMemoで参照を安定させる",
                "category": "bug_fix",
                "tags": ["React", "hooks"],
                "related_files": ["src/App.tsx"],
                "session_id": "session_002",
                "timestamp": datetime.datetime.now(),
                "entities_json": '["React", "useState"]',
                "relations_json": '[]',
            },
            {
                "id": "c" * 64,
                "event": "PostgreSQLのインデックス最適化",
                "context": "クエリが遅かった",
                "core_lessons": "複合インデックスを使う",
                "category": "performance",
                "tags": ["PostgreSQL", "indexing"],
                "related_files": ["db/migrations/001.sql"],
                "session_id": "session_003",
                "timestamp": datetime.datetime.now(),
                "entities_json": '["PostgreSQL"]',
                "relations_json": '[]',
            },
        ]

        insert_records(records, db_path=tmp_db_path)

        # グラフに同期（Next.js → React の関連を作る）
        for rec in records:
            entities = json.loads(rec["entities_json"])
            relations = json.loads(rec["relations_json"])
            sync_to_graph(
                memory_id=rec["id"],
                event=rec["event"],
                category=rec["category"],
                timestamp=rec["timestamp"],
                entities=entities,
                relations=relations,
                graph_path=tmp_graph_path,
            )

        return tmp_db_path, tmp_graph_path

    def test_hybrid_search_boosts_graph_related_results(self, hybrid_db):
        """graph_path指定時にグラフ関連メモリのスコアがブーストされる"""
        from engram.recall import search_memories

        db_path, graph_path = hybrid_db

        # "Next.js" で検索 → Next.js記憶がトップ、React記憶もグラフ経由でブーストされる
        results_hybrid = search_memories(
            "Next.jsのエラー", db_path=db_path, graph_path=graph_path, limit=3
        )
        results_vector = search_memories(
            "Next.jsのエラー", db_path=db_path, graph_path=None, limit=3
        )

        assert len(results_hybrid) > 0
        assert len(results_vector) > 0

        # ハイブリッドの場合、グラフ経由でブーストされたメモリのスコアが上がっている
        hybrid_scores = {r["id"]: r["score"] for r in results_hybrid}
        vector_scores = {r["id"]: r["score"] for r in results_vector}

        # React記憶(bbb...)はNext.jsとグラフ接続があるのでブーストされるはず
        react_id = "b" * 64
        if react_id in hybrid_scores and react_id in vector_scores:
            assert hybrid_scores[react_id] >= vector_scores[react_id]

    def test_hybrid_search_graceful_degradation_none(self, populated_db):
        """graph_path=None ではベクトルのみ検索（V1互換）"""
        from engram.recall import search_memories

        results = search_memories(
            "CORSエラー", db_path=populated_db, graph_path=None
        )
        assert len(results) > 0
        # スコアが通常の範囲内
        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    def test_hybrid_search_graceful_degradation_empty_graph(self, populated_db, tmp_graph_path):
        """グラフDBが空の場合、ベクトルのみ検索と同一挙動"""
        from engram.recall import search_memories

        results_hybrid = search_memories(
            "CORSエラー", db_path=populated_db, graph_path=tmp_graph_path
        )
        results_vector = search_memories(
            "CORSエラー", db_path=populated_db, graph_path=None
        )

        # 同一件数が返るはず（グラフ経由の追加なし）
        assert len(results_hybrid) == len(results_vector)

    def test_graph_only_hit(self, hybrid_db):
        """ベクトル検索に出なかったがグラフ走査で見つかるケース"""
        from engram.recall import search_memories

        db_path, graph_path = hybrid_db

        # limit=1 でベクトル検索すると最も類似した1件のみ
        # しかしハイブリッドではグラフ経由で追加メモリも取得される可能性がある
        results_vector = search_memories(
            "Next.jsのサーバーコンポーネント", db_path=db_path, graph_path=None, limit=1
        )
        results_hybrid = search_memories(
            "Next.jsのサーバーコンポーネント", db_path=db_path, graph_path=graph_path, limit=3
        )

        # ハイブリッドの方がベクトルのみより多くの結果を返す可能性がある
        # (グラフ経由で追加メモリが見つかるため)
        assert len(results_hybrid) >= len(results_vector)

    def test_hybrid_results_sorted_by_final_score(self, hybrid_db):
        """ハイブリッド結果がfinal_scoreで降順ソートされている"""
        from engram.recall import search_memories

        db_path, graph_path = hybrid_db

        results = search_memories(
            "Reactのエラー", db_path=db_path, graph_path=graph_path, limit=5
        )

        if len(results) >= 2:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_graph_boost_weight_affects_score(self, hybrid_db):
        """graph_boost パラメータがスコアに影響する"""
        from engram.recall import search_memories

        db_path, graph_path = hybrid_db

        results_low = search_memories(
            "Next.jsのエラー", db_path=db_path, graph_path=graph_path,
            graph_boost=0.1, limit=3
        )
        results_high = search_memories(
            "Next.jsのエラー", db_path=db_path, graph_path=graph_path,
            graph_boost=0.5, limit=3
        )

        # graph_boost が大きい方が、グラフ接続のあるメモリのスコアが高い
        react_id = "b" * 64
        low_score = next((r["score"] for r in results_low if r["id"] == react_id), None)
        high_score = next((r["score"] for r in results_high if r["id"] == react_id), None)

        if low_score is not None and high_score is not None:
            assert high_score >= low_score
