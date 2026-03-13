"""
PoC: Mem0 + ChromaDB をローカルembeddingのみで動作させる検証
外部API (OpenAI等) を一切使わず、sentence-transformers でembeddingを生成する
"""

import os
import shutil
import tempfile
import json
import time

# テスト用の一時ディレクトリ
TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "engram_poc_test")

# クリーンスタート
if os.path.exists(TEST_DB_PATH):
    shutil.rmtree(TEST_DB_PATH)

print("=" * 60)
print("PoC: Mem0 ローカル完結検証")
print("=" * 60)

# --- Step 1: Mem0の設定 (外部API不使用) ---
print("\n[Step 1] Mem0をローカルembedding設定で初期化...")

from mem0 import Memory

config = {
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "all-MiniLM-L6-v2",
            # "model": "sentence-transformers/all-MiniLM-L6-v2",  # フルネームでも可
        },
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "engram_poc",
            "path": TEST_DB_PATH,
        },
    },
    # LLM設定を明示的にOFFにできるか確認
    # Mem0はadd時にLLMで要約/抽出を行うため、LLMが必須かどうかがポイント
}

try:
    memory = Memory.from_config(config)
    print("  -> Memory インスタンス生成: OK")
except Exception as e:
    print(f"  -> Memory インスタンス生成: FAILED - {e}")
    raise

# --- Step 2: 記憶の保存 (add) ---
print("\n[Step 2] 記憶の保存テスト (add)...")

test_memories = [
    "Next.jsのApp RouterでuseEffectがサーバーコンポーネントで動かないバグに遭遇。'use client'ディレクティブの追加で解決した。",
    "ChromaDBのpersist_directoryオプションが非推奨になっていた。Settingsオブジェクト経由でpersist_implとchroma_db_implを指定する方式に変更が必要。",
    "GoのgoroutineでチャネルのデッドロックをデバッグするのにDelveのattach機能が有効だった。pprofよりも直接的に原因を特定できる。",
    "RailsのN+1問題をBulletgemで検知し、includesで解決。ただしpolymorphic関連付けではeager_loadを使う必要があった。",
    "TypeScriptのstrictモードでは、undefinedチェックをOptional Chainingだけに頼ると型ガードが効かないケースがある。明示的なif文の方が安全。",
]

try:
    for i, mem_text in enumerate(test_memories):
        result = memory.add(mem_text, user_id="test_user")
        print(f"  [{i+1}] 保存OK: {json.dumps(result, ensure_ascii=False, default=str)[:120]}...")
    print("  -> 全件保存: OK")
except Exception as e:
    print(f"  -> 保存: FAILED - {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    print("\n  *** LLMなしでのadd()が失敗した場合、Mem0はLLM依存の可能性が高い ***")

# --- Step 3: 記憶の検索 (search) ---
print("\n[Step 3] 記憶の検索テスト (search)...")

queries = [
    "Next.jsでサーバーコンポーネントのエラー",
    "Goのデッドロック",
    "TypeScriptの型安全性",
]

try:
    for query in queries:
        results = memory.search(query, user_id="test_user")
        print(f"\n  Query: '{query}'")
        if hasattr(results, 'results'):
            hits = results.results
        elif isinstance(results, dict) and 'results' in results:
            hits = results['results']
        elif isinstance(results, list):
            hits = results
        else:
            hits = results

        for j, hit in enumerate(hits[:3]):
            if isinstance(hit, dict):
                text = hit.get('memory', hit.get('text', str(hit)))[:80]
                score = hit.get('score', 'N/A')
            else:
                text = str(hit)[:80]
                score = 'N/A'
            print(f"    [{j+1}] (score={score}) {text}")
    print("\n  -> 検索: OK")
except Exception as e:
    print(f"  -> 検索: FAILED - {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# --- Step 4: 記憶の全件取得 ---
print("\n[Step 4] 記憶の全件取得テスト (get_all)...")

try:
    all_memories = memory.get_all(user_id="test_user")
    if hasattr(all_memories, 'results'):
        items = all_memories.results
    elif isinstance(all_memories, dict) and 'results' in all_memories:
        items = all_memories['results']
    elif isinstance(all_memories, list):
        items = all_memories
    else:
        items = all_memories
    print(f"  -> 件数: {len(items)}")
    for item in items:
        if isinstance(item, dict):
            print(f"    - {item.get('memory', item.get('text', str(item)))[:80]}")
        else:
            print(f"    - {str(item)[:80]}")
    print("  -> 全件取得: OK")
except Exception as e:
    print(f"  -> 全件取得: FAILED - {type(e).__name__}: {e}")

# --- Step 5: 永続化の確認 ---
print("\n[Step 5] 永続化テスト (再起動シミュレーション)...")

try:
    del memory
    memory2 = Memory.from_config(config)
    all_memories2 = memory2.get_all(user_id="test_user")
    if hasattr(all_memories2, 'results'):
        items2 = all_memories2.results
    elif isinstance(all_memories2, dict) and 'results' in all_memories2:
        items2 = all_memories2['results']
    elif isinstance(all_memories2, list):
        items2 = all_memories2
    else:
        items2 = all_memories2
    print(f"  -> 再読み込み後の件数: {len(items2)}")
    if len(items2) > 0:
        print("  -> 永続化: OK (プロセス再起動後もデータが残存)")
    else:
        print("  -> 永続化: FAILED (データが消失)")
except Exception as e:
    print(f"  -> 永続化: FAILED - {type(e).__name__}: {e}")

# --- クリーンアップ ---
print("\n[Cleanup] テスト用DB削除...")
if os.path.exists(TEST_DB_PATH):
    shutil.rmtree(TEST_DB_PATH)
    print("  -> OK")

print("\n" + "=" * 60)
print("検証完了")
print("=" * 60)
