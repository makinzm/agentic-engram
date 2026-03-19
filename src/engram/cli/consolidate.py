#!/usr/bin/env python3
"""ae-consolidate: 類似メモリの統合・スキル化 CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def _make_cli_llm(cli_name: str, model: str = None):
    """CLI名に応じた llm_fn を返すファクトリ。"""
    cmd = {
        "claude-code": ["claude", "-p", "--output-format", "text", "--no-session-persistence"],
        "codex": ["codex", "exec", "--ephemeral"],
        "gemini": ["gemini"],
    }[cli_name]

    if model:
        if cli_name == "claude-code":
            cmd = cmd + ["--model", model]
        elif cli_name == "codex":
            cmd = cmd + ["-c", f"model={model}"]

    def llm_fn(messages: list) -> str:
        prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]

        env = dict(os.environ)
        if cli_name == "claude-code":
            env.pop("CLAUDECODE", None)

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{cli_name} exited {result.returncode}: {result.stderr[:200]}")
        return result.stdout

    return llm_fn


def main():
    parser = argparse.ArgumentParser(description="Consolidate similar memories")
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.engram/memory-db/vector_store"),
        help="Path to LanceDB database directory",
    )
    parser.add_argument(
        "--graph-path",
        default=None,
        help="Path to Kuzu graph database directory",
    )
    parser.add_argument(
        "--skills-dir",
        default=os.path.expanduser("~/.engram/skills"),
        help="Directory to write skill files",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="Cosine similarity threshold for clustering (default: 0.90)",
    )
    parser.add_argument(
        "--llm",
        choices=["claude-code", "codex", "gemini"],
        default=None,
        help="CLI tool to use as LLM backend",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use for LLM backend (e.g. sonnet, opus)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show clusters and LLM decisions without modifying DB",
    )
    args = parser.parse_args()

    from engram.consolidate import find_similar_clusters, process_cluster

    # 1. クラスタリング
    print(f"Scanning memories (threshold={args.threshold})...")
    clusters = find_similar_clusters(args.db_path, threshold=args.threshold)
    print(f"Found {len(clusters)} cluster(s) to process.")

    if not clusters:
        print("No similar memory clusters found.")
        return

    # ドライラン: クラスタのみ表示（LLMなし）
    if args.dry_run and args.llm is None:
        for i, cluster in enumerate(clusters, 1):
            total_count = sum(m.get("occurrence_count", 1) for m in cluster)
            print(f"\n--- Cluster {i} ({len(cluster)} memories, {total_count} occurrences) ---")
            for mem in cluster:
                count = mem.get("occurrence_count", 1)
                print(f"  [{mem.get('category', '?')}] (x{count}) {mem.get('event', '')[:100]}")
        return

    # LLM が必要
    if args.llm is None:
        print("ERROR: --llm is required for consolidation (or use --dry-run without --llm to preview clusters)")
        sys.exit(1)

    llm_fn = _make_cli_llm(args.llm, model=args.model)

    # 2. 各クラスタを処理
    stats = {"MERGE": 0, "KEEP": 0, "SKILL": 0, "ERROR": 0}
    for i, cluster in enumerate(clusters, 1):
        total_count = sum(m.get("occurrence_count", 1) for m in cluster)
        print(f"\nProcessing cluster {i}/{len(clusters)} ({len(cluster)} memories, {total_count} occurrences)...")

        result = process_cluster(
            cluster,
            llm_fn=llm_fn,
            db_path=args.db_path,
            graph_path=args.graph_path,
            skills_dir=args.skills_dir,
            dry_run=args.dry_run,
        )

        action = result.get("action", "ERROR")
        stats[action] = stats.get(action, 0) + 1

        if args.dry_run:
            print(f"  Decision: {action}")
            for ev in result.get("events", []):
                print(f"    - {ev}")
            if action == "SKILL":
                skill = result.get("decision", {}).get("skill", {})
                print(f"    Skill: {skill.get('name', '?')} - {skill.get('title', '?')}")
        else:
            print(f"  Result: {action}")
            if action in ("MERGE", "SKILL"):
                print(f"    Deleted {len(result.get('deleted_ids', []))} old memories")
                if action == "SKILL":
                    print(f"    Skill: {result.get('skill_name', '?')}")

    # サマリー
    print(f"\n=== Summary ===")
    for action, count in sorted(stats.items()):
        if count > 0:
            print(f"  {action}: {count}")


if __name__ == "__main__":
    main()
