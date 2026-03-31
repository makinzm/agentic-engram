#!/usr/bin/env python3
"""ae-miner: 砂金掘りエンジン CLI エントリポイント.

cron等で定期実行し、short-term-memory/ の生ログから記憶を抽出する。
"""

import argparse
import os
import subprocess
import sys

from engram.llm import LLM_CHOICES, make_cli_llm

SOURCE_CHOICES = ["text", "claude-code", "codex"]

_DEFAULT_LOG_DIRS = {
    "text": "~/.engram/short-term-memory",
    "claude-code": "~/.claude/projects",
    "codex": "~/.codex/sessions",
}


# 後方互換のエイリアス
_extract_json_array = None  # removed: use engram.llm.extract_json_array
_make_cli_llm = make_cli_llm


def main():
    parser = argparse.ArgumentParser(description="Mine memories from session logs")
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="claude-code",
        help="Log source type (default: claude-code)",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory containing session log files (default depends on --source)",
    )
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
        default=os.path.expanduser("~/.engram/config/cursor.json"),
        help="Path to cursor.json",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help="Archive directory (default: <log-dir>/archive)",
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=7,
        help="Days before a stale log is archived",
    )
    parser.add_argument(
        "--llm",
        choices=LLM_CHOICES,
        default=None,
        help="CLI tool to use as LLM backend (claude-code, codex, gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use for LLM backend (e.g. sonnet, opus, gpt-4o)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of session files to process per run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually calling LLM",
    )
    args = parser.parse_args()

    # --log-dir のデフォルトは --source に依存
    log_dir = args.log_dir or os.path.expanduser(_DEFAULT_LOG_DIRS[args.source])
    archive_dir = args.archive_dir or os.path.join(log_dir, "archive")

    try:
        from engram.cursor import CursorManager
        from engram.miner import scan_logs, process_log, archive_stale_logs

        cm = CursorManager(args.cursor_path)

        # 1. スキャン（source に応じて分岐）
        session_parser = None
        if args.source == "claude-code":
            from engram.parsers.claude_code import ClaudeCodeParser
            session_parser = ClaudeCodeParser(base_dir=log_dir)
            targets = session_parser.scan(cm)
        elif args.source == "codex":
            from engram.parsers.codex import CodexParser
            session_parser = CodexParser(base_dir=log_dir)
            targets = session_parser.scan(cm)
        else:
            targets = scan_logs(log_dir, cm)

        if not targets:
            print("No log files to process.")
        else:
            if args.limit is not None and len(targets) > args.limit:
                print(f"Found {len(targets)} log file(s), processing first {args.limit}.")
                targets = targets[:args.limit]
            else:
                print(f"Found {len(targets)} log file(s) to process.")

            if args.dry_run:
                for t in targets:
                    print(f"  [DRY RUN] {t['filename']}")
            elif args.llm is None:
                print(
                    "Error: --llm is required when not using --dry-run.\n"
                    f"  Choices: {', '.join(LLM_CHOICES)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            else:
                llm_fn = _make_cli_llm(args.llm, model=args.model)

                for t in targets:
                    print(f"  Processing: {t['filename']} ...")
                    try:
                        process_log(
                            t["filepath"],
                            cm,
                            llm_fn,
                            db_path=args.db_path,
                            parser=session_parser,
                            graph_path=args.graph_path,
                        )
                    except subprocess.TimeoutExpired:
                        print(
                            f"    Timeout: {args.llm} did not respond within 300s",
                            file=sys.stderr,
                        )
                    except RuntimeError as e:
                        print(f"    Error: {e}", file=sys.stderr)

        # 2. アーカイブ（text source のみ。claude-code は Claude Code が管理）
        if args.source == "text":
            archive_stale_logs(log_dir, archive_dir, cm, ttl_days=args.ttl_days)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
