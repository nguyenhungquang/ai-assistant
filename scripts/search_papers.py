#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from _common import (
    connect_db,
    db_has_paper_search_schema,
    search_paper_chunks,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search ingested paper chunks with SQLite FTS."
    )
    parser.add_argument("query", help="Keyword or phrase query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k = max(args.top_k, 0)
    if not args.query.strip() or top_k == 0:
        print(json.dumps({"query": args.query, "results": []}, indent=2))
        return

    try:
        conn = connect_db(read_only=True)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

    if not db_has_paper_search_schema(conn):
        conn.close()
        print(
            "Database exists but paper search schema is not initialized.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    results = search_paper_chunks(conn, query=args.query, top_k=top_k)
    conn.close()

    print(
        json.dumps(
            {
                "query": args.query,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
