#!/usr/bin/env python3
"""ae-miner: 砂金掘りエンジン CLI エントリポイント.

cron等で定期実行し、short-term-memory/ の生ログから記憶を抽出する。
"""

import argparse
import os
import subprocess
import sys

LLM_CHOICES = ["claude-code", "codex", "gemini"]
SOURCE_CHOICES = ["text", "claude-code"]

_DEFAULT_LOG_DIRS = {
    "text": "~/.engram/short-term-memory",
    "claude-code": "~/.claude/projects",
}


def _extract_json_array(text: str) -> str:
    """LLMレスポンスからJSON配列部分を抽出する。

    CLIツールの出力にはmarkdownフェンスや説明文が含まれることがあるため、
    最初の [...] ブロックを探して返す。見つからなければ元テキストをそのまま返す。
    """
    start = text.find("[")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text


def _make_cli_llm(cli_name: str):
    """CLI名に応じた llm_fn を返すファクトリ。"""

    configs = {
        "claude-code": {
            "cmd": ["claude", "-p", "--output-format", "text"],
        },
        "codex": {
            "cmd": ["codex", "-q"],
        },
        "gemini": {
            "cmd": ["gemini"],
        },
    }
    config = configs[cli_name]

    def llm_fn(messages: list) -> str:
        prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]

        env = dict(os.environ)
        # Claude Code はネスト起動を禁止するため、環境変数を除去して回避
        if cli_name == "claude-code":
            env.pop("CLAUDECODE", None)

        result = subprocess.run(
            config["cmd"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{cli_name} exited with code {result.returncode}: "
                f"{result.stderr[:500]}"
            )
        return _extract_json_array(result.stdout)

    return llm_fn


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
        else:
            targets = scan_logs(log_dir, cm)

        if not targets:
            print("No log files to process.")
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
                llm_fn = _make_cli_llm(args.llm)

                for t in targets:
                    print(f"  Processing: {t['filename']} ...")
                    try:
                        process_log(
                            t["filepath"],
                            cm,
                            llm_fn,
                            db_path=args.db_path,
                            parser=session_parser,
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
