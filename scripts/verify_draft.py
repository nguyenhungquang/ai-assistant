#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import (
    ROOT,
    connect_db,
    init_db,
    normalize_claim_text,
    rebuild_fts,
    retrieve_supporting_chunks,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a draft page against persisted claims and evidence."
    )
    parser.add_argument("page_path", help="Path to the markdown page to verify")
    return parser.parse_args()


def relative_page_path(page: Path) -> str | None:
    try:
        return str(page.relative_to(ROOT))
    except ValueError:
        return None


def section_content(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    if marker not in text:
        return ""
    after = text.split(marker, 1)[1]
    if "\n## " in after:
        return after.split("\n## ", 1)[0].strip()
    return after.strip()


def evaluate_claim(
    conn,
    *,
    claim_row,
    source_id: str | None,
) -> dict:
    normalized_claim_text = normalize_claim_text(claim_row["claim_text"])
    stored_rows = conn.execute(
        """
        SELECT ce.chunk_id, ce.span_start, ce.span_end, ch.section_path, ch.page_num
        FROM claim_evidence ce
        LEFT JOIN chunks ch ON ch.chunk_id = ce.chunk_id
        WHERE ce.claim_id = ? AND ce.support_type = 'supporting'
        ORDER BY ce.chunk_id
        """,
        (claim_row["claim_id"],),
    ).fetchall()
    stored_support = [dict(row) for row in stored_rows]
    retrieved_support = retrieve_supporting_chunks(
        conn,
        claim_text=normalized_claim_text,
        source_id=source_id,
        top_k=3,
    )
    stored_chunk_ids = {item["chunk_id"] for item in stored_support}
    retrieved_chunk_ids = {item["chunk_id"] for item in retrieved_support}
    overlap = stored_chunk_ids & retrieved_chunk_ids

    if not retrieved_support:
        status = "fail"
        issue = f"{claim_row['claim_type']} claim has no supporting chunks"
    elif overlap:
        status = "pass"
        issue = None
    else:
        status = "pass"
        issue = None

    return {
        "claim_id": claim_row["claim_id"],
        "claim_type": claim_row["claim_type"],
        "claim_text": normalized_claim_text,
        "original_claim_text": claim_row["claim_text"],
        "status": status,
        "stored_support": stored_support,
        "retrieved_support": retrieved_support,
        "issue": issue,
        "evidence_refreshed": bool(retrieved_support) and not overlap,
    }


def derive_page_verdict(*, structural_issues: bool, claim_results: list[dict]) -> str:
    if structural_issues:
        return "fail"
    if not claim_results:
        return "needs-review"
    if any(item["status"] == "fail" for item in claim_results):
        return "fail"
    if any(item["status"] == "needs-review" for item in claim_results):
        return "needs-review"
    return "pass"


def replace_claim_evidence(conn, *, claim_id: str, support_rows: list[dict]) -> None:
    conn.execute(
        "DELETE FROM claim_evidence WHERE claim_id = ? AND support_type = 'supporting'",
        (claim_id,),
    )
    for item in support_rows:
        conn.execute(
            """
            INSERT INTO claim_evidence (claim_id, chunk_id, support_type, span_start, span_end)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                item["chunk_id"],
                "supporting",
                item["char_start"],
                item["char_end"],
            ),
        )


def main() -> None:
    args = parse_args()
    page = Path(args.page_path).expanduser().resolve()
    if not page.exists():
        print(f"Page not found: {page}", file=sys.stderr)
        raise SystemExit(2)

    text = page.read_text()
    issues: list[str] = []
    big_picture = section_content(text, "Big Picture")
    evidence = section_content(text, "Evidence Map")
    contributions = section_content(text, "Main Contributions")
    main_results = section_content(text, "Main Results")

    if not text.lstrip().startswith("---"):
        issues.append("missing frontmatter")
    if "## Provenance" not in text:
        issues.append("missing provenance section")
    if not evidence:
        issues.append("missing evidence map section")
    if not big_picture or "TODO:" in big_picture:
        issues.append("missing usable big picture")
    if not contributions:
        issues.append("missing main contributions section")
    if not main_results:
        issues.append("missing main results section")

    structural_issues = any(
        issue in issues
        for issue in [
            "missing frontmatter",
            "missing provenance section",
            "missing evidence map section",
        ]
    )

    conn = connect_db()
    init_db(conn)
    rel_path = relative_page_path(page)
    page_row = None
    if rel_path is not None:
        page_row = conn.execute(
            "SELECT page_id, primary_source_id FROM pages WHERE path = ?",
            (rel_path,),
        ).fetchone()
    if page_row is None:
        conn.close()
        print("Page is not registered in SQLite state.", file=sys.stderr)
        raise SystemExit(2)

    claim_rows = conn.execute(
        """
        SELECT claim_id, claim_text, COALESCE(claim_type, '') AS claim_type
        FROM claims
        WHERE page_id = ?
        ORDER BY claim_id
        """,
        (page_row["page_id"],),
    ).fetchall()

    claim_results = [
        evaluate_claim(
            conn,
            claim_row=claim_row,
            source_id=page_row["primary_source_id"],
        )
        for claim_row in claim_rows
    ]
    if not claim_results:
        issues.append("no persisted claims to verify")

    for item in claim_results:
        if item["evidence_refreshed"]:
            replace_claim_evidence(
                conn,
                claim_id=item["claim_id"],
                support_rows=item["retrieved_support"],
            )
        conn.execute(
            "UPDATE claims SET claim_text = ?, verifier_status = ? WHERE claim_id = ?",
            (item["claim_text"], item["status"], item["claim_id"]),
        )
        if item["issue"] and item["issue"] not in issues:
            issues.append(item["issue"])

    conn.execute(
        "UPDATE pages SET updated_at = ? WHERE page_id = ?",
        (utc_now(), page_row["page_id"]),
    )
    rebuild_fts(conn)
    conn.commit()
    conn.close()

    verdict = derive_page_verdict(
        structural_issues=structural_issues,
        claim_results=claim_results,
    )
    page_output = rel_path or str(page)
    summary_claim = next(
        (
            item["claim_text"]
            for item in claim_results
            if item["claim_type"] in {"main_contribution", "main_result"}
        ),
        (big_picture.splitlines()[0].removeprefix("> ").strip() if big_picture else None),
    )
    supporting_spans = [
        support
        for item in claim_results[:3]
        for support in item["retrieved_support"][:1]
    ]

    print(
        json.dumps(
            {
                "page": page_output,
                "verdict": verdict,
                "issues": issues,
                "summary_claim": summary_claim,
                "persisted": {
                    "claim_count": len(claim_results),
                    "supporting_spans": supporting_spans,
                    "refreshed_claim_ids": [
                        item["claim_id"]
                        for item in claim_results
                        if item["evidence_refreshed"]
                    ],
                }
                if claim_results
                else None,
                "claim_results": claim_results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
