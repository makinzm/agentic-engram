# ae-harvest タイムライン

## 2026-03-31

### 計画フェーズ
- Planエージェントで設計を完了
- `ae-harvest` コマンドを新設する方針に決定（ae-miner拡張ではなく独立コマンド）
- 既存インフラ（CursorManager, save_memories, LLM backend）を再利用
- trafilatura で Web 本文抽出

### 実装フェーズ1: コアパイプライン
- `engram/llm.py`: 共有LLMユーティリティ抽出（cli/miner.pyからリファクタ）
- `engram/prompts_harvest.py`: Kaggle/ML Tips抽出用プロンプト
- `engram/harvest.py`: コアロジック（fetch, LLM, save, cursor）
- `engram/cli/harvest.py`: CLIエントリポイント
- テスト20件全パス（RED→GREEN完了）
- 既存229テスト全パス、リグレッションなし

### 実装フェーズ2: 自動ソース（4種類）
- `engram/sources/rss.py`: ML系ブログRSSフィード（MachinelearningMastery, TDS, fast.ai等）
- `engram/sources/awesome.py`: GitHub Awesome Lists（kaggle-solutions, awesome-kaggle）
- `engram/sources/search.py`: DuckDuckGo Liteで検索（認証不要）
- `engram/sources/kaggle.py`: Kaggle API（notebooks/kernels、~/.kaggle/kaggle.json要）
- `engram/sources/__init__.py`: ソースレジストリ + `discover_urls()` + `--source all`
- CLIに`--source`オプション追加
- テスト39件全パス
