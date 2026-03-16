"""Memory Consolidation 用 LLM プロンプト構築."""

from __future__ import annotations

import json
from typing import Dict, List


def build_consolidation_prompt(
    cluster_memories: List[Dict],
    total_occurrence_count: int,
) -> List[Dict]:
    """類似メモリクラスタの統合判断を求めるプロンプトを構築する。

    Args:
        cluster_memories: 各メモリの辞書リスト
        total_occurrence_count: クラスタ内メモリの occurrence_count 合計

    Returns:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
    """
    system_content = (
        "あなたは開発知見の記憶を整理する専門家です。"
        "類似する記憶群を分析し、統合方針を判断してください。"
    )

    # メモリ群のフォーマット
    memories_text = _format_cluster_memories(cluster_memories)

    # アクション選択肢の構築
    actions_text = _build_actions_text(total_occurrence_count)

    # 出力形式
    output_format = _build_output_format(total_occurrence_count)

    user_content = f"""以下の類似メモリ群（{len(cluster_memories)}件、累計出現{total_occurrence_count}回）を確認し、統合方針を判断してください。

## メモリ群
{memories_text}

## 判断基準
{actions_text}

## 出力形式
以下のJSON形式で**1つのJSONオブジェクト**を返してください（配列ではありません）。
{output_format}"""

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _format_cluster_memories(memories: List[Dict]) -> str:
    """クラスタ内のメモリを可読テキストにフォーマットする。"""
    parts: List[str] = []
    for i, mem in enumerate(memories, 1):
        count = mem.get("occurrence_count", 1)
        tags = ", ".join(mem.get("tags", []) or [])
        files = ", ".join(mem.get("related_files", []) or [])
        parts.append(
            f"### メモリ {i} (出現{count}回)\n"
            f"- **event**: {mem.get('event', '')}\n"
            f"- **context**: {mem.get('context', '')}\n"
            f"- **core_lessons**: {mem.get('core_lessons', '')}\n"
            f"- **category**: {mem.get('category', '')}\n"
            f"- **tags**: {tags}\n"
            f"- **related_files**: {files}"
        )
    return "\n\n".join(parts)


def _build_actions_text(total_occurrence_count: int) -> str:
    """利用可能なアクションの説明テキストを構築する。"""
    lines = [
        "- **MERGE**: 同じ教訓・同じ問題の別表現である場合。"
        "最も包括的な統合メモリを1つ生成する。"
        "context と core_lessons は最も詳細な内容を保持・統合し、"
        "tags と related_files は和集合とする。",
        "- **KEEP**: 似ているが異なる問題・異なる教訓である場合。何もしない。",
    ]
    if total_occurrence_count >= 3:
        lines.append(
            "- **SKILL**: 再利用可能な手順・判断基準・チェックリストとして"
            "構造化できる教訓の場合。スキルファイル（Markdown手順書）を生成し、"
            "メモリも統合する。単なる事実の記録（「XはYの仕様」）はSKILLにしないこと。"
        )
    return "\n".join(lines)


def _build_output_format(total_occurrence_count: int) -> str:
    """出力形式のJSON例を構築する。"""
    merge_example = {
        "action": "MERGE",
        "merged_memory": {
            "event": "統合された教訓の要約",
            "context": "最も詳細な文脈を保持・統合",
            "core_lessons": "すべてのメモリから得られた教訓を統合",
            "category": "適切なカテゴリ",
            "tags": ["tag1", "tag2"],
            "related_files": ["file1.ts", "file2.ts"],
            "entities": ["Entity1", "Entity2"],
            "relations": [{"source": "Entity1", "target": "Entity2", "type": "USES"}],
        },
    }

    keep_example = {"action": "KEEP"}

    parts = [
        "MERGE の場合:",
        f"```json\n{json.dumps(merge_example, ensure_ascii=False, indent=2)}\n```",
        "",
        "KEEP の場合:",
        f"```json\n{json.dumps(keep_example, ensure_ascii=False, indent=2)}\n```",
    ]

    if total_occurrence_count >= 3:
        skill_example = {
            "action": "SKILL",
            "merged_memory": {"event": "...", "context": "...", "core_lessons": "...", "category": "...", "tags": ["..."], "related_files": ["..."], "entities": ["..."], "relations": []},
            "skill": {
                "name": "kebab-case-name",
                "title": "スキルの日本語タイトル",
                "content": "## 概要\n...\n\n## 判断基準\n...\n\n## 手順\n1. ...\n2. ...",
            },
        }
        parts.extend([
            "",
            "SKILL の場合:",
            f"```json\n{json.dumps(skill_example, ensure_ascii=False, indent=2)}\n```",
        ])

    return "\n".join(parts)
