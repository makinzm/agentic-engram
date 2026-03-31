# ae-harvest: Web→RAG パイプライン

## 概要
Webから Kaggle/ML Tips を自動収集し、既存の agentic-engram RAG システムに投入する `ae-harvest` CLI コマンドを新設する。

## 要件
- URLリスト or 定義済みソースからWeb記事を取得
- trafilatura で本文抽出
- LLM でTips を構造化データとして抽出
- 既存の `save_memories()` 経由で LanceDB + Kuzu に保存
- CursorManager でURL処理状態を管理（重複取得を防止）
- セマンティック重複チェック（既存の ae-recall を利用）

## ステップ
1. [x] ブランチ作成・タスク定義
2. [x] 共有LLMユーティリティの抽出 (`engram/llm.py`)
3. [x] harvest用プロンプト作成 (`engram/prompts_harvest.py`)
4. [x] Web取得・本文抽出 (`engram/harvest.py` 内に `fetch_web_content`)
5. [x] harvestコアロジック (`engram/harvest.py`)
6. [x] CLI エントリポイント (`engram/cli/harvest.py`)
7. [x] pyproject.toml にエントリポイント + 依存追加
8. [x] テスト作成・実行 (20件全パス、既存229件リグレッションなし)
9. [x] README.md 更新
