#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _common import (
    ROOT,
    append_log,
    connect_db,
    init_db,
    parse_frontmatter_value,
    rebuild_fts,
    rebuild_index,
    replace_frontmatter_field,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark a verified wiki page as published."
    )
    parser.add_argument("page_path", help="Path to the markdown page to publish")
    return parser.parse_args()


def run_verifier(page_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_draft.py"), str(page_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    args = parse_args()
    page_path = Path(args.page_path).expanduser().resolve()
    if not page_path.exists():
        print(f"Page not found: {page_path}", file=sys.stderr)
        raise SystemExit(2)

    verification = run_verifier(page_path)
    if verification["verdict"] != "pass":
        print(
            f"Page is not publishable. Verdict={verification['verdict']} issues={verification['issues']}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    text = page_path.read_text()
    page_type = parse_frontmatter_value(text, "page_type") or "paper"
    rel_old = str(page_path.relative_to(ROOT))

    conn = connect_db()
    init_db(conn)
    now = utc_now()
    page_row = conn.execute(
        "SELECT page_id FROM pages WHERE path = ?", (rel_old,)
    ).fetchone()
    if page_row is None:
        conn.close()
        print(f"No page record found for {rel_old}", file=sys.stderr)
        raise SystemExit(2)

    updated = replace_frontmatter_field(text, "status", "published")
    updated = replace_frontmatter_field(updated, "verifier_status", "pass")
    updated = updated.replace("- Status: `needs-review`", "- Status: `published`")
    rel_new = rel_old

    conn.execute(
        "UPDATE pages SET path = ?, status = ?, updated_at = ? WHERE page_id = ?",
        (rel_new, "published", now, page_row["page_id"]),
    )
    conn.execute(
        "UPDATE claims SET verifier_status = ? WHERE page_id = ?",
        ("pass", page_row["page_id"]),
    )
    rebuild_fts(conn)
    rebuild_index(conn)
    conn.commit()
    conn.close()

    page_path.write_text(updated)

    append_log(f"Published page '{page_path.stem}' at {rel_new}")
    print(
        json.dumps({"published_page": rel_new, "verification": verification}, indent=2)
    )


if __name__ == "__main__":
    main()
