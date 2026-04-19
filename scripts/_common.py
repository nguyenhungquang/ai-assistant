from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_PAPERS_DIR = ROOT / "raw" / "papers"
RAW_HTML_DIR = ROOT / "raw" / "html"
RAW_POSTS_DIR = ROOT / "raw" / "posts"
RAW_EXTRACTED_DIR = ROOT / "raw" / "extracted"
WIKI_PAPERS_DIR = ROOT / "wiki" / "papers"
WIKI_POSTS_DIR = ROOT / "wiki" / "posts"
WIKI_TOPICS_DIR = ROOT / "wiki" / "topics"
WIKI_ENTITIES_DIR = ROOT / "wiki" / "entities"
WIKI_SYNTHESES_DIR = ROOT / "wiki" / "syntheses"
WIKI_INBOX_DIR = ROOT / "wiki" / "inbox"
SYSTEM_DIR = ROOT / "system"
SYSTEM_LOGS_DIR = SYSTEM_DIR / "logs"
SYSTEM_CACHE_DIR = SYSTEM_DIR / "cache"
DB_PATH = SYSTEM_DIR / "state.db"
INDEX_PATH = ROOT / "index.md"
LOG_PATH = ROOT / "log.md"


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        title TEXT NOT NULL,
        canonical_locator TEXT,
        authors_or_creator TEXT,
        published_at TEXT,
        source_kind TEXT NOT NULL DEFAULT 'pdf',
        source_url TEXT,
        parsed_snapshot_path TEXT,
        raw_path TEXT NOT NULL,
        extracted_path TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_versions (
        version_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        version_label TEXT NOT NULL,
        created_at TEXT NOT NULL,
        source_kind TEXT NOT NULL DEFAULT 'pdf',
        source_url TEXT,
        parsed_snapshot_path TEXT,
        raw_path TEXT NOT NULL,
        extracted_path TEXT NOT NULL,
        FOREIGN KEY (source_id) REFERENCES sources(source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        page_id TEXT PRIMARY KEY,
        page_type TEXT NOT NULL,
        title TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        primary_source_id TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (primary_source_id) REFERENCES sources(source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        section_path TEXT,
        chunk_text TEXT NOT NULL,
        char_start INTEGER NOT NULL,
        char_end INTEGER NOT NULL,
        page_num INTEGER,
        FOREIGN KEY (source_id) REFERENCES sources(source_id),
        FOREIGN KEY (version_id) REFERENCES source_versions(version_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT PRIMARY KEY,
        page_id TEXT NOT NULL,
        claim_text TEXT NOT NULL,
        claim_type TEXT,
        verifier_status TEXT,
        FOREIGN KEY (page_id) REFERENCES pages(page_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claim_evidence (
        claim_id TEXT NOT NULL,
        chunk_id TEXT NOT NULL,
        support_type TEXT NOT NULL,
        span_start INTEGER,
        span_end INTEGER,
        PRIMARY KEY (claim_id, chunk_id, support_type),
        FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
        FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL,
        source_id TEXT,
        page_id TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY (source_id) REFERENCES sources(source_id),
        FOREIGN KEY (page_id) REFERENCES pages(page_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prepared_packets (
        source_id TEXT PRIMARY KEY,
        version_id TEXT NOT NULL,
        page_id TEXT NOT NULL,
        packet_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (source_id) REFERENCES sources(source_id),
        FOREIGN KEY (version_id) REFERENCES source_versions(version_id),
        FOREIGN KEY (page_id) REFERENCES pages(page_id)
    )
    """,
    "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(page_id UNINDEXED, title, body)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, section_path, chunk_text)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(claim_id UNINDEXED, page_id UNINDEXED, claim_type, claim_text)",
]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def ensure_workspace() -> None:
    for path in [
        RAW_PAPERS_DIR,
        RAW_HTML_DIR,
        RAW_POSTS_DIR,
        RAW_EXTRACTED_DIR,
        WIKI_PAPERS_DIR,
        WIKI_POSTS_DIR,
        WIKI_TOPICS_DIR,
        WIKI_ENTITIES_DIR,
        WIKI_SYNTHESES_DIR,
        WIKI_INBOX_DIR,
        SYSTEM_DIR,
        SYSTEM_LOGS_DIR,
        SYSTEM_CACHE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def connect_db(*, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"Database not found: {DB_PATH}")
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        ensure_workspace()
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_has_retrieval_schema(conn: sqlite3.Connection) -> bool:
    required = {
        "pages",
        "chunks",
        "claims",
        "claim_evidence",
        "pages_fts",
        "chunks_fts",
        "claims_fts",
    }
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    existing = {row["name"] for row in rows}
    return required.issubset(existing)


def init_db(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    ensure_column(conn, "sources", "source_kind", "TEXT NOT NULL DEFAULT 'pdf'")
    ensure_column(conn, "sources", "source_url", "TEXT")
    ensure_column(conn, "sources", "parsed_snapshot_path", "TEXT")
    ensure_column(conn, "source_versions", "source_kind", "TEXT NOT NULL DEFAULT 'pdf'")
    ensure_column(conn, "source_versions", "source_url", "TEXT")
    ensure_column(conn, "source_versions", "parsed_snapshot_path", "TEXT")
    conn.commit()


def ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, definition: str
) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM pages_fts")
    conn.execute("DELETE FROM chunks_fts")
    conn.execute("DELETE FROM claims_fts")

    page_rows = conn.execute("SELECT page_id, title, path FROM pages").fetchall()
    for row in page_rows:
        body = ""
        page_path = ROOT / row["path"]
        if page_path.exists():
            body = page_path.read_text()
        conn.execute(
            "INSERT INTO pages_fts(page_id, title, body) VALUES (?, ?, ?)",
            (row["page_id"], row["title"], body),
        )

    chunk_rows = conn.execute(
        "SELECT chunk_id, source_id, section_path, chunk_text FROM chunks"
    ).fetchall()
    for row in chunk_rows:
        conn.execute(
            "INSERT INTO chunks_fts(chunk_id, source_id, section_path, chunk_text) VALUES (?, ?, ?, ?)",
            (
                row["chunk_id"],
                row["source_id"],
                row["section_path"] or "",
                row["chunk_text"],
            ),
        )

    claim_rows = conn.execute(
        "SELECT claim_id, page_id, COALESCE(claim_type, ''), claim_text FROM claims"
    ).fetchall()
    for row in claim_rows:
        conn.execute(
            "INSERT INTO claims_fts(claim_id, page_id, claim_type, claim_text) VALUES (?, ?, ?, ?)",
            (row["claim_id"], row["page_id"], row[2], row["claim_text"]),
        )

    conn.commit()


def append_log(message: str) -> None:
    timestamp = utc_now()
    existing = LOG_PATH.read_text() if LOG_PATH.exists() else "# Activity Log\n"
    if not existing.endswith("\n"):
        existing += "\n"
    LOG_PATH.write_text(existing + f"- {timestamp} — {message}\n")


def ensure_index_entry(page_path: Path, title: str) -> None:
    existing = (
        INDEX_PATH.read_text()
        if INDEX_PATH.exists()
        else "# Vault Index\n\n## Pages\n\n"
    )
    rel_path = page_path.relative_to(ROOT).as_posix()
    entry = f"- [{title}]({rel_path})"
    existing = existing.replace("- No pages yet.\n", "")
    if entry not in existing:
        if not existing.endswith("\n"):
            existing += "\n"
        INDEX_PATH.write_text(existing + entry + "\n")


def rebuild_index(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT title, path FROM pages ORDER BY title COLLATE NOCASE"
    ).fetchall()
    content = "# Vault Index\n\n## Pages\n\n"
    if rows:
        content += (
            "\n".join(f"- [{row['title']}]({row['path']})" for row in rows) + "\n"
        )
    else:
        content += "- No pages yet.\n"
    INDEX_PATH.write_text(content)


def target_dir_for_page_type(page_type: str) -> Path:
    mapping = {
        "paper": WIKI_PAPERS_DIR,
        "post": WIKI_POSTS_DIR,
        "topic": WIKI_TOPICS_DIR,
        "entity": WIKI_ENTITIES_DIR,
        "synthesis": WIKI_SYNTHESES_DIR,
    }
    return mapping.get(page_type, WIKI_INBOX_DIR)


def parse_frontmatter_value(text: str, field: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    frontmatter = text[4:end]
    pattern = re.compile(rf"^{re.escape(field)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(frontmatter)
    return match.group(1).strip() if match else None


def replace_frontmatter_field(text: str, field: str, value: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    frontmatter = text[4:end]
    body = text[end + 5 :]
    pattern = re.compile(rf"^{re.escape(field)}:\s*.+$", re.MULTILINE)
    replacement = f"{field}: {value}"
    if pattern.search(frontmatter):
        frontmatter = pattern.sub(replacement, frontmatter)
    else:
        if frontmatter and not frontmatter.endswith("\n"):
            frontmatter += "\n"
        frontmatter += replacement
    return f"---\n{frontmatter}\n---\n{body}"


def make_id(prefix: str, label: str) -> str:
    return (
        f"{prefix}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{slugify(label)[:40]}"
    )


def split_text_into_chunks(
    text: str,
    page_breaks: list[tuple[int, int]],
    chunk_size: int = 1200,
    section_markers: list[tuple[int, str]] | None = None,
) -> list[dict]:
    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[dict] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    cursor = 0
    chunk_index = 0
    for paragraph in paragraphs:
        start = normalized.find(paragraph, cursor)
        if start == -1:
            start = cursor
        end = start + len(paragraph)
        cursor = end
        while start < end:
            slice_end = min(start + chunk_size, end)
            page_num = infer_page_num(start, page_breaks)
            section_label = infer_section_label(start, section_markers or [])
            chunks.append(
                {
                    "chunk_id": f"chunk_{chunk_index:05d}",
                    "section_path": section_label
                    or (f"page:{page_num}" if page_num is not None else None),
                    "chunk_text": normalized[start:slice_end],
                    "char_start": start,
                    "char_end": slice_end,
                    "page_num": page_num,
                }
            )
            chunk_index += 1
            start = slice_end
    return chunks


def infer_page_num(offset: int, page_breaks: list[tuple[int, int]]) -> int | None:
    for page_num, end_offset in page_breaks:
        if offset < end_offset:
            return page_num
    return page_breaks[-1][0] if page_breaks else None


def infer_section_label(
    offset: int, section_markers: list[tuple[int, str]]
) -> str | None:
    current: str | None = None
    for marker_offset, label in section_markers:
        if marker_offset > offset:
            break
        current = label
    return current
