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
    slugify,
    target_dir_for_page_type,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote a verified inbox page into the main wiki."
    )
    parser.add_argument("page_path", help="Path to the inbox markdown page to publish")
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
    if ROOT / "wiki" / "inbox" not in [page_path.parent, *page_path.parents]:
        print("Only inbox pages can be published.", file=sys.stderr)
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
    target_dir = target_dir_for_page_type(page_type)
    if target_dir.name == "inbox":
        print(
            f"Unsupported publish target for page_type={page_type!r}", file=sys.stderr
        )
        raise SystemExit(2)

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

    target_name = page_path.name
    if page_path.name.startswith(f"{page_type}-"):
        target_name = page_path.name[len(page_type) + 1 :]
    target_path = target_dir / target_name
    if target_path.exists() and target_path != page_path:
        target_path = (
            target_dir / f"{slugify(target_path.stem)}-{page_path.stem[-8:]}.md"
        )

    updated = replace_frontmatter_field(text, "status", "published")
    updated = replace_frontmatter_field(updated, "verifier_status", "pass")
    rel_new = str(target_path.relative_to(ROOT))

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

    target_path.write_text(updated)
    if target_path != page_path:
        page_path.unlink()

    append_log(f"Published page '{target_path.stem}' to {rel_new}")
    print(
        json.dumps({"published_page": rel_new, "verification": verification}, indent=2)
    )


if __name__ == "__main__":
    main()
