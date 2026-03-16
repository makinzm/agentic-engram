# V3: 記憶の自動要約・統合（Memory Consolidation）

## 背景

ae-miner は異なるセッションから同じ教訓を独立に抽出するため、
DB に意味的に重複する記憶が蓄積される。

**現状の実データ（162件）:**

| 類似度帯 | ペア数 | 内容 |
|---------|--------|------|
| 0.97+ | 4 | ほぼ同一の記述違い。確実にマージ対象 |
| 0.95-0.97 | 11 | 同じ教訓の別セッション抽出。マージ対象 |
| 0.92-0.95 | 18 | 同じ問題の異なる視点。大半マージ対象 |
| 0.90-0.92 | 12 | マージ対象が多いが、判断が必要なものも混在 |
| 0.87-0.90 | 14 | 異なる教訓が混在。LLM判断が必須 |
| 0.85-0.87 | 6 | 別の教訓が大半。マージ不要なものが多い |

**結論:** デフォルト閾値は **0.90** が妥当。0.85は偽陽性が多い。

## 設計方針

人間の睡眠時記憶整理を模倣:
「似た体験を統合し、より洗練された教訓に昇華する。
繰り返し現れるパターンはスキルとして定着させる。」

## コア機能: `ae-consolidate`

### 1. クラスタリング（検出フェーズ）
- 全メモリのベクトルを取得し、コサイン類似度で類似ペアを検出
- 閾値（デフォルト 0.90）以上のペアを連結成分としてクラスタリング
- 各クラスタ = 統合候補グループ

### 2. 統合判断（LLMフェーズ）
各クラスタの全メモリをLLMに渡し、3つのアクションから判断:

| アクション | 条件 | 処理 |
|-----------|------|------|
| **MERGE** | 同じ教訓の別表現 | 統合メモリを1つ生成、元メモリを削除 |
| **KEEP** | 似ているが異なる教訓 | 何もしない |
| **SKILL** | 3回以上出現 + 再利用可能な手順やパターン | スキルファイル（.md）を生成 + メモリをマージ |

#### MERGE の詳細
- 最も詳細な context / core_lessons を保持・統合
- tags, related_files は和集合
- `occurrence_count` = 統合元の count の合計
- entities, relations も統合（グラフDBも更新）
- 統合元のメモリは DELETE

#### SKILL の詳細
繰り返し出現する教訓は「スキル」に昇格:
- スキル = 再利用可能な手順書（Markdown）
- 出力先: `~/.engram/skills/<skill-name>.md`
- 内容: 問題パターン、判断基準、具体的な対処手順
- メモリ側: MERGEと同様に統合し、`tags` に `skill:<name>` を追加

**スキル化の基準（過剰なスキル化を防ぐ）:**
- クラスタ内メモリの `occurrence_count` 合計 ≥ 3
  - 各メモリは `occurrence_count`（出現回数）を持つ（デフォルト 1）
  - MERGE 時: 統合元の count を合算（例: count=2 + count=1 → count=3）
  - これにより「2件ずつMERGEを繰り返して3に到達しない」問題を回避
- 「手順」「判断基準」「チェックリスト」として構造化できるもの
- 単なる事実の記録（「XはYの仕様」）はスキル化しない
- LLMが SKILL と判断しても、最終的にはユーザーがレビュー可能（`--dry-run`）

**スキル化のライフサイクル例:**
```
1回目: ESLint v10 の教訓A (count=1)
2回目: 別セッションで教訓B (count=1) → A+B を MERGE → C (count=2)
3回目: さらに教訓D (count=1) → C+D のクラスタ (合計count=3) → SKILL 候補
```

### 3. 実装の制約
- 統合はバッチ処理（`ae-consolidate` コマンド）
- ae-miner の定期実行とは独立（手動 or 低頻度スケジュール）
- ドライラン対応（`--dry-run` で統合候補とLLM判断を表示）
- 統合元IDをログに記録（トレーサビリティ）

## データフロー

```
ae-consolidate
  ├─ 1. LanceDB から全メモリのベクトルを取得
  ├─ 2. コサイン類似度でクラスタリング（閾値 ≥ 0.90）
  ├─ 3. 各クラスタをLLMに渡して統合判断
  │     ├─ MERGE → 統合メモリを INSERT、元メモリを DELETE
  │     ├─ SKILL → スキルファイル生成 + MERGE + タグ追加
  │     └─ KEEP  → なにもしない
  └─ 4. グラフDB同期（MERGE/SKILL時）
```

## LLM プロンプト設計

```
以下の類似メモリ群を確認し、統合方針を判断してください。

## メモリ群（{cluster_size}件）
{cluster_memories}

## 指示
- 同じ教訓・同じ問題の別表現 → MERGE（1つの統合メモリに集約）
- 似ているが異なる問題・異なる教訓 → KEEP（何もしない）
- 3件以上のクラスタで、再利用可能な手順・判断基準・チェックリストとして
  構造化できる教訓 → SKILL（スキルファイルを生成しつつメモリも統合）
  ※ 単なる事実の記録はSKILLにしないこと

## 出力形式 (JSON)
{
  "action": "MERGE" | "KEEP" | "SKILL",
  "merged_memory": { ... },     // MERGE/SKILL時
  "skill": {                    // SKILL時のみ
    "name": "kebab-case-name",
    "title": "スキルのタイトル",
    "content": "Markdown形式の手順書"
  }
}
```

## CLI インターフェース

```bash
# ドライラン: 統合候補とLLM判断を表示（DB変更なし）
python scripts/ae-consolidate.py --dry-run

# 実行: LLMで統合判断し、DBを更新
python scripts/ae-consolidate.py --llm claude-code

# 閾値調整（デフォルト: 0.90）
python scripts/ae-consolidate.py --llm claude-code --threshold 0.85

# モデル指定
python scripts/ae-consolidate.py --llm claude-code --model sonnet
```

## 新規ファイル

| File | Role |
|------|------|
| `src/engram/consolidate.py` | クラスタリング + 統合ロジック |
| `src/engram/prompts_consolidate.py` | 統合用LLMプロンプト構築 |
| `scripts/ae-consolidate.py` | CLI エントリポイント |
| `tests/test_consolidate.py` | テスト |

## 既存モジュールへの影響

- `db.py`: スキーマに `occurrence_count` (int, default=1) を追加。既存レコードはマイグレーション不要（クエリ時に未設定なら1として扱う）
- `save.py`: `save_memories()` で `occurrence_count` を保存可能に（オプショナル、デフォルト1）
- `graph.py`: `remove_from_graph()` + `sync_to_graph()` で同期。変更不要
- スキルファイルは `~/.engram/skills/` に独立保存
