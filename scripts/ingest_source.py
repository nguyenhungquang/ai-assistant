#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from pypdf import PdfReader

from _drafter import DraftOutput, build_draft_packet, run_drafter
from _common import (
    RAW_EXTRACTED_DIR,
    RAW_HTML_DIR,
    RAW_PAPERS_DIR,
    ROOT,
    WIKI_INBOX_DIR,
    append_log,
    connect_db,
    ensure_workspace,
    ensure_index_entry,
    init_db,
    make_id,
    rebuild_fts,
    slugify,
    split_text_into_chunks,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a paper into the research vault from local PDF or arXiv source."
    )
    parser.add_argument(
        "source_input", help="Local PDF path, arXiv ID, arXiv URL, or ar5iv URL"
    )
    parser.add_argument("--title", help="Override detected title")
    parser.add_argument(
        "--canonical-locator",
        help="Canonical locator such as DOI, arXiv URL, or source URL",
    )
    parser.add_argument("--draft-output-file")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def exit_blocked(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def fetch_url_text(url: str, *, timeout: int = 30) -> str | None:
    request = Request(url, headers={"User-Agent": "paper-hub-agent/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError):
        return None


def fetch_url_bytes(url: str, *, timeout: int = 60) -> bytes | None:
    request = Request(url, headers={"User-Agent": "paper-hub-agent/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError):
        return None


def count_pdf_pages_from_bytes(pdf_bytes: bytes) -> int:
    cache_path = ROOT / "system" / "cache" / "_page_count_probe.pdf"
    cache_path.write_bytes(pdf_bytes)
    try:
        return len(PdfReader(str(cache_path)).pages)
    finally:
        cache_path.unlink(missing_ok=True)


def parse_arxiv_reference(source_input: str) -> dict | None:
    direct_match = re.fullmatch(
        r"(?P<id>\d{4}\.\d{4,5})(?P<version>v\d+)?", source_input
    )
    if direct_match:
        arxiv_id = direct_match.group(0)
    else:
        parsed = urlparse(source_input)
        host = parsed.netloc.lower()
        path = parsed.path
        if host not in {
            "arxiv.org",
            "www.arxiv.org",
            "ar5iv.labs.arxiv.org",
            "ar5iv.org",
        }:
            return None
        match = re.search(r"(?:abs|html|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)", path)
        if not match:
            return None
        arxiv_id = match.group("id")

    return {
        "arxiv_id": arxiv_id,
        "canonical_locator": f"arXiv:{arxiv_id}",
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "html_url": f"https://arxiv.org/html/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "ar5iv_url": f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    }


def extract_pdf(source_path: Path) -> tuple[str, int, list[tuple[int, int]]]:
    reader = PdfReader(str(source_path))
    page_texts: list[str] = []
    page_breaks: list[tuple[int, int]] = []
    total = 0
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            cleaned = clean_page_text(text)
            if not cleaned:
                continue
            page_texts.append(cleaned)
            total += len(cleaned) + 2
            page_breaks.append((idx, total))
    return "\n\n".join(page_texts).strip(), len(reader.pages), page_breaks


def validate_arxiv_html(html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    title = soup.select_one("h1.ltx_title_document")
    abstract = soup.select_one("div.ltx_abstract p")
    sections = soup.select("article section.ltx_section")
    body_paragraphs = soup.select("article section p.ltx_p")
    return bool(title and abstract and sections and body_paragraphs)


def clean_html_text(text: str) -> str:
    cleaned = unescape(text)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_arxiv_html(html_text: str) -> dict:
    soup = BeautifulSoup(html_text, "html.parser")
    title = clean_html_text(
        soup.select_one("h1.ltx_title_document").get_text(" ", strip=True)
    )

    author_block = soup.select_one(".ltx_authors")
    authors = (
        extract_author_names(clean_html_text(author_block.get_text(" ", strip=True)))
        if author_block is not None
        else []
    )

    abstract = ""
    abstract_node = soup.select_one("div.ltx_abstract p")
    if abstract_node is not None:
        abstract = clean_html_text(abstract_node.get_text(" ", strip=True))

    body_parts: list[str] = []
    if abstract:
        body_parts.append("Abstract")
        body_parts.append(abstract)

    for section in soup.select("article > section"):
        for node in section.find_all(["h2", "h3", "h4", "h5", "h6", "p"]):
            if node.name.startswith("h"):
                heading_text = clean_html_text(node.get_text(" ", strip=True))
                if heading_text:
                    body_parts.append(heading_text)
            elif "ltx_p" in (node.get("class") or []):
                para_text = clean_html_text(node.get_text(" ", strip=True))
                if para_text:
                    body_parts.append(para_text)

    extracted_text = "\n\n".join(body_parts).strip()
    year = None
    watermark = soup.select_one("#watermark-tr")
    if watermark is not None:
        year_match = re.search(r"\b(19|20)\d{2}\b", watermark.get_text(" ", strip=True))
        if year_match:
            year = year_match.group(0)

    page_breaks = [(1, len(extracted_text) + 1)] if extracted_text else []
    return {
        "title": title,
        "authors_or_creator": ", ".join(authors) if authors else None,
        "published_at": year,
        "extracted_text": extracted_text,
        "page_count": None,
        "page_breaks": page_breaks,
    }


def clean_page_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    normalized = re.sub(r"-\n(?=\w)", "", normalized)

    paragraphs: list[str] = []
    current_lines: list[str] = []
    for raw_line in normalized.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if current_lines:
                paragraphs.append(" ".join(current_lines).strip())
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(" ".join(current_lines).strip())

    cleaned = "\n\n".join(p for p in paragraphs if p)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def normalize_inline_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def detect_canonical_locator(text: str, provided: str | None) -> str | None:
    if provided:
        return provided

    doi_match = re.search(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", text, re.IGNORECASE)
    if doi_match:
        return doi_match.group(1).rstrip(".,;)")

    arxiv_match = re.search(
        r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", text, re.IGNORECASE
    )
    if arxiv_match:
        return f"arXiv:{arxiv_match.group(1)}"
    return None


def detect_published_at(text: str, metadata_created: str | None) -> str | None:
    year_match = re.search(r"\b(19|20)\d{2}\b", text[:4000])
    if year_match:
        return year_match.group(0)
    if metadata_created:
        year_match = re.search(r"(19|20)\d{2}", metadata_created)
        if year_match:
            return year_match.group(0)
    return None


def detect_authors(text: str, metadata_author: str | None) -> str | None:
    if normalize_inline_text(metadata_author):
        return normalize_inline_text(metadata_author)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for paragraph in paragraphs[1:4]:
        if len(paragraph) > 300:
            continue
        lower = paragraph.lower()
        if any(
            token in lower for token in ["abstract", "introduction", "doi", "arxiv"]
        ):
            continue
        if re.search(r"\b(and|,|·)\b", paragraph) or re.search(
            r"[A-Z][a-z]+\s+[A-Z][a-z]+", paragraph
        ):
            return paragraph[:300]
    return None


def detect_title(
    source_path: Path,
    extracted_text: str,
    override: str | None,
    metadata_title: str | None,
) -> str:
    if override:
        return override.strip()
    if normalize_inline_text(metadata_title):
        return normalize_inline_text(metadata_title)[:200]
    for line in extracted_text.splitlines():
        clean = line.strip()
        if len(clean) >= 10:
            return clean[:200]
    return (
        source_path.stem.replace("_", " ").replace("-", " ").strip() or "Untitled PDF"
    )


def extract_author_names(raw_text: str) -> list[str]:
    without_emails = re.sub(r"\S+@\S+", " ", raw_text)
    without_notes = re.sub(r"\b\d+\b", " ", without_emails)
    candidates = re.findall(
        r"[A-ZÀ-ÖØ-ÝŁ][\w.'’-]+(?:\s+[A-ZÀ-ÖØ-ÝŁ][\w.'’-]+){1,3}",
        without_notes,
    )
    banned_terms = {
        "google",
        "research",
        "brain",
        "university",
        "institute",
        "department",
        "school",
        "center",
        "centre",
        "work performed",
        "equal contribution",
    }
    authors: list[str] = []
    for candidate in candidates:
        normalized = clean_html_text(candidate)
        lowered = normalized.lower()
        if any(term in lowered for term in banned_terms):
            continue
        if normalized not in authors:
            authors.append(normalized)
    return authors


def extraction_quality(
    *, page_count: int, extracted_text: str, chunk_count: int
) -> tuple[str, list[str]]:
    notes = [
        f"Extracted characters: {len(extracted_text)}",
        f"Indexed chunks: {chunk_count}",
        f"Pages in canonical PDF: {page_count}",
    ]
    if not extracted_text.strip():
        return "low", notes + ["No extractable text detected."]
    avg_chars = len(extracted_text) / max(page_count, 1)
    if avg_chars < 150:
        return "low", notes + ["Very little text extracted per page."]
    if avg_chars < 600:
        return "medium", notes + ["Extraction is usable but likely incomplete."]
    return "high", notes + ["Extraction looks strong enough for draft retrieval."]


def detect_section_markers(text: str) -> list[tuple[int, str]]:
    markers: list[tuple[int, str]] = []
    pattern = re.compile(
        r"(^|\n\n)(abstract|introduction|background|method(?:s)?|approach|results?|discussion|conclusion)s?\b[:.-]?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        offset = match.start() + len(match.group(1))
        label = match.group(2).lower()
        markers.append((offset, label))
    markers.sort(key=lambda item: item[0])
    return markers


def build_page_markdown(
    *,
    title: str,
    source_id: str,
    version_id: str,
    raw_rel: str,
    extracted_rel: str,
    page_count: int,
    canonical_locator: str | None,
    authors_or_creator: str | None,
    published_at: str | None,
    source_kind: str,
    source_url: str | None,
    parsed_snapshot_rel: str,
    chunk_count: int,
    quality_label: str,
    quality_notes: list[str],
    draft: dict,
) -> str:
    locator_line = canonical_locator or "Unknown"
    authors_line = authors_or_creator or "Unknown"
    published_line = published_at or "Unknown"
    source_url_line = source_url or "Unknown"
    summary = draft["summary"]
    overview_block = summary["text"]
    quality_lines = "\n".join(f"- {note}" for note in quality_notes)
    summary_chunks = ", ".join(f"`{chunk_id}`" for chunk_id in summary["chunk_ids"])
    key_points = draft.get("key_points", [])
    limitations = draft.get("limitations", [])
    key_points_block = (
        "\n".join(
            f"- {item['text']} _(evidence: {', '.join(f'`{chunk_id}`' for chunk_id in item['chunk_ids'])})_"
            for item in key_points
        )
        if key_points
        else "- No key points extracted yet."
    )
    limitations_block = (
        "\n".join(
            f"- {item['text']} _(evidence: {', '.join(f'`{chunk_id}`' for chunk_id in item['chunk_ids'])})_"
            for item in limitations
        )
        if limitations
        else "- No limitations extracted yet."
    )
    return f"""---
title: {title}
page_type: paper
source_id: {source_id}
version_id: {version_id}
status: needs-review
verifier_status: pending
---

# {title}

## Source metadata

- Source ID: `{source_id}`
- Source Type: `paper`
- Version ID: `{version_id}`
- Authors / Creator: {authors_line}
- Published At: {published_line}
- Canonical Locator: {locator_line}
- Parsed Source Kind: `{source_kind}`
- Parsed Source URL: {source_url_line}
- Imported At: {utc_now()}
- Raw File: `{raw_rel}`
- Parsed Snapshot: `{parsed_snapshot_rel}`
- Extracted Text: `{extracted_rel}`
- Page Count: {page_count}
- Indexed Chunks: {chunk_count}

## Extraction quality

- Quality: `{quality_label}`
{quality_lines}

## Summary

> {overview_block}

- Summary evidence: {summary_chunks or "not available"}

## Key points

{key_points_block}

## Limitations

{limitations_block}

## Evidence

- Primary evidence lives in the extracted text file and chunk index.
- Use `uv run scripts/retrieve_evidence.py "<query>"` to inspect supporting spans.

## Notes

- This page was created by the initial ingest path and should remain in review until verified.
"""


def reserve_page_target(conn, title: str, source_id: str) -> Path:
    candidate = WIKI_INBOX_DIR / f"paper-{slugify(title)}.md"
    suffix = source_id[-8:]
    while (
        candidate.exists()
        or conn.execute(
            "SELECT 1 FROM pages WHERE path = ?",
            (str(candidate.relative_to(ROOT)),),
        ).fetchone()
        is not None
    ):
        candidate = WIKI_INBOX_DIR / f"paper-{slugify(title)}-{suffix}.md"
        suffix = suffix + "x"
    return candidate


def prepare_ingest(
    *,
    source_input: str,
    title_override: str | None = None,
    canonical_locator_override: str | None = None,
) -> dict:
    arxiv_ref = parse_arxiv_reference(source_input)
    source_path = Path(source_input).expanduser().resolve()

    source_kind = "pdf"
    source_url: str | None = None
    parsed_snapshot_rel: str | None = None
    html_snapshot_text: str | None = None
    pdf_bytes: bytes | None = None

    if arxiv_ref is not None:
        canonical_locator = arxiv_ref["canonical_locator"]
        ensure_workspace()
        conn = connect_db()
        init_db(conn)
        duplicate = conn.execute(
            "SELECT source_id FROM sources WHERE canonical_locator = ?",
            (canonical_locator,),
        ).fetchone()
        if duplicate is not None:
            conn.close()
            print(
                f"Duplicate source detected: {duplicate['source_id']}",
                file=sys.stderr,
            )
            raise SystemExit(2)

        official_html = fetch_url_text(arxiv_ref["html_url"])
        if official_html and validate_arxiv_html(official_html):
            source_kind = "arxiv_html"
            source_url = arxiv_ref["html_url"]
            html_snapshot_text = official_html
            html_data = extract_arxiv_html(official_html)
        else:
            fallback_html = fetch_url_text(arxiv_ref["ar5iv_url"])
            if fallback_html and validate_arxiv_html(fallback_html):
                source_kind = "ar5iv_html"
                source_url = arxiv_ref["ar5iv_url"]
                html_snapshot_text = fallback_html
                html_data = extract_arxiv_html(fallback_html)
            else:
                source_kind = "pdf"
                source_url = arxiv_ref["pdf_url"]
                html_data = None

        pdf_bytes = fetch_url_bytes(arxiv_ref["pdf_url"])
        if not pdf_bytes:
            conn.close()
            raise SystemExit("Failed to download canonical arXiv PDF.")
        canonical_pdf_page_count = count_pdf_pages_from_bytes(pdf_bytes)

        if html_data is None:
            temp_pdf = (
                ROOT / "system" / "cache" / f"{slugify(arxiv_ref['arxiv_id'])}.pdf"
            )
            temp_pdf.write_bytes(pdf_bytes)
            reader = PdfReader(str(temp_pdf))
            metadata = reader.metadata or {}
            extracted_text, page_count, page_breaks = extract_pdf(temp_pdf)
            metadata_title = getattr(metadata, "title", None)
            metadata_author = getattr(metadata, "author", None)
            metadata_created = getattr(metadata, "creation_date", None)
            title = detect_title(
                temp_pdf, extracted_text, title_override, metadata_title
            )
            authors_or_creator = detect_authors(extracted_text, metadata_author)
            published_at = detect_published_at(
                extracted_text, str(metadata_created) if metadata_created else None
            )
            temp_pdf.unlink(missing_ok=True)
        else:
            extracted_text = html_data["extracted_text"]
            page_count = canonical_pdf_page_count
            page_breaks = html_data["page_breaks"]
            title = title_override.strip() if title_override else html_data["title"]
            authors_or_creator = html_data["authors_or_creator"]
            published_at = html_data["published_at"]
        conn.close()
    else:
        if not source_path.exists():
            exit_blocked(f"PDF not found: {source_path}")
        if source_path.suffix.lower() != ".pdf":
            exit_blocked(
                "Supported inputs are local PDF paths or arXiv/ar5iv identifiers/URLs."
            )

        reader = PdfReader(str(source_path))
        metadata = reader.metadata or {}
        extracted_text, page_count, page_breaks = extract_pdf(source_path)
        metadata_title = getattr(metadata, "title", None)
        metadata_author = getattr(metadata, "author", None)
        metadata_created = getattr(metadata, "creation_date", None)

        title = detect_title(
            source_path, extracted_text, title_override, metadata_title
        )
        authors_or_creator = detect_authors(extracted_text, metadata_author)
        canonical_locator = detect_canonical_locator(
            extracted_text, canonical_locator_override
        )
        published_at = detect_published_at(
            extracted_text, str(metadata_created) if metadata_created else None
        )
        source_url = str(source_path)

    source_id = make_id("src", title)
    version_id = make_id("ver", title)
    page_id = make_id("page", title)

    ensure_workspace()
    conn = connect_db()
    init_db(conn)

    if canonical_locator:
        duplicate = conn.execute(
            "SELECT source_id FROM sources WHERE canonical_locator = ?",
            (canonical_locator,),
        ).fetchone()
        if duplicate is not None:
            conn.close()
            exit_blocked(f"Duplicate source detected: {duplicate['source_id']}")

    raw_target = RAW_PAPERS_DIR / f"{source_id}.pdf"
    html_target = RAW_HTML_DIR / f"{source_id}.html"
    extracted_target = RAW_EXTRACTED_DIR / f"{source_id}.txt"
    page_target = reserve_page_target(conn, title, source_id)

    if pdf_bytes is not None:
        raw_target.write_bytes(pdf_bytes)
    else:
        shutil.copy2(source_path, raw_target)
    if html_snapshot_text is not None:
        html_target.write_text(html_snapshot_text)
        parsed_snapshot_rel = str(html_target.relative_to(ROOT))
    else:
        parsed_snapshot_rel = str(raw_target.relative_to(ROOT))
    extracted_target.write_text(extracted_text + ("\n" if extracted_text else ""))

    section_markers = detect_section_markers(extracted_text)
    chunks = split_text_into_chunks(
        extracted_text, page_breaks, section_markers=section_markers
    )
    quality_label, quality_notes = extraction_quality(
        page_count=page_count,
        extracted_text=extracted_text,
        chunk_count=len(chunks),
    )
    draft_packet = build_draft_packet(
        source_id=source_id,
        title=title,
        source_kind=source_kind,
        authors_or_creator=authors_or_creator,
        published_at=published_at,
        canonical_locator=canonical_locator,
        quality_label=quality_label,
        quality_notes=quality_notes,
        chunks=chunks,
    )

    now = utc_now()
    conn.execute(
        """
        INSERT INTO sources (
            source_id, source_type, title, canonical_locator, authors_or_creator,
            published_at, source_kind, source_url, parsed_snapshot_path,
            raw_path, extracted_path, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            "paper",
            title,
            canonical_locator,
            authors_or_creator,
            published_at,
            source_kind,
            source_url,
            parsed_snapshot_rel,
            str(raw_target.relative_to(ROOT)),
            str(extracted_target.relative_to(ROOT)),
            "prepared",
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO source_versions (
            version_id, source_id, version_label, created_at, source_kind,
            source_url, parsed_snapshot_path, raw_path, extracted_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            source_id,
            "initial",
            now,
            source_kind,
            source_url,
            parsed_snapshot_rel,
            str(raw_target.relative_to(ROOT)),
            str(extracted_target.relative_to(ROOT)),
        ),
    )
    conn.execute(
        """
        INSERT INTO pages (page_id, page_type, title, path, status, primary_source_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            page_id,
            "paper",
            title,
            str(page_target.relative_to(ROOT)),
            "prepared",
            source_id,
            now,
        ),
    )

    conn.execute(
        "INSERT OR REPLACE INTO prepared_packets (source_id, version_id, page_id, packet_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            source_id,
            version_id,
            page_id,
            json.dumps(draft_packet, sort_keys=True),
            now,
        ),
    )

    for chunk in chunks:
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, source_id, version_id, section_path, chunk_text,
                char_start, char_end, page_num
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{source_id}_{chunk['chunk_id']}",
                source_id,
                version_id,
                chunk["section_path"],
                chunk["chunk_text"],
                chunk["char_start"],
                chunk["char_end"],
                chunk["page_num"],
            ),
        )

    rebuild_fts(conn)
    conn.commit()
    conn.close()

    return {
        "source_id": source_id,
        "version_id": version_id,
        "page_id": page_id,
        "title": title,
        "page_path": str(page_target.relative_to(ROOT)),
        "raw_path": str(raw_target.relative_to(ROOT)),
        "parsed_snapshot_path": parsed_snapshot_rel,
        "extracted_path": str(extracted_target.relative_to(ROOT)),
        "page_count": page_count,
        "canonical_locator": canonical_locator,
        "authors_or_creator": authors_or_creator,
        "published_at": published_at,
        "source_kind": source_kind,
        "source_url": source_url,
        "chunk_count": len(chunks),
        "quality_label": quality_label,
        "quality_notes": quality_notes,
        "draft_packet": draft_packet,
        "status": "prepared",
    }


def finalize_ingest(prepared: dict, draft_output: DraftOutput | None = None) -> dict:
    prepared = validate_prepared_ingest(prepared)
    draft = run_drafter(
        prepared["draft_packet"],
        draft_output=draft_output,
        mode="external" if draft_output is not None else "heuristic",
    )
    page_count = prepared["page_count"]
    chunk_count = prepared["chunk_count"]
    quality_label = prepared["quality_label"]
    quality_notes = prepared["quality_notes"]
    page_target = ROOT / prepared["page_path"]
    page_markdown = build_page_markdown(
        title=prepared["title"],
        source_id=prepared["source_id"],
        version_id=prepared["version_id"],
        raw_rel=prepared["raw_path"],
        extracted_rel=prepared["extracted_path"],
        page_count=page_count,
        canonical_locator=prepared["canonical_locator"],
        authors_or_creator=prepared["authors_or_creator"],
        published_at=prepared["published_at"],
        source_kind=prepared["source_kind"],
        source_url=prepared["source_url"],
        parsed_snapshot_rel=prepared["parsed_snapshot_path"],
        chunk_count=chunk_count,
        quality_label=quality_label,
        quality_notes=quality_notes,
        draft=draft,
    )
    page_target.write_text(page_markdown)

    conn = connect_db()
    init_db(conn)
    persist_draft_claims(
        conn,
        page_id=prepared["page_id"],
        draft=draft,
    )
    conn.execute(
        "UPDATE sources SET status = ? WHERE source_id = ?",
        ("needs-review", prepared["source_id"]),
    )
    conn.execute(
        "UPDATE pages SET status = ?, updated_at = ? WHERE page_id = ?",
        ("needs-review", utc_now(), prepared["page_id"]),
    )
    rebuild_fts(conn)
    conn.commit()
    conn.close()

    ensure_index_entry(page_target, prepared["title"])
    append_log(
        f"Ingested paper '{prepared['title']}' using {prepared['source_kind']} into inbox as {prepared['page_path']}"
    )
    return {
        "source_id": prepared["source_id"],
        "version_id": prepared["version_id"],
        "page_id": prepared["page_id"],
        "source_kind": prepared["source_kind"],
        "page_path": prepared["page_path"],
        "chunk_count": prepared["chunk_count"],
        "status": "needs-review",
        "draft": draft,
    }


def persist_draft_claims(conn, *, page_id: str, draft: DraftOutput) -> list[str]:
    conn.execute(
        "DELETE FROM claim_evidence WHERE claim_id IN (SELECT claim_id FROM claims WHERE page_id = ?)",
        (page_id,),
    )
    conn.execute("DELETE FROM claims WHERE page_id = ?", (page_id,))

    created: list[str] = []

    def insert_section(claim_type: str, text: str, chunk_ids: list[str]) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        evidence_rows = []
        for chunk_id in chunk_ids:
            chunk_row = conn.execute(
                "SELECT char_start, char_end FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            if chunk_row is None:
                continue
            evidence_rows.append(
                (chunk_id, chunk_row["char_start"], chunk_row["char_end"])
            )
        if not evidence_rows:
            return
        claim_id = make_id("claim", f"{claim_type}-{cleaned[:30]}")
        conn.execute(
            "INSERT INTO claims (claim_id, page_id, claim_text, claim_type, verifier_status) VALUES (?, ?, ?, ?, ?)",
            (claim_id, page_id, cleaned, claim_type, "draft"),
        )
        for chunk_id, char_start, char_end in evidence_rows:
            conn.execute(
                "INSERT INTO claim_evidence (claim_id, chunk_id, support_type, span_start, span_end) VALUES (?, ?, ?, ?, ?)",
                (
                    claim_id,
                    chunk_id,
                    "supporting",
                    char_start,
                    char_end,
                ),
            )
        created.append(claim_id)

    insert_section("summary", draft["summary"]["text"], draft["summary"]["chunk_ids"])
    for item in draft.get("key_points", []):
        insert_section("key_point", item["text"], item["chunk_ids"])
    for item in draft.get("limitations", []):
        insert_section("limitation", item["text"], item["chunk_ids"])
    return created


def main() -> None:
    args = parse_args()
    prepared = prepare_ingest(
        source_input=args.source_input,
        title_override=args.title,
        canonical_locator_override=args.canonical_locator,
    )
    draft_output = None
    if args.draft_output_file:
        draft_output = json.loads(Path(args.draft_output_file).read_text())
    payload = finalize_ingest(prepared, draft_output=draft_output)
    print(json.dumps(payload, indent=2))


def validate_prepared_ingest(prepared: dict[str, Any]) -> dict[str, Any]:
    required_fields = {
        "source_id",
        "version_id",
        "page_id",
        "title",
        "page_path",
        "raw_path",
        "parsed_snapshot_path",
        "extracted_path",
        "page_count",
        "source_kind",
        "chunk_count",
        "draft_packet",
        "status",
        "quality_label",
        "quality_notes",
    }
    missing = sorted(required_fields - prepared.keys())
    if missing:
        raise ValueError(f"prepared ingest missing fields: {missing}")
    if prepared["status"] != "prepared":
        raise ValueError("prepared ingest must be in 'prepared' status")

    for path_key in ["page_path", "raw_path", "parsed_snapshot_path", "extracted_path"]:
        path = (ROOT / prepared[path_key]).resolve(strict=False)
        try:
            path.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(
                f"prepared path escapes repository root: {path_key}"
            ) from exc

    packet = prepared["draft_packet"]
    if packet.get("source_id") != prepared["source_id"]:
        raise ValueError("prepared packet source_id does not match prepared state")

    conn = connect_db()
    init_db(conn)
    source_row = conn.execute(
        "SELECT source_id, title, canonical_locator, authors_or_creator, published_at, source_kind, source_url, parsed_snapshot_path, raw_path, extracted_path, status FROM sources WHERE source_id = ?",
        (prepared["source_id"],),
    ).fetchone()
    version_row = conn.execute(
        "SELECT version_id, source_id FROM source_versions WHERE version_id = ? AND source_id = ?",
        (prepared["version_id"], prepared["source_id"]),
    ).fetchone()
    packet_row = conn.execute(
        "SELECT packet_json FROM prepared_packets WHERE source_id = ? AND version_id = ? AND page_id = ?",
        (prepared["source_id"], prepared["version_id"], prepared["page_id"]),
    ).fetchone()
    page_row = conn.execute(
        "SELECT page_id, title, path, status, primary_source_id FROM pages WHERE page_id = ?",
        (prepared["page_id"],),
    ).fetchone()
    if (
        source_row is None
        or version_row is None
        or packet_row is None
        or page_row is None
    ):
        conn.close()
        raise ValueError("prepared ingest does not match persisted staging rows")
    if source_row["status"] != "prepared" or page_row["status"] != "prepared":
        conn.close()
        raise ValueError("prepared ingest is not in staged status")
    if page_row["path"] != prepared["page_path"]:
        conn.close()
        raise ValueError("prepared page path does not match persisted page row")
    if page_row["primary_source_id"] != prepared["source_id"]:
        conn.close()
        raise ValueError("prepared page does not belong to prepared source")
    source_field_map = {
        "title": "title",
        "canonical_locator": "canonical_locator",
        "authors_or_creator": "authors_or_creator",
        "published_at": "published_at",
        "source_kind": "source_kind",
        "source_url": "source_url",
        "parsed_snapshot_path": "parsed_snapshot_path",
        "raw_path": "raw_path",
        "extracted_path": "extracted_path",
    }
    for prepared_key, row_key in source_field_map.items():
        if prepared.get(prepared_key) != source_row[row_key]:
            conn.close()
            raise ValueError(
                f"prepared field {prepared_key} does not match persisted source state"
            )
    if prepared.get("title") != page_row["title"]:
        conn.close()
        raise ValueError("prepared title does not match persisted page state")
    if not isinstance(prepared.get("page_count"), int):
        conn.close()
        raise ValueError("prepared page_count must be an integer")
    if not isinstance(prepared.get("chunk_count"), int):
        conn.close()
        raise ValueError("prepared chunk_count must be an integer")
    if not isinstance(prepared.get("quality_label"), str):
        conn.close()
        raise ValueError("prepared quality_label must be a string")
    if not isinstance(prepared.get("quality_notes"), list) or any(
        not isinstance(item, str) for item in prepared.get("quality_notes", [])
    ):
        conn.close()
        raise ValueError("prepared quality_notes must be a list of strings")

    persisted_packet = json.loads(packet_row["packet_json"])
    if packet != persisted_packet:
        conn.close()
        raise ValueError("prepared packet does not match persisted staged packet")

    persisted_chunk_ids = {
        row["chunk_id"]: {
            "chunk_text": row["chunk_text"],
            "section_path": row["section_path"],
            "char_start": row["char_start"],
            "char_end": row["char_end"],
            "page_num": row["page_num"],
        }
        for row in conn.execute(
            "SELECT chunk_id, chunk_text, section_path, char_start, char_end, page_num FROM chunks WHERE source_id = ? AND version_id = ?",
            (prepared["source_id"], prepared["version_id"]),
        ).fetchall()
    }
    conn.close()
    packet_chunks = packet.get("chunks", [])
    for chunk in packet_chunks:
        persisted = persisted_chunk_ids[chunk["chunk_id"]]
        for field in [
            "chunk_text",
            "section_path",
            "char_start",
            "char_end",
            "page_num",
        ]:
            if chunk.get(field) != persisted[field]:
                raise ValueError(
                    f"prepared packet chunk content does not match persisted state for {chunk['chunk_id']}"
                )
    return prepared


if __name__ == "__main__":
    main()
