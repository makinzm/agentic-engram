#!/usr/bin/env python3
"""ae-groom: 長期記憶グルーミング CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def _make_cli_llm(cli_name: str, model: str = None):
    """CLI名に応じた llm_fn を返すファクトリ。ae-consolidate と同じパターン。"""
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
    parser = argparse.ArgumentParser(description="Groom long-term memories")
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.engram/memory-db/vector_store"),
        help="Path to LanceDB database directory",
    )
    parser.add_argument(
        "--graph-path",
        default=os.path.expanduser("~/.engram/memory-db/graph_store"),
        help="Path to Kuzu graph database directory",
    )
    parser.add_argument(
        "--llm",
        choices=["claude-code", "codex", "gemini"],
        default=None,
        help="CLI tool to use as LLM backend (required for entity re-extraction)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use for LLM backend (e.g. sonnet, opus)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Memories per LLM call for entity re-extraction (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying DB",
    )
    parser.add_argument(
        "--normalize-categories-only",
        action="store_true",
        help="Run Phase 1 (category normalization) only",
    )
    parser.add_argument(
        "--re-extract-only",
        action="store_true",
        help="Run Phase 2 (entity re-extraction) only",
    )
    parser.add_argument(
        "--rebuild-graph-only",
        action="store_true",
        help="Run Phase 3+4 (graph rebuild + orphan cleanup) only",
    )
    args = parser.parse_args()

    from engram.groom import (
        analyze_categories,
        normalize_categories,
        analyze_entities,
        re_extract_entities,
        rebuild_graph,
        cleanup_orphan_entities,
    )

    # フェーズ選択
    only_flags = [args.normalize_categories_only, args.re_extract_only, args.rebuild_graph_only]
    run_all = not any(only_flags)

    run_phase1 = run_all or args.normalize_categories_only
    run_phase2 = run_all or args.re_extract_only
    run_phase3 = run_all or args.rebuild_graph_only

    # Phase 2 (全フェーズ実行) には LLM が必要
    if run_phase2 and not args.dry_run and args.llm is None:
        print("ERROR: --llm is required for entity re-extraction (or use --dry-run to preview)")
        sys.exit(1)

    # LLM ファクトリ（Phase 1, 2 で共用）
    llm_fn = _make_cli_llm(args.llm, model=args.model) if args.llm else None

    # ── Phase 1: Category 正規化 ──
    if run_phase1:
        print("=== Phase 1: Category Normalization ===")
        analysis = analyze_categories(args.db_path)
        print(f"Total memories: {analysis['total']}")

        if analysis["to_rename"]:
            for old, info in analysis["to_rename"].items():
                print(f"  {old} -> {info['to']} ({info['count']} records)")
        else:
            print("  No categories to rename.")

        if analysis["unknown"]:
            for cat, cnt in analysis["unknown"].items():
                if llm_fn:
                    print(f"  [LLM] {cat} ({cnt} records) -> will classify via LLM")
                else:
                    print(f"  [UNKNOWN] {cat} ({cnt} records) -> use --llm to classify")

        if not args.dry_run and (analysis["to_rename"] or analysis["unknown"]):
            result = normalize_categories(args.db_path, llm_fn=llm_fn)
            print(f"  Renamed (fixed): {result['renamed']}, LLM classified: {result['llm_classified']}, Skipped: {result['skipped_unknown']}")
        print()

    # ── Phase 2: Entity/Relation 再抽出 ──
    if run_phase2:
        print("=== Phase 2: Entity/Relation Re-extraction ===")
        analysis = analyze_entities(args.db_path)
        print(f"Total memories: {analysis['total']}")
        print(f"Currently empty entities: {analysis['empty_entities']}")
        print(f"Will re-extract: {analysis['to_re_extract']} (all)")

        if not args.dry_run:
            def progress(processed, total):
                print(f"  Progress: {processed}/{total}", end="\r", flush=True)

            result = re_extract_entities(
                args.db_path,
                llm_fn=llm_fn,
                batch_size=args.batch_size,
                progress_fn=progress,
            )
            print(f"\n  Updated: {result['updated']}, Errors: {result['errors']}")
        print()

    # ── Phase 3: GraphDB 再構築 ──
    if run_phase3:
        print("=== Phase 3: GraphDB Rebuild ===")

        if args.dry_run:
            from engram.graph import get_graph_stats
            try:
                stats = get_graph_stats(args.graph_path)
                print(f"Current graph: {stats['memory_count']} memories, {stats['entity_count']} entities")
            except Exception:
                print("Current graph: not available")
            analysis = analyze_entities(args.db_path)
            print(f"Will rebuild from {analysis['total']} VectorDB records")
        else:
            def progress(processed, total):
                print(f"  Progress: {processed}/{total}", end="\r", flush=True)

            result = rebuild_graph(args.db_path, args.graph_path, progress_fn=progress)
            print(f"\n  Synced: {result['synced']}, Errors: {result['errors']}")
        print()

    # ── Phase 4: 孤立 Entity 掃除 ──
    if run_phase3:
        print("=== Phase 4: Orphan Entity Cleanup ===")

        if args.dry_run:
            print("  Will clean up orphan entities after rebuild")
        else:
            result = cleanup_orphan_entities(args.graph_path)
            print(f"  Deleted orphan entities: {result['deleted']}")
        print()

    print("=== Grooming complete ===")


if __name__ == "__main__":
    main()
