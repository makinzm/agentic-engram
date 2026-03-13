#!/usr/bin/env python3
"""ae-save: CLI entry point for saving memories via stdin JSON."""

import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Save memories to LanceDB")
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.engram/memory-db/vector_store"),
        help="Path to LanceDB database directory",
    )
    args = parser.parse_args()

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(payload, list):
        print("Error: Input must be a JSON array", file=sys.stderr)
        sys.exit(1)

    try:
        from engram.save import save_memories, SaveValidationError

        result = save_memories(payload, db_path=args.db_path)
        print(json.dumps(result, ensure_ascii=False))
    except SaveValidationError as e:
        print(f"Validation Error [{e.error_code}]: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
