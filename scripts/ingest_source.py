from __future__ import annotations

import json
import os
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from _drafter import DraftOutput, build_draft_packet, run_drafter
from _common import (
    RAW_ASSETS_DIR,
    RAW_EXTRACTED_DIR,
    RAW_HTML_DIR,
    ROOT,
    SYSTEM_CACHE_DIR,
    agent_edit_policy,
    append_log,
    connect_db,
    ensure_workspace,
    ensure_index_entry,
    get_runtime_mode,
    init_db,
    make_id,
    normalize_claim_text,
    rebuild_fts,
    retrieve_supporting_chunks,
    section_ref_from_heading,
    slugify,
    split_text_into_chunks,
    target_dir_for_page_type,
    utc_now,
)
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
        "ar5iv_url": f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
    }


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
    cleaned = re.sub(r"\$\$\s*(.*?)\s*\$\$", r"$$\n\1\n$$", cleaned)
    return cleaned.strip()


def tex_from_math_node(node: Any) -> str:
    annotation = node.find("annotation", attrs={"encoding": "application/x-tex"})
    tex = annotation.get_text("", strip=True) if annotation is not None else ""
    if not tex:
        tex = (node.get("alttext") or "").strip()
    tex = clean_html_text(tex)
    if not tex:
        return ""
    if node.get("display") == "block":
        return f"$$\n{tex}\n$$"
    return f"${tex}$"


def text_with_math(node: Any) -> str:
    clone = BeautifulSoup(str(node), "html.parser")
    for math_node in clone.select("math"):
        math_node.replace_with(clone.new_string(f" {tex_from_math_node(math_node)} "))
    return clean_html_text(clone.get_text(" ", strip=True))


def figure_label_from_caption(caption: str, fallback_index: int) -> str:
    match = re.match(r"^\s*((?:Figure|Fig\.|Table)\s+[A-Za-z0-9.]+)\s*[:.]", caption)
    if match:
        return clean_html_text(match.group(1).replace("Fig.", "Figure"))
    return f"Figure {fallback_index}"


def extract_figures_from_section(
    section: Any,
    *,
    section_path: str,
    section_ref: str | None,
    start_index: int,
) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for figure in section.find_all("figure", class_="ltx_figure", recursive=False):
        caption_node = figure.find("figcaption", class_="ltx_caption")
        caption = text_with_math(caption_node) if caption_node is not None else ""
        images: list[dict[str, Any]] = []
        for image_index, image in enumerate(figure.find_all("img"), start=1):
            src = (image.get("src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            images.append(
                {
                    "src": src,
                    "alt": clean_html_text(image.get("alt") or ""),
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "panel_index": image_index,
                }
            )
        if not images:
            continue
        label = figure_label_from_caption(caption, start_index + len(figures))
        figures.append(
            {
                "figure_id": figure.get("id"),
                "label": label,
                "caption": caption,
                "section_path": section_path,
                "section_ref": section_ref,
                "images": images,
            }
        )
    return figures


def equation_label_from_node(node: Any, fallback_index: int) -> str:
    container = node.find_parent(["table", "tr", "div"])
    if container is not None:
        tag = container.find(class_=re.compile(r"\bltx_tag_equation\b"))
        if tag is not None:
            label = clean_html_text(tag.get_text(" ", strip=True)).strip("()")
            if label:
                return f"Equation {label}"
    return f"Equation {fallback_index}"


def extract_equations_from_block(
    block: Any,
    *,
    section_path: str,
    section_ref: str | None,
    start_index: int,
) -> list[dict[str, Any]]:
    equations: list[dict[str, Any]] = []
    for math_node in block.find_all("math", attrs={"display": "block"}):
        tex = tex_from_math_node(math_node)
        if not tex:
            continue
        equations.append(
            {
                "label": equation_label_from_node(
                    math_node, start_index + len(equations)
                ),
                "tex": tex,
                "section_path": section_path,
                "section_ref": section_ref,
                "math_id": math_node.get("id"),
            }
        )
    return equations


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
        abstract = text_with_math(abstract_node)

    body_parts: list[str] = []
    section_markers: list[dict[str, Any]] = []
    section_blocks: dict[str, list[dict[str, str]]] = {}
    figures: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    current_offset = 0

    def append_block(text: str) -> int | None:
        nonlocal current_offset
        cleaned = clean_html_text(text)
        if not cleaned:
            return None
        if body_parts:
            current_offset += 2
        offset = current_offset
        body_parts.append(cleaned)
        current_offset += len(cleaned)
        return offset

    def append_section_block(role: str, section_path: str, texts: list[str]) -> None:
        block_text = "\n\n".join(text for text in texts if text).strip()
        if not block_text:
            return
        section_blocks.setdefault(role, []).append(
            {"section_path": section_path, "text": block_text}
        )

    if abstract:
        offset = append_block("Abstract")
        if offset is not None:
            section_markers.append(
                {
                    "offset": offset,
                    "raw_heading": "Abstract",
                    "level": 1,
                    "canonical_role": "abstract",
                    "section_path": "abstract",
                }
            )
        append_block(abstract)

    def visit_section(
        section: Any,
        *,
        root_role: str | None,
        path_parts: list[str],
        level: int,
    ) -> list[str]:
        heading_text = None
        for child in section.children:
            if getattr(child, "name", None) in {"h2", "h3", "h4", "h5", "h6"}:
                heading_text = text_with_math(child)
                break

        role = canonical_section_role(heading_text or "") or root_role or "body"
        if root_role is None or role != root_role:
            current_root_role = role
            current_parts: list[str] = []
        else:
            current_root_role = root_role
            current_parts = list(path_parts)

        normalized_heading = normalize_heading_text(heading_text or "").lower()
        if normalized_heading and normalized_heading not in {
            current_root_role,
            *current_parts,
        }:
            current_parts.append(normalized_heading)
        section_path = (
            " > ".join([current_root_role, *current_parts])
            if current_parts
            else current_root_role
        )
        section_ref = section_ref_from_heading(heading_text)

        figures.extend(
            extract_figures_from_section(
                section,
                section_path=section_path,
                section_ref=section_ref,
                start_index=len(figures) + 1,
            )
        )

        section_texts: list[str] = []
        for child in section.children:
            child_name = getattr(child, "name", None)
            if child_name in {"h2", "h3", "h4", "h5", "h6"}:
                child_heading = text_with_math(child)
                offset = append_block(child_heading)
                if offset is not None:
                    section_markers.append(
                        {
                            "offset": offset,
                            "raw_heading": child_heading,
                            "level": level,
                            "canonical_role": current_root_role,
                            "section_path": section_path,
                        }
                    )
            elif child_name == "section":
                section_texts.extend(
                    visit_section(
                        child,
                        root_role=current_root_role,
                        path_parts=current_parts,
                        level=level + 1,
                    )
                )
            elif child_name in {"p", "div"} and any(
                cls.startswith("ltx_p") or cls == "ltx_para"
                for cls in (child.get("class") or [])
            ):
                equations.extend(
                    extract_equations_from_block(
                        child,
                        section_path=section_path,
                        section_ref=section_ref,
                        start_index=len(equations) + 1,
                    )
                )
                para_text = text_with_math(child)
                if para_text:
                    append_block(para_text)
                    section_texts.append(para_text)

        append_section_block(current_root_role, section_path, section_texts)
        return section_texts

    article = soup.select_one("article")
    if article is not None:
        for section in article.find_all("section", recursive=False):
            visit_section(section, root_role=None, path_parts=[], level=1)

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
        "section_markers": section_markers,
        "section_blocks": section_blocks,
        "figures": figures,
        "equations": equations,
    }


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


def file_extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix
    return ".png"


def download_figure_assets(
    *,
    source_id: str,
    source_url: str,
    figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not figures:
        return []

    asset_dir = RAW_ASSETS_DIR / source_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    resolved_figures: list[dict[str, Any]] = []

    for figure_index, figure in enumerate(figures, start=1):
        resolved_images: list[dict[str, Any]] = []
        label_slug = slugify(figure.get("label") or f"figure-{figure_index}")
        figure_images = figure.get("images", [])
        for image_index, image in enumerate(figure_images, start=1):
            src = image.get("src")
            if not src:
                continue
            image_url = urljoin(f"{source_url.rstrip('/')}/", src)
            image_bytes = fetch_url_bytes(image_url)
            if not image_bytes:
                continue
            suffix = file_extension_from_url(image_url)
            panel_suffix = f"-{image_index}" if len(figure_images) > 1 else ""
            target = asset_dir / f"{label_slug}{panel_suffix}{suffix}"
            target.write_bytes(image_bytes)
            resolved_image = dict(image)
            resolved_image.update(
                {
                    "source_url": image_url,
                    "asset_path": str(target.relative_to(ROOT)),
                }
            )
            resolved_images.append(resolved_image)

        if not resolved_images:
            continue
        resolved_figure = dict(figure)
        resolved_figure["images"] = resolved_images
        resolved_figures.append(resolved_figure)

    return resolved_figures


def extraction_quality(
    *, page_count: int, extracted_text: str, chunk_count: int
) -> tuple[str, list[str]]:
    notes = [
        f"Extracted characters: {len(extracted_text)}",
        f"Indexed chunks: {chunk_count}",
        f"Logical document spans: {page_count}",
    ]
    if not extracted_text.strip():
        return "low", notes + ["No extractable text detected."]
    avg_chars = len(extracted_text) / max(page_count, 1)
    if avg_chars < 150:
        return "low", notes + ["Very little text extracted per logical span."]
    if avg_chars < 600:
        return "medium", notes + ["Extraction is usable but likely incomplete."]
    return "high", notes + ["Extraction looks strong enough for draft retrieval."]


GENERIC_HEADING_TERMS = [
    "Abstract",
    "Introduction",
    "Background",
    "Related Work",
    "Literature Review",
    "Preliminaries",
    "Problem Setup",
    "Methods",
    "Materials and Methods",
    "Approach",
    "Framework",
    "Algorithm",
    "Algorithms",
    "Implementation",
    "Model Architecture",
    "Architecture",
    "Training",
    "Training Data",
    "Data Collection",
    "Experimental Setup",
    "Setup",
    "Analysis",
    "Experiments",
    "Evaluation",
    "Results",
    "Findings",
    "Ablations",
    "Case Study",
    "Discussion",
    "Limitations",
    "Threats to Validity",
    "Future Work",
    "Conclusion",
    "Conclusions",
    "Appendix",
    "Supplementary",
    "Supplemental",
]

SECTION_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary"),
    "introduction": ("introduction",),
    "background": (
        "background",
        "related work",
        "literature review",
        "preliminar",
        "motivation",
        "problem setup",
    ),
    "method": (
        "method",
        "materials",
        "approach",
        "framework",
        "algorithm",
        "implementation",
        "architecture",
        "training",
        "optimizer",
        "regularization",
        "experimental setup",
        "setup",
        "data collection",
        "procedure",
        "proof",
        "theorem",
        "construction",
    ),
    "results": (
        "result",
        "finding",
        "evaluation",
        "experiment",
        "ablation",
        "case study",
        "benchmark",
        "comparison",
        "variation",
    ),
    "discussion": ("discussion", "interpretation"),
    "limitations": (
        "limitation",
        "threats to validity",
        "future work",
        "open questions",
        "caveat",
    ),
    "conclusion": ("conclusion", "concluding"),
    "appendix": ("appendix", "supplement", "supplementary"),
}


def normalize_heading_text(raw_heading: str) -> str:
    heading = raw_heading.strip()
    heading = re.sub(r"^(?:section\s+)?(?:\d+(?:\.\d+)*)\s*", "", heading, flags=re.IGNORECASE)
    heading = re.sub(r"\s+", " ", heading)
    heading = re.sub(r"[:.\-]+$", "", heading)
    return heading.strip()


def canonical_section_role(raw_heading: str) -> str | None:
    normalized = normalize_heading_text(raw_heading).lower()
    if not normalized:
        return None
    for role, keywords in SECTION_ROLE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return role
    return None


def heading_level(raw_heading: str) -> int:
    numbered = re.match(r"^(?:section\s+)?(\d+(?:\.\d+)*)\b", raw_heading.strip(), re.IGNORECASE)
    if numbered:
        return numbered.group(1).count(".") + 1
    return 1


def is_heading_candidate(paragraph: str) -> bool:
    cleaned = paragraph.strip()
    if not cleaned or len(cleaned) > 120:
        return False
    if cleaned.endswith((".", "?", "!")) and len(cleaned.split()) > 8:
        return False
    if canonical_section_role(cleaned):
        return True
    numbered = re.match(
        r"^(?:section\s+)?(\d+(?:\.\d+)*)\s+(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if not numbered:
        return False
    body = numbered.group(2).strip()
    if len(body.split()) > 8:
        return False
    if any(mark in body for mark in [",", ".", "?", "!", ";", ":"]):
        return False
    if len(re.findall(r"\d", body)) > 2:
        return False
    words = [word for word in re.split(r"\s+", body) if word]
    if not words:
        return False
    heading_like_words = 0
    for word in words:
        bare = re.sub(r"[^A-Za-z0-9&()/\-]", "", word)
        if not bare:
            continue
        if bare.isupper() or re.match(r"^[A-Z][a-z]+", bare):
            heading_like_words += 1
    return heading_like_words >= max(1, int(len(words) * 0.6))


def section_path_from_stack(role: str, stack: list[dict[str, Any]], current_heading: str) -> str:
    subheadings: list[str] = []
    for item in stack:
        heading = item["heading"]
        item_role = item["role"]
        if item_role == role:
            continue
        subheadings.append(heading.lower())
    current_normalized = normalize_heading_text(current_heading).lower()
    if current_normalized and current_normalized not in {role, *subheadings}:
        subheadings.append(current_normalized)
    if not subheadings:
        return role
    return " > ".join([role, *subheadings])


def detect_section_markers(text: str) -> list[dict[str, Any]]:
    heading_entries: list[dict[str, Any]] = []

    heading_term_pattern = "|".join(
        sorted((re.escape(term) for term in GENERIC_HEADING_TERMS), key=len, reverse=True)
    )

    numbered_canonical_pattern = re.compile(
        rf"(?<![A-Za-z0-9])(?P<number>(?:section\s+)?\d+(?:\.\d+)*)\s+(?P<label>{heading_term_pattern})\b",
        re.IGNORECASE,
    )
    for match in numbered_canonical_pattern.finditer(text):
        offset = match.start()
        raw_heading = f"{match.group('number') or ''}{match.group('label')}".strip()
        heading_entries.append(
            {
                "offset": offset,
                "raw_heading": raw_heading,
                "role": canonical_section_role(raw_heading),
                "level": heading_level(raw_heading),
            }
        )

    canonical_pattern = re.compile(
        rf"(^|\n\n)(?P<label>{heading_term_pattern})\b",
        re.IGNORECASE,
    )
    for match in canonical_pattern.finditer(text):
        offset = match.start() + len(match.group(1))
        raw_heading = match.group("label").strip()
        heading_entries.append(
            {
                "offset": offset,
                "raw_heading": raw_heading,
                "role": canonical_section_role(raw_heading),
                "level": heading_level(raw_heading),
            }
        )

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    cursor = 0
    for paragraph in paragraphs:
        offset = text.find(paragraph, cursor)
        if offset == -1:
            offset = cursor
        cursor = offset + len(paragraph)
        if not is_heading_candidate(paragraph):
            continue
        raw_heading = paragraph.strip()
        role = canonical_section_role(raw_heading)
        if role is None and re.match(
            r"^(?:section\s+)?\d+(?:\.\d+)*\b", raw_heading, re.IGNORECASE
        ):
            role = "body"
        if role is None:
            continue
        heading_entries.append(
            {
                "offset": offset,
                "raw_heading": raw_heading,
                "role": role,
                "level": heading_level(raw_heading),
            }
        )

    heading_entries.sort(key=lambda item: (item["offset"], item["level"]))
    deduped_entries: list[dict[str, Any]] = []
    for entry in heading_entries:
        if deduped_entries and abs(entry["offset"] - deduped_entries[-1]["offset"]) < 4:
            previous = deduped_entries[-1]
            previous_score = 1 if previous.get("role") not in {None, "body"} else 0
            entry_score = 1 if entry.get("role") not in {None, "body"} else 0
            if entry_score > previous_score:
                deduped_entries[-1] = entry
            continue
        deduped_entries.append(entry)

    markers: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for entry in deduped_entries:
        role = entry["role"]
        if role in {None, "body"}:
            role = stack[-1]["role"] if stack else "body"
        level = entry["level"]
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        heading_text = normalize_heading_text(entry["raw_heading"])
        marker = {
            "offset": entry["offset"],
            "raw_heading": entry["raw_heading"],
            "level": level,
            "canonical_role": role,
            "section_path": section_path_from_stack(role, stack, heading_text),
        }
        markers.append(marker)
        stack.append({"level": level, "heading": heading_text, "role": role})
    return markers


def build_page_markdown(
    *,
    title: str,
    source_id: str,
    version_id: str,
    page_rel: str,
    raw_rel: str,
    extracted_rel: str,
    page_count: int,
    canonical_locator: str | None,
    authors_or_creator: str | None,
    published_at: str | None,
    source_kind: str,
    source_url: str | None,
    chunk_count: int,
    quality_label: str,
    quality_notes: list[str],
    draft: dict,
    draft_packet: dict,
) -> str:
    packet_chunk_lookup = {
        chunk["chunk_id"]: chunk for chunk in draft_packet.get("chunks", [])
    }
    figure_lookup: dict[str, dict] = {}
    for figure in draft_packet.get("figures", []):
        for key in ("figure_id", "label"):
            value = figure.get(key)
            if isinstance(value, str) and value.strip():
                figure_lookup.setdefault(value.strip(), figure)
    equation_lookup: dict[str, dict] = {}
    for equation in draft_packet.get("equations", []):
        for key in ("math_id", "label"):
            value = equation.get(key)
            if isinstance(value, str) and value.strip():
                equation_lookup.setdefault(value.strip(), equation)

    def clean_text(text: str | None) -> str:
        cleaned = normalize_claim_text((text or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def section_refs(chunk_ids: list[str]) -> str:
        refs: list[str] = []
        for chunk_id in chunk_ids:
            chunk = packet_chunk_lookup.get(chunk_id)
            if chunk is None:
                continue
            ref = clean_text(chunk.get("section_ref"))
            if not ref:
                continue
            if ref.lower() == "abstract":
                label = "Abstract"
            elif re.match(r"^(?:Appendix\s+)?[A-Z](?:\.\d+)+$", ref):
                label = f"Appendix {ref}" if not ref.lower().startswith("appendix") else ref
            else:
                label = f"§ {ref}"
            if label not in refs:
                refs.append(label)
        return f"Sections: {', '.join(refs)}" if refs else ""

    def relative_asset_path(asset_path: str) -> str:
        page_parent = (ROOT / page_rel).parent
        return Path(os.path.relpath(ROOT / asset_path, page_parent)).as_posix()

    def selected_figures(figure_ids: list[str]) -> list[dict]:
        figures: list[dict] = []
        seen: set[int] = set()
        for figure_id in figure_ids:
            figure = figure_lookup.get(figure_id)
            if figure is None:
                continue
            object_id = id(figure)
            if object_id in seen:
                continue
            seen.add(object_id)
            figures.append(figure)
        return figures

    def selected_equations(equation_ids: list[str]) -> list[dict]:
        equations: list[dict] = []
        seen: set[int] = set()
        for equation_id in equation_ids:
            equation = equation_lookup.get(equation_id)
            if equation is None:
                continue
            object_id = id(equation)
            if object_id in seen:
                continue
            seen.add(object_id)
            equations.append(equation)
        return equations

    def render_selected_media(section: dict) -> str:
        blocks: list[str] = []
        for equation in selected_equations(section.get("equation_ids", [])):
            tex = (equation.get("tex") or "").strip()
            if tex:
                blocks.append(tex)
        for figure in selected_figures(section.get("figure_ids", [])):
            label = clean_text(figure.get("label")) or "Figure"
            caption = clean_text(figure.get("caption"))
            image_lines: list[str] = []
            for image in figure.get("images", []):
                asset_path = image.get("asset_path")
                if not asset_path:
                    continue
                alt = clean_text(image.get("alt")) or label
                image_lines.append(f"![{alt}]({relative_asset_path(asset_path)})")
            if not image_lines:
                continue
            figure_lines = [*image_lines]
            if caption:
                figure_lines.append(f"*{caption}*")
            blocks.append("\n\n".join(figure_lines))
        return "\n\n".join(blocks)

    def format_section(section: dict) -> str:
        text = clean_text(section.get("text"))
        if not text:
            return "Not extracted yet."
        media_block = render_selected_media(section)
        if media_block:
            return f"{text}\n\n{media_block}"
        return text

    def render_entry_sections(
        items: list[dict],
        *,
        empty_text: str,
    ) -> str:
        if not items:
            return empty_text
        blocks: list[str] = []
        for index, item in enumerate(items, start=1):
            title_text = clean_text(item.get("title")) or f"Entry {index}"
            text = clean_text(item.get("text"))
            if not text:
                continue
            refs = section_refs(item.get("chunk_ids", []))
            body = format_section(item)
            block = f"### {title_text}\n{body}"
            if refs:
                block = f"{block}\n\n{refs}"
            blocks.append(block)
        return "\n\n".join(blocks) if blocks else empty_text

    def render_bullet_sections(
        items: list[dict],
        *,
        empty_text: str,
    ) -> str:
        if not items:
            return empty_text
        blocks: list[str] = []
        for item in items:
            text = clean_text(item.get("text"))
            if not text:
                continue
            refs = section_refs(item.get("chunk_ids", []))
            suffix = f" ({refs})" if refs else ""
            media_block = render_selected_media(item)
            if media_block:
                blocks.append(f"- {text}{suffix}\n\n{media_block}")
            else:
                blocks.append(f"- {text}{suffix}")
        return "\n\n".join(blocks) if blocks else empty_text

    locator_line = canonical_locator or "Unknown"
    authors_line = authors_or_creator or "Unknown"
    published_line = published_at or "Unknown"
    big_picture = draft["big_picture"]
    problem_setting = draft.get("problem_setting", {})
    method_overview = draft["method_overview"]
    core_claims = draft.get("core_claims", [])
    method_details = draft.get("method_details", [])
    data_or_inputs = draft.get("data_or_inputs", [])
    experimental_setup = draft.get("experimental_setup", [])
    results = draft.get("results", [])
    analysis = draft.get("analysis", [])
    limitations = draft.get("limitations", [])
    open_questions = draft.get("open_questions", [])
    core_claims_block = render_entry_sections(
        core_claims,
        empty_text="No core claims extracted yet.",
    )
    method_details_block = render_entry_sections(
        method_details,
        empty_text="No method details extracted yet.",
    )
    data_or_inputs_block = render_entry_sections(
        data_or_inputs,
        empty_text="No important data or input details extracted yet.",
    )
    experimental_setup_block = render_entry_sections(
        experimental_setup,
        empty_text="No experimental setup details extracted yet.",
    )
    results_block = render_entry_sections(
        results,
        empty_text="No significant results extracted yet.",
    )
    analysis_block = render_entry_sections(
        analysis,
        empty_text="No analytical insights extracted yet.",
    )
    limitations_block = render_bullet_sections(
        limitations,
        empty_text="No limitations extracted yet.",
    )
    open_questions_block = render_bullet_sections(
        open_questions,
        empty_text="- No explicit open questions extracted yet.",
    )
    provenance_lines = [
        f"- Status: `needs-review`",
        f"- Canonical locator: {locator_line}",
        f"- Source ID: `{source_id}`",
        f"- Version ID: `{version_id}`",
        f"- Raw file: `{raw_rel}`",
        f"- Extracted text: `{extracted_rel}`",
        f"- Imported at: {utc_now()}",
        f"- Parsed source kind: `{source_kind}`",
        f"- Logical document spans: {page_count}",
        f"- Indexed chunks: {chunk_count}",
        f"- Extraction quality: `{quality_label}`",
    ]
    if source_url:
        provenance_lines.insert(4, f"- Parsed source URL: {source_url}")
    quality_block = "\n".join(f"- {note}" for note in quality_notes)
    return f"""---
title: {title}
page_type: paper
source_id: {source_id}
version_id: {version_id}
status: needs-review
verifier_status: pending
---

# {title}

- Authors: {authors_line}
- Published: {published_line}
- Status: `needs-review`
- Canonical locator: {locator_line}

## Big Picture

{format_section(big_picture)}

## Problem Setting

{format_section(problem_setting)}

## Core Claims

{core_claims_block}

## Method Overview

{format_section(method_overview)}

## Method Details

{method_details_block}

## Data And Inputs

{data_or_inputs_block}

## Experimental Setup

{experimental_setup_block}

## Results

{results_block}

## Analysis And Insights

{analysis_block}

## Limitations

{limitations_block}

## Open Questions

{open_questions_block}

## Provenance

{chr(10).join(provenance_lines)}

## Extraction Notes

{quality_block}
"""


def reserve_page_target(conn, title: str, source_id: str) -> Path:
    target_dir = target_dir_for_page_type("paper")
    candidate = target_dir / f"{slugify(title)}.md"
    suffix = source_id[-8:]
    while (
        candidate.exists()
        or conn.execute(
            "SELECT 1 FROM pages WHERE path = ?",
            (str(candidate.relative_to(ROOT)),),
        ).fetchone()
        is not None
    ):
        candidate = target_dir / f"{slugify(title)}-{suffix}.md"
        suffix = suffix + "x"
    return candidate


def prepare_ingest(
    *,
    source_input: str,
    title_override: str | None = None,
    canonical_locator_override: str | None = None,
) -> dict:
    arxiv_ref = parse_arxiv_reference(source_input)
    if arxiv_ref is None:
        exit_blocked("Supported inputs are arXiv identifiers or arXiv/ar5iv URLs.")

    source_kind = "html"
    source_url: str | None = None
    html_snapshot_text: str | None = None
    html_section_markers: list[dict[str, Any]] | None = None
    section_blocks: dict[str, list[dict[str, str]]] = {}
    canonical_locator = canonical_locator_override or arxiv_ref["canonical_locator"]

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
            conn.close()
            exit_blocked(
                "HTML is unavailable for this arXiv source. Only HTML-backed arXiv ingest is supported."
            )

    extracted_text = html_data["extracted_text"]
    page_breaks = html_data["page_breaks"]
    page_count = max(1, len(page_breaks)) if extracted_text else 0
    title = title_override.strip() if title_override else html_data["title"]
    authors_or_creator = html_data["authors_or_creator"]
    published_at = html_data["published_at"]
    html_section_markers = html_data.get("section_markers")
    section_blocks = html_data.get("section_blocks") or {}
    figures = html_data.get("figures") or []
    equations = html_data.get("equations") or []
    conn.close()

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

    html_target = RAW_HTML_DIR / f"{source_id}.html"
    extracted_target = RAW_EXTRACTED_DIR / f"{source_id}.txt"
    page_target = reserve_page_target(conn, title, source_id)

    if html_snapshot_text is None:
        conn.close()
        raise SystemExit("No HTML snapshot was captured for this arXiv source.")
    html_target.write_text(html_snapshot_text)
    parsed_snapshot_rel = str(html_target.relative_to(ROOT))
    raw_rel = str(html_target.relative_to(ROOT))
    extracted_target.write_text(extracted_text + ("\n" if extracted_text else ""))
    figure_assets = (
        download_figure_assets(
            source_id=source_id,
            source_url=source_url,
            figures=figures,
        )
        if source_url
        else []
    )

    section_markers = html_section_markers or detect_section_markers(extracted_text)
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
        full_paper_text=extracted_text,
        chunks=chunks,
        section_blocks=section_blocks,
    )
    draft_packet["figures"] = figure_assets
    draft_packet["equations"] = equations

    now = utc_now()
    prepared_rel = str((SYSTEM_CACHE_DIR / f"prepared-{source_id}.json").relative_to(ROOT))
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
            raw_rel,
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
            raw_rel,
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
        "raw_path": raw_rel,
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
        "workspace_mode": get_runtime_mode(),
        "agent_policy": agent_edit_policy(),
        "coordination": {
            "drafter_prompt_path": "prompts/drafter_prompt.md",
            "prepared_json_path": prepared_rel,
            "finalize_command": f"uv run scripts/hub.py add-source {source_input} --draft-output-file <draft.json> --json",
            "verify_command": f"uv run scripts/hub.py verify {str(page_target.relative_to(ROOT))} --json",
            "target_page_path": str(page_target.relative_to(ROOT)),
        },
        "draft_packet": draft_packet,
        "status": "prepared",
    }


def finalize_ingest(prepared: dict, draft_output: DraftOutput | None = None) -> dict:
    prepared = validate_prepared_ingest(prepared)
    if draft_output is None:
        raise ValueError(
            "draft output is required for ingest-finalize; run the external drafter first"
        )
    draft = run_drafter(
        prepared["draft_packet"],
        draft_output=draft_output,
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
        page_rel=prepared["page_path"],
        raw_rel=prepared["raw_path"],
        extracted_rel=prepared["extracted_path"],
        page_count=page_count,
        canonical_locator=prepared["canonical_locator"],
        authors_or_creator=prepared["authors_or_creator"],
        published_at=prepared["published_at"],
        source_kind=prepared["source_kind"],
        source_url=prepared["source_url"],
        chunk_count=chunk_count,
        quality_label=quality_label,
        quality_notes=quality_notes,
        draft=draft,
        draft_packet=prepared["draft_packet"],
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
        f"Ingested paper '{prepared['title']}' using {prepared['source_kind']} into {prepared['page_path']}"
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
    page_row = conn.execute(
        "SELECT primary_source_id FROM pages WHERE page_id = ?",
        (page_id,),
    ).fetchone()
    source_id = page_row["primary_source_id"] if page_row is not None else None

    def insert_section(claim_type: str, text: str, chunk_ids: list[str]) -> None:
        cleaned = normalize_claim_text(text)
        if not cleaned:
            return
        evidence_rows = [
            (item["chunk_id"], item["char_start"], item["char_end"])
            for item in retrieve_supporting_chunks(
                conn,
                claim_text=cleaned,
                source_id=source_id,
                top_k=3,
            )
        ]
        if not evidence_rows:
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

    for item in draft.get("core_claims", []):
        insert_section("core_claim", item["text"], item["chunk_ids"])
    for item in draft.get("results", []):
        insert_section("result", item["text"], item["chunk_ids"])
    for item in draft.get("analysis", []):
        insert_section("analysis", item["text"], item["chunk_ids"])
    for item in draft.get("limitations", []):
        insert_section("limitation", item["text"], item["chunk_ids"])
    return created
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
