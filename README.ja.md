[English](./README.md)

# Agentic Engram

**AIコーディングエージェントのための自律型ローカルメモリエコシステム -- 人間の記憶の仕組みにインスパイアされた設計。**

Agentic Engramは、AIコーディングエージェント（Claude Code、Codex CLIなど）のネイティブセッションログを読み取り、LLMで再利用可能なナレッジを抽出し、ローカルのベクトル+グラフDBに保存する。エージェントはセマンティック検索で過去の教訓を呼び出せる -- クラウド不要、Docker不要、常駐サーバー不要。

## コンセプト

```mermaid
flowchart LR
    A["AIコーディングエージェント\n(Claude Code, Codex等)"] -->|native JSONL logs| B["~/.claude/projects/"]
    B -->|diff via mtime + cursor| C["ae-miner\n(LLM extraction)"]
    C -->|JSON| D["ae-save\n(LanceDB + Kuzu)"]
    D --> E["memory-db/\nvector_store + graph_store"]
    E -->|hybrid search| F["ae-recall"]
    F -->|context| A
    E --> G["ae-console\n(Streamlit UI)"]
```

**ライフサイクル:**

1. **記録** -- AIコーディングエージェント（Claude Code等）は通常の動作の一部として構造化セッションログ（JSONL）を自動保存する。追加の記録設定は不要。
2. **採掘** -- `ae-miner`（cron）が`mtime`+行ポインタカーソルで変更ログを検出し、JSONLをパースして可読テキストに変換し、差分をLLMに送信。LLMがINSERT / UPDATE / SKIPを判定する。
3. **保存** -- `ae-save`が`sentence-transformers`でペイロードを埋め込みベクトル化し、LanceDBにupsertする。エンティティとリレーションはKuzuグラフDBに同期される。
4. **想起** -- `ae-recall`がハイブリッド検索（ベクトル類似度 + グラフトラバーサル）を実行。エージェントは未知のエラーに遭遇した際に自律的に呼び出す。
5. **管理** -- `ae-console`がStreamlitダッシュボードを提供し、メモリの閲覧・検索・削除やエンティティグラフの探索ができる。

## 機能

- 完全ローカル、ゼロオーバーヘッド -- エージェントのネイティブログを読み取り、外部APIやサーバー不要
- Filebeatスタイルのクラッシュ耐性 -- `mtime`+行ポインタのみで状態管理、ステータスフラグなし
- 決定論的ID（SHA-256）による冪等upsert
- ハイブリッド検索：ベクトル類似度（LanceDB + `paraphrase-multilingual-MiniLM-L12-v2`）+ グラフトラバーサル（Kuzu）
- カテゴリ・タグフィルタリング
- Claude Code・Codex CLI用ネイティブJSONLパーサー（他CLIツールへの拡張可能）
- TTLベースの古いログの自動アーカイブ（テキストソースモード）
- エンティティグラフ可視化付きStreamlit管理コンソール

## クイックスタート

### 要件

- Python 3.9+
- セッションログを保存するAIコーディングエージェント（例：Claude Code）

### インストール

```bash
pip install -e ".[dev]"
```

### メモリの手動保存

```bash
echo '[{"action":"INSERT","payload":{"event":"CORS error with Ollama","context":"Direct fetch from Next.js client","core_lessons":"Use Route Handler as proxy","category":"architecture","tags":["Next.js","CORS"],"related_files":["app/api/chat/route.ts"],"session_id":"session_001"}}]' \
  | python scripts/ae-save.py
```

### メモリの検索

```bash
python scripts/ae-recall.py --query "CORS error" --format markdown
python scripts/ae-recall.py --query "CORS error" --format json --limit 3
```

### マイナーの実行

```bash
python scripts/ae-miner.py --dry-run                # 対象ログファイルをプレビュー（LLM不要）
python scripts/ae-miner.py --llm claude-code         # Claude Code JSONLログをマイニング（デフォルト）
python scripts/ae-miner.py --source codex --llm claude-code  # Codex CLI JONLログをマイニング
python scripts/ae-miner.py --llm codex               # Codex CLIをLLMバックエンドとして使用
python scripts/ae-miner.py --llm gemini              # Gemini CLIをLLMバックエンドとして使用
python scripts/ae-miner.py --source text --llm claude-code  # レガシー：生テキストログをマイニング
```

### コンソールの起動

```bash
streamlit run scripts/ae-console.py
```

## アーキテクチャ

```
~/.engram/
  memory-db/
    vector_store/        LanceDBデータ（セマンティック検索）
    graph_store/         Kuzuデータ（エンティティグラフ）
  config/
    cursor.json          ログファイルごとの行ポインタ + mtime
```

| コンポーネント | ファイル | 役割 |
|-----------|------|------|
| `db` | `src/engram/db.py` | LanceDB接続、スキーマ、CRUD |
| `save` | `src/engram/save.py` | バリデーション、ID生成、upsertロジック、グラフ同期 |
| `recall` | `src/engram/recall.py` | ハイブリッド検索（ベクトル + グラフ）、出力フォーマット |
| `graph` | `src/engram/graph.py` | Kuzuグラフ DB: エンティティ/リレーションCRUD、トラバーサル |
| `miner` | `src/engram/miner.py` | ログスキャン、差分読み取り、LLMオーケストレーション |
| `parsers` | `src/engram/parsers/` | ネイティブログパーサー（Claude Code、Codex CLI） |
| `cursor` | `src/engram/cursor.py` | cursor.jsonのアトミックな状態管理 |
| `prompts` | `src/engram/prompts.py` | 抽出用LLMプロンプト構築 |
| `embedder` | `src/engram/embedder.py` | sentence-transformersのシングルトンラッパー |
| `console` | `src/engram/console.py` | Streamlit UIロジック（統計、閲覧、削除、グラフ） |

## CLIリファレンス

### ae-save

stdinからJSON配列を読み取り、バリデーション・埋め込み・LanceDBへのupsertを行う。

```
python scripts/ae-save.py [--db-path PATH] [--graph-path PATH]
```

### ae-recall

セマンティック類似度+グラフブーストでメモリを検索する。

```
python scripts/ae-recall.py --query "..." [--format json|markdown] [--limit N] [--category CAT]
                            [--graph-path PATH] [--no-graph]
```

### ae-miner

ネイティブセッションログをパースし、LLMでナレッジを抽出し、メモリDBに保存する。

```
python scripts/ae-miner.py --llm claude-code|codex|gemini
                           [--source claude-code|codex|text] [--log-dir DIR]
                           [--db-path PATH] [--cursor-path PATH] [--dry-run]
```

### ae-console

メモリとグラフ管理用のStreamlit Webダッシュボード。

```
streamlit run scripts/ae-console.py
```

## AIエージェントとの連携

### 自律的な想起

#### CLAUDE.mdにae-recallをスキルとして登録する

プロジェクトの`CLAUDE.md`（またはグローバルアクセス用に`~/.claude/CLAUDE.md`）に以下を追加する：

```markdown
## Memory Recall
When you encounter an unfamiliar error, unexpected behavior, or need to check
if a similar problem was solved before, run:
  python /path/to/agentic-engram/scripts/ae-recall.py --query "<describe the issue>" --format markdown --limit 3
Review the results before attempting a fix from scratch.
```

エージェントは未知のエラーに遭遇した際に自律的に`ae-recall`を呼び出し、ゼロから解決を試みる前に過去の教訓を取得する。

### マイナー -- AIコーディングエージェントCLIの利用

`ae-miner`はAIコーディングエージェントのネイティブセッションログ（JSONL）を読み取り、CLIツールをLLMバックエンドとして使用する。追加の記録設定やAPIキーは不要。

```bash
python scripts/ae-miner.py --llm claude-code   # ~/.claude/projects/を読み取り、`claude -p`を使用
python scripts/ae-miner.py --source codex --llm claude-code  # ~/.codex/sessions/を読み取り、`claude -p`を使用
python scripts/ae-miner.py --llm codex          # `codex exec`を使用
python scripts/ae-miner.py --llm gemini         # `gemini`を使用
```

#### PythonでカスタムLLMを渡す

CLIツールを使わずAPIを直接呼び出す場合は、`process_log()`にカスタム`llm_fn`コールバックを渡す：

```python
from engram.cursor import CursorManager
from engram.parsers.claude_code import ClaudeCodeParser
from engram.miner import process_log
import os

cm = CursorManager(os.path.expanduser("~/.engram/config/cursor.json"))
parser = ClaudeCodeParser()

from openai import OpenAI
client = OpenAI()

def llm_fn(messages: list[dict]) -> str:
    resp = client.chat.completions.create(model="gpt-4o", messages=messages, temperature=0.2)
    return resp.choices[0].message.content

for target in parser.scan(cm):
    process_log(target["filepath"], cm, llm_fn, db_path=os.path.expanduser("~/.engram/memory-db/vector_store"), parser=parser)
```

## 自動スケジューリング

> **macOS注意:** LLMバックエンド（例：`claude -p`）がmacOS Keychainで認証する場合、cronではなく**launchdを使用する必要がある**。cronジョブはユーザーログインセッション外で実行されるため、Keychainにアクセスできず認証エラーになる。LaunchAgentsはユーザーセッション内で実行されるため、Keychainに完全にアクセスできる。また、ログファイルへのリダイレクト時はPythonに`-u`フラグを付けてstdoutバッファリングを無効化すること。

### cron（Linux）

`ae-miner`を30分ごとに実行する：

```bash
crontab -e
```

```cron
*/30 * * * * cd /path/to/agentic-engram && .venv/bin/python scripts/ae-miner.py --llm claude-code >> ~/.engram/miner.log 2>&1
```

### launchd（macOS推奨）

`~/Library/LaunchAgents/com.engram.miner.plist`を作成する：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.engram.miner</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/agentic-engram/.venv/bin/python</string>
    <string>/path/to/agentic-engram/scripts/ae-miner.py</string>
    <string>--llm</string>
    <string>claude-code</string>
  </array>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>StandardOutPath</key>
  <string>/Users/YOU/.engram/miner.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/.engram/miner.log</string>
</dict>
</plist>
```

読み込む：

```bash
launchctl load ~/Library/LaunchAgents/com.engram.miner.plist
```

### systemd timer（Linux）

Linuxサーバーでは、`~/.config/systemd/user/`配下にsystemdのservice + timerペアを作成する。構造はlaunchdと同様 -- `ae-miner.py`を実行するserviceユニットと、`OnUnitActiveSec=30min`を設定したtimerユニット。`systemctl --user enable --now engram-miner.timer`で有効化する。

## 開発

```bash
pip install -e ".[dev]"
pytest -v
```

## ロードマップ

- ~~**V2: グラフDB拡張**~~ -- **完了。** [Kuzu](https://kuzudb.com/)統合によるGraphRAGスタイルのハイブリッド検索（ベクトル類似度 + グラフトラバーサル）。
- **V3: メモリ統合** -- 類似した記憶の自動重複排除・マージ。

## ライセンス

[Apache License 2.0](LICENSE)
