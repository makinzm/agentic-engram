#!/usr/bin/env python3
"""ae-harvest: WebからKaggle/ML Tipsを収集してRAGに投入する CLI エントリポイント."""

import argparse
import os
import subprocess
import sys

from engram.llm import LLM_CHOICES, make_cli_llm

SOURCE_CHOICES = ["rss", "awesome", "search", "kaggle", "all"]


def _read_urls_from_file(filepath: str) -> list:
    """ファイルからURL一覧を読み込む（1行1URL、#コメント・空行無視）。"""
    urls = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="Harvest Kaggle/ML tips from web articles into memory DB"
    )

    # URL指定（手動）
    parser.add_argument(
        "--urls",
        nargs="+",
        default=[],
        help="URLs to harvest tips from",
    )
    parser.add_argument(
        "--url-file",
        default=None,
        help="File containing URLs (one per line)",
    )

    # 自動ソース
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default=None,
        help="Auto-discover URLs from source: rss, awesome, search, kaggle, or all",
    )

    # DB/カーソル
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.engram/memory-db/vector_store"),
        help="Path to LanceDB database directory",
    )
    parser.add_argument(
        "--graph-path",
        default=os.path.expanduser("~/.engram/memory-db/graph_store"),
        help="Path to Kùzu graph database directory",
    )
    parser.add_argument(
        "--cursor-path",
        default=os.path.expanduser("~/.engram/config/harvest_cursor.json"),
        help="Path to harvest cursor.json",
    )

    # LLM
    parser.add_argument(
        "--llm",
        choices=LLM_CHOICES,
        default=None,
        help="CLI tool to use as LLM backend",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use for LLM backend",
    )

    # 制御
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of URLs to process per run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show URLs to process without actually harvesting",
    )
    args = parser.parse_args()

    # URL一覧の収集
    urls = list(args.urls)
    if args.url_file:
        urls.extend(_read_urls_from_file(args.url_file))

    # 自動ソースからURL発見
    if args.source:
        from engram.sources import discover_urls

        discover_limit = args.limit or 20
        print(f"Discovering URLs from source: {args.source} ...")
        try:
            discovered = discover_urls(args.source, limit=discover_limit)
            print(f"  Discovered {len(discovered)} URL(s) from {args.source}.")
            urls.extend(discovered)
        except Exception as e:
            print(f"  Warning: Source discovery failed: {e}", file=sys.stderr)

    if not urls:
        print(
            "Error: No URLs specified. Use --urls, --url-file, or --source.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 重複除去（順序維持）
    seen: set = set()
    unique_urls: list = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    urls = unique_urls

    try:
        from engram.cursor import CursorManager
        from engram.harvest import filter_new_urls, process_url

        cm = CursorManager(args.cursor_path)

        # 未処理URLのフィルタリング
        new_urls = filter_new_urls(urls, cm)

        if not new_urls:
            print("No new URLs to process (all already harvested).")
            return

        if args.limit is not None and len(new_urls) > args.limit:
            print(f"Found {len(new_urls)} new URL(s), processing first {args.limit}.")
            new_urls = new_urls[: args.limit]
        else:
            print(f"Found {len(new_urls)} new URL(s) to process.")

        if args.dry_run:
            for url in new_urls:
                print(f"  [DRY RUN] {url}")
            return

        if args.llm is None:
            print(
                "Error: --llm is required when not using --dry-run.\n"
                f"  Choices: {', '.join(LLM_CHOICES)}",
                file=sys.stderr,
            )
            sys.exit(1)

        llm_fn = make_cli_llm(args.llm, model=args.model)

        total_inserted = 0
        total_skipped = 0

        for url in new_urls:
            print(f"  Harvesting: {url} ...")
            try:
                result = process_url(
                    url,
                    cm,
                    llm_fn,
                    db_path=args.db_path,
                    graph_path=args.graph_path,
                )
                inserted = result.get("inserted", 0)
                skipped = result.get("skipped", 0)
                total_inserted += inserted
                total_skipped += skipped
                print(f"    → {inserted} tip(s) saved, {skipped} skipped")
            except subprocess.TimeoutExpired:
                print(
                    f"    Timeout: {args.llm} did not respond within 300s",
                    file=sys.stderr,
                )
            except RuntimeError as e:
                print(f"    Error: {e}", file=sys.stderr)

        print(f"\nDone. Total: {total_inserted} tip(s) saved, {total_skipped} skipped.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
