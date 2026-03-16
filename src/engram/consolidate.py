"""Memory Consolidation: 類似メモリのクラスタリングと統合."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from engram.db import get_table, delete_records, insert_records, TABLE_NAME

logger = logging.getLogger(__name__)


def find_similar_clusters(
    db_path: str,
    threshold: float = 0.90,
) -> List[List[Dict]]:
    """全メモリからコサイン類似度でクラスタを検出する。

    Returns:
        各クラスタはメモリ辞書のリスト。サイズ2以上のクラスタのみ返す。
    """
    try:
        table = get_table(db_path)
    except Exception:
        return []

    df = table.to_pandas()
    if len(df) < 2:
        return []

    # ベクトル正規化
    vectors = np.array(df["vector"].tolist())
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normalized = vectors / norms

    # 類似ペアを検出
    n = len(normalized)
    adjacency: Dict[int, set] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(np.dot(normalized[i], normalized[j]))
            if sim >= threshold:
                adjacency[i].add(j)
                adjacency[j].add(i)

    # 連結成分でクラスタリング
    visited = set()
    clusters: List[List[int]] = []
    for node in range(n):
        if node in visited:
            continue
        if not adjacency[node]:
            continue
        # BFS
        component = []
        queue = [node]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    queue.append(neighbor)
        if len(component) >= 2:
            clusters.append(component)

    # インデックスをメモリ辞書に変換
    result = []
    columns = [c for c in df.columns if c != "vector"]
    for cluster_indices in clusters:
        cluster_memories = []
        for idx in cluster_indices:
            row = df.iloc[idx]
            mem = {}
            for col in columns:
                val = row[col]
                # pandas/pyarrow 型を Python ネイティブに変換
                if hasattr(val, "tolist"):
                    val = val.tolist()
                elif hasattr(val, "isoformat"):
                    val = val.isoformat()
                mem[col] = val
            # occurrence_count がない古いレコード対策
            if "occurrence_count" not in mem or mem["occurrence_count"] is None:
                mem["occurrence_count"] = 1
            cluster_memories.append(mem)
        result.append(cluster_memories)

    return result


def process_cluster(
    cluster: List[Dict],
    llm_fn: Callable,
    db_path: str,
    graph_path: Optional[str] = None,
    skills_dir: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """1つのクラスタを処理する。

    Returns:
        {"action": "MERGE"|"KEEP"|"SKILL", "cluster_size": int, ...}
    """
    from engram.prompts_consolidate import build_consolidation_prompt

    total_count = sum(m.get("occurrence_count", 1) for m in cluster)
    messages = build_consolidation_prompt(cluster, total_count)

    # LLM 呼び出し
    try:
        response = llm_fn(messages)
        decision = _parse_decision(response)
    except Exception as e:
        logger.error("LLM call or parse failed for cluster: %s", e)
        return {"action": "ERROR", "cluster_size": len(cluster), "error": str(e)}

    action = decision.get("action", "KEEP")

    if dry_run:
        events = [m.get("event", "")[:80] for m in cluster]
        return {
            "action": action,
            "cluster_size": len(cluster),
            "total_occurrence_count": total_count,
            "events": events,
            "decision": decision,
        }

    if action == "KEEP":
        return {"action": "KEEP", "cluster_size": len(cluster)}

    if action in ("MERGE", "SKILL"):
        merged = decision.get("merged_memory", {})
        if not merged:
            return {"action": "ERROR", "cluster_size": len(cluster), "error": "No merged_memory"}

        # 統合メモリの occurrence_count = 元メモリの合計
        merged["occurrence_count"] = total_count
        merged["session_id"] = f"consolidated_{cluster[0].get('id', 'unknown')[:16]}"

        # 元メモリを削除
        old_ids = [m["id"] for m in cluster if "id" in m]
        if old_ids:
            delete_records(old_ids, db_path)

            # グラフDBから削除
            if graph_path:
                try:
                    from engram.graph import remove_from_graph
                    for old_id in old_ids:
                        remove_from_graph(old_id, graph_path)
                except Exception as e:
                    logger.warning("Graph removal failed: %s", e)

        # SKILL タグを追加
        if action == "SKILL":
            skill_info = decision.get("skill", {})
            skill_name = skill_info.get("name", "unnamed-skill")
            tags = merged.get("tags", []) or []
            if f"skill:{skill_name}" not in tags:
                tags.append(f"skill:{skill_name}")
            merged["tags"] = tags

            # スキルファイル生成
            if skills_dir and skill_info.get("content"):
                _write_skill_file(skills_dir, skill_info)

        # 統合メモリを保存（save_memories のスキーマに合わせる）
        from engram.save import save_memories
        save_action = {
            "action": "INSERT",
            "target_id": None,
            "payload": {
                "event": merged.get("event", ""),
                "context": merged.get("context", ""),
                "core_lessons": merged.get("core_lessons", ""),
                "category": merged.get("category", ""),
                "tags": merged.get("tags", []),
                "related_files": merged.get("related_files", []),
                "session_id": merged.get("session_id", ""),
                "entities": merged.get("entities", []),
                "relations": merged.get("relations", []),
            },
        }
        try:
            save_memories([save_action], db_path=db_path, graph_path=graph_path)

            # occurrence_count を直接更新（save_memories はデフォルト1で保存するため）
            if total_count > 1:
                _update_occurrence_count(db_path, save_action["payload"], total_count)
        except Exception as e:
            logger.error("Failed to save consolidated memory: %s", e)
            return {"action": "ERROR", "cluster_size": len(cluster), "error": str(e)}

        result = {
            "action": action,
            "cluster_size": len(cluster),
            "total_occurrence_count": total_count,
            "deleted_ids": old_ids,
        }
        if action == "SKILL":
            result["skill_name"] = decision.get("skill", {}).get("name", "")
        return result

    return {"action": "KEEP", "cluster_size": len(cluster)}


def _parse_decision(response: str) -> Dict:
    """LLM レスポンスからJSON決定を抽出する。"""
    # JSON オブジェクトを抽出（{...} を探す）
    start = response.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth = 0
    for i in range(start, len(response)):
        if response[i] == "{":
            depth += 1
        elif response[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(response[start : i + 1])

    raise ValueError("Incomplete JSON object in response")


def _update_occurrence_count(db_path: str, payload: Dict, count: int) -> None:
    """保存直後のメモリの occurrence_count を更新する。"""
    try:
        from engram.save import generate_memory_id
        mem_id = generate_memory_id(payload.get("session_id", ""), payload.get("event", ""))
        table = get_table(db_path)
        # LanceDB の update は直接的な API がないため、
        # 該当レコードを読み取り → 削除 → 再挿入で更新
        results = table.search().where(f'id = "{mem_id}"').limit(1).to_arrow()
        if len(results) > 0:
            record = results.to_pydict()
            record["occurrence_count"] = [count]
            delete_records([mem_id], db_path)
            import pyarrow as pa
            table.add(pa.table(record))
    except Exception as e:
        logger.warning("Failed to update occurrence_count: %s", e)


def _write_skill_file(skills_dir: str, skill_info: Dict) -> None:
    """スキルファイルを Markdown で書き出す。"""
    os.makedirs(skills_dir, exist_ok=True)
    name = skill_info.get("name", "unnamed-skill")
    title = skill_info.get("title", name)
    content = skill_info.get("content", "")

    filepath = os.path.join(skills_dir, f"{name}.md")
    header = f"# {title}\n\n"

    with open(filepath, "w") as f:
        f.write(header + content)

    logger.info("Skill file written: %s", filepath)
