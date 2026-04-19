#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import ROOT, connect_db, init_db, make_id, rebuild_fts, utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a draft page with simple evidence-bound checks."
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


def normalize_summary(summary: str) -> str:
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    cleaned = " ".join(line.removeprefix("> ").removeprefix(">") for line in lines)
    return cleaned.strip()


def extract_summary_claim(summary: str) -> str | None:
    cleaned = normalize_summary(summary)
    if not cleaned or "TODO:" in cleaned:
        return None
    return cleaned


def persist_basic_claim(page: Path, claim_text: str, verdict: str) -> dict | None:
    conn = connect_db()
    init_db(conn)
    rel_path = relative_page_path(page)
    if rel_path is None:
        conn.close()
        return None
    page_row = conn.execute(
        "SELECT page_id, primary_source_id FROM pages WHERE path = ?",
        (rel_path,),
    ).fetchone()
    if page_row is None or page_row["primary_source_id"] is None:
        conn.close()
        return None

    page_id = page_row["page_id"]
    source_id = page_row["primary_source_id"]
    conn.execute(
        "DELETE FROM claim_evidence WHERE claim_id IN (SELECT claim_id FROM claims WHERE page_id = ?)",
        (page_id,),
    )
    conn.execute("DELETE FROM claims WHERE page_id = ?", (page_id,))

    evidence_chunk = conn.execute(
        """
        SELECT chunk_id, char_start, char_end, section_path, page_num
        FROM chunks
        WHERE source_id = ?
        ORDER BY CASE
            WHEN lower(COALESCE(section_path, '')) LIKE '%abstract%' THEN 0
            WHEN lower(COALESCE(section_path, '')) LIKE '%introduction%' THEN 1
            ELSE 2
        END, char_start
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()

    claim_id = make_id("claim", claim_text[:40])
    conn.execute(
        "INSERT INTO claims (claim_id, page_id, claim_text, claim_type, verifier_status) VALUES (?, ?, ?, ?, ?)",
        (claim_id, page_id, claim_text, "summary", verdict),
    )

    evidence_info = None
    if evidence_chunk is not None:
        conn.execute(
            "INSERT INTO claim_evidence (claim_id, chunk_id, support_type, span_start, span_end) VALUES (?, ?, ?, ?, ?)",
            (
                claim_id,
                evidence_chunk["chunk_id"],
                "supporting",
                evidence_chunk["char_start"],
                evidence_chunk["char_end"],
            ),
        )
        evidence_info = {
            "chunk_id": evidence_chunk["chunk_id"],
            "section_path": evidence_chunk["section_path"],
            "page_num": evidence_chunk["page_num"],
        }

    conn.execute(
        "UPDATE pages SET updated_at = ? WHERE page_id = ?",
        (utc_now(), page_id),
    )
    rebuild_fts(conn)
    conn.commit()
    conn.close()
    return {
        "claim_id": claim_id,
        "evidence": evidence_info,
    }


def clear_page_claims(page: Path) -> None:
    conn = connect_db()
    init_db(conn)
    rel_path = relative_page_path(page)
    if rel_path is None:
        conn.close()
        return
    page_row = conn.execute(
        "SELECT page_id FROM pages WHERE path = ?",
        (rel_path,),
    ).fetchone()
    if page_row is not None:
        page_id = page_row["page_id"]
        conn.execute(
            "DELETE FROM claim_evidence WHERE claim_id IN (SELECT claim_id FROM claims WHERE page_id = ?)",
            (page_id,),
        )
        conn.execute("DELETE FROM claims WHERE page_id = ?", (page_id,))
        conn.execute(
            "UPDATE pages SET updated_at = ? WHERE page_id = ?",
            (utc_now(), page_id),
        )
        rebuild_fts(conn)
        conn.commit()
    conn.close()


def main() -> None:
    args = parse_args()
    page = Path(args.page_path).expanduser().resolve()
    if not page.exists():
        print(f"Page not found: {page}", file=sys.stderr)
        raise SystemExit(2)

    text = page.read_text()
    issues: list[str] = []
    summary = section_content(text, "Summary")
    evidence = section_content(text, "Evidence")
    summary_claim = extract_summary_claim(summary)

    if not text.lstrip().startswith("---"):
        issues.append("missing frontmatter")
    if "## Source metadata" not in text:
        issues.append("missing source metadata section")
    if not evidence:
        issues.append("missing evidence section")

    structural_issues = any(
        issue in issues
        for issue in [
            "missing frontmatter",
            "missing source metadata section",
            "missing evidence section",
        ]
    )

    verdict = "fail" if structural_issues else "pass"
    if not summary_claim:
        issues.append("missing usable summary")
        if not structural_issues:
            verdict = "needs-review"
    if "TODO:" in summary:
        issues.append("summary still contains TODO placeholder")
        if not structural_issues:
            verdict = "needs-review"
    if issues and verdict == "pass":
        verdict = "fail"

    persisted = None
    if verdict in {"pass", "needs-review"} and summary_claim:
        persisted = persist_basic_claim(page, summary_claim, verdict)
    else:
        clear_page_claims(page)

    page_output = relative_page_path(page) or str(page)

    print(
        json.dumps(
            {
                "page": page_output,
                "verdict": verdict,
                "issues": issues,
                "summary_claim": summary_claim,
                "persisted": persisted,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
