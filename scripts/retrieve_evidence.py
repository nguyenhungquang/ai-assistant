#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from _common import (
    connect_db,
    db_has_retrieval_schema,
    retrieve_supporting_chunks,
    safe_match_query,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrieve evidence from indexed pages and chunks."
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    if not args.query.strip():
        print(
            json.dumps(
                {
                    "query": args.query,
                    "pages": [],
                    "chunks": [],
                },
                indent=2,
            )
        )
        return
    try:
        conn = connect_db(read_only=True)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    if not db_has_retrieval_schema(conn):
        conn.close()
        print(
            "Database exists but retrieval schema is not initialized.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    match_query = safe_match_query(args.query)

    pages = conn.execute(
        """
        SELECT page_id, title, rank
        FROM (
            SELECT page_id, title, bm25(pages_fts) AS rank
            FROM pages_fts
            WHERE pages_fts MATCH ?
        )
        ORDER BY rank
        LIMIT ?
        """,
        (match_query, args.top_k),
    ).fetchall()
    claim_rows = conn.execute(
        """
        SELECT base.claim_id, base.claim_text, base.claim_type, base.verifier_status, base.page_title, base.page_path,
               ce.chunk_id AS evidence_chunk_id, ch.section_path AS evidence_section_path, base.rank
        FROM (
            SELECT c.claim_id, c.claim_text, c.claim_type, c.verifier_status, p.title AS page_title, p.path AS page_path, f.rank
            FROM claims_fts
            JOIN (
                SELECT claim_id, bm25(claims_fts) AS rank
                FROM claims_fts
                WHERE claims_fts MATCH ?
            ) AS f ON f.claim_id = claims_fts.claim_id
            JOIN claims c ON c.claim_id = f.claim_id
            LEFT JOIN pages p ON p.page_id = c.page_id
            ORDER BY f.rank
            LIMIT ?
        ) AS base
        LEFT JOIN claim_evidence ce ON ce.claim_id = base.claim_id AND ce.support_type = 'supporting'
        LEFT JOIN chunks ch ON ch.chunk_id = ce.chunk_id
        GROUP BY base.claim_id
        ORDER BY base.rank
        """,
        (match_query, args.top_k),
    ).fetchall()
    supporting_chunks = retrieve_supporting_chunks(
        conn,
        claim_text=args.query,
        top_k=args.top_k,
    )
    chunk_rows = []
    for item in supporting_chunks:
        page_row = conn.execute(
            "SELECT title, path FROM pages WHERE primary_source_id = ?",
            (item["source_id"],),
        ).fetchone()
        chunk_rows.append(
            {
                **item,
                "rank": item["fts_rank"],
                "adjusted_rank": item["final_rank"],
                "page_title": page_row["title"] if page_row else None,
                "page_path": page_row["path"] if page_row else None,
            }
        )
    conn.close()

    result = {
        "query": args.query,
        "pages": [dict(row) for row in pages],
        "claims": [dict(row) for row in claim_rows],
        "chunks": chunk_rows,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
