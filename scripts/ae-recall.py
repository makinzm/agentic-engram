#!/usr/bin/env python3
"""ae-recall: CLI entry point for searching memories."""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Search memories in LanceDB")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.engram/memory-db/vector_store"),
        help="Path to LanceDB database directory",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter by category",
    )
    parser.add_argument(
        "--graph-path",
        default=os.path.expanduser("~/.engram/memory-db/graph_store"),
        help="Path to Kuzu graph database directory",
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Disable graph search (vector-only)",
    )
    args = parser.parse_args()

    graph_path = None if args.no_graph else args.graph_path

    try:
        from engram.recall import search_memories, format_output

        results = search_memories(
            query=args.query,
            db_path=args.db_path,
            limit=args.limit,
            category=args.category,
            graph_path=graph_path,
        )
        output = format_output(results, fmt=args.format)
        print(output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
