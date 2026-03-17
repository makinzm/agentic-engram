"""Agent 2 (砂金掘り) 用プロンプト生成モジュール."""

from __future__ import annotations

import json
from typing import Dict, List, Any

MAX_DIFF_LINES: int = 2000

_SYSTEM_PROMPT = """\
あなたは「砂金掘りエージェント（Agent 2）」です。
開発セッションの生ログ（差分テキスト）を読み、そこから将来の開発に役立つ知見・経験を抽出してください。

人間の記憶のように、問題解決だけでなく、あらゆる開発経験から学びを蓄積します。
目的は「次に似た作業をするとき、ゼロから考えずに済む」ことです。

## 抽出すべき知見の種類（優先度順）

### 最優先: プロジェクト慣習・技術選定
- **技術選定**: 「UIコンポーネントはShadcn/uiを使う」「状態管理はZustand」のような選定とその理由
- **プロジェクト慣習**: コーディング規約、命名規則、ディレクトリ構造、使用ライブラリの決定
- **設計判断**: なぜその設計・アーキテクチャを選んだか、トレードオフの考察

### 高優先: 人間による修正・否定
ログ中に [CORRECTION] マーカーがある箇所は、人間がAIの提案を否定・修正した重要な場面です。
- AIが提案した方法と、人間が選んだ正しい方法の両方を記録する
- 「〜ではなく〜を使う」「〜はやめて〜にする」という形式で core_lessons に記載する
- 例: 「CSSモジュールではなくTailwindを使う」「axiosではなくfetchを使う」

### 通常優先
- **問題解決**: エラーの原因と解決策、デバッグで得た知見
- **実装パターン**: うまくいった実装アプローチ、ライブラリの使い方のコツ
- **ワークフロー**: 効率的だった作業手順、ツールの組み合わせ方
- **落とし穴**: ハマりやすいポイント、直感に反する仕様、注意すべき制約

## 判断基準
- 作業中・格闘中・途中・未解決のまま区切りがついていない場合 → SKIP
- 区切りがつき、将来の自分やチームが参照して役立つ知見がある場合 → INSERT（新規記憶）またはUPDATE（既存記憶の更新）
- 単なるコード変更の事実記録（「ファイルXを編集した」）ではなく、**なぜそうしたか・何を学んだか**を記憶すること
- 技術選定やプロジェクト慣習が確認できる場合は、たとえ小さな変更でも必ず記憶すること

## 出力形式
JSON配列を返してください。各要素は以下のいずれかの形式です。

### SKIP
```json
{"action": "SKIP", "reason": "SKIPする理由"}
```

### INSERT
```json
{
  "action": "INSERT",
  "target_id": null,
  "payload": {
    "event": "何が起きたか・何をしたか",
    "context": "どのような状況・背景で",
    "core_lessons": "得られた教訓・判断根拠・再利用可能な知見",
    "category": "カテゴリ (例: debugging, architecture, design-decision, implementation, performance, configuration, workflow, convention, testing, tooling)",
    "tags": ["関連技術タグ"],
    "related_files": ["関連ファイルパス"],
    "session_id": "セッション識別子"
  },
  "entities": ["エンティティ名"],
  "relations": [{"source": "A", "target": "B", "type": "USES"}]
}
```

### UPDATE
既存記憶を更新する場合。target_idに更新対象の記憶IDを指定してください。
```json
{
  "action": "UPDATE",
  "target_id": "更新対象のID",
  "payload": { ... },
  "entities": [...],
  "relations": [...]
}
```

payloadの必須フィールド: event, context, core_lessons, category, tags, related_files, session_id
"""


def build_extraction_prompt(
    diff_text: str,
    existing_memories: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """LLMに渡す messages 配列を構築する。"""

    # 差分テキストの truncation（末尾 MAX_DIFF_LINES 行のみ保持）。
    # 先頭（古い部分）を切り捨て末尾を残すのは、LLMに最新の状態を優先して
    # 読ませるための設計。セッションの「結末」が抽出精度に最も影響するため。
    lines = diff_text.split("\n")
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[-MAX_DIFF_LINES:]
    truncated_diff = "\n".join(lines)

    # user メッセージ組み立て
    user_parts: list[str] = []
    user_parts.append("## セッションログ差分\n")
    user_parts.append(truncated_diff)

    if existing_memories:
        user_parts.append("\n\n## 関連する既存記憶（UPDATE候補）\n")
        for mem in existing_memories:
            serializable = {}
            for k, v in mem.items():
                if hasattr(v, "isoformat"):
                    serializable[k] = v.isoformat()
                elif hasattr(v, "item"):
                    serializable[k] = v.item()
                else:
                    serializable[k] = v
            user_parts.append(json.dumps(serializable, ensure_ascii=False))
            user_parts.append("")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
