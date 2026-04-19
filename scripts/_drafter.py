from __future__ import annotations

import re
from typing import Literal, TypedDict


class DraftChunk(TypedDict):
    chunk_id: str
    section_path: str | None
    chunk_text: str
    char_start: int
    char_end: int
    page_num: int | None


class DraftPacket(TypedDict):
    source_id: str
    title: str
    source_kind: str
    source_type: str
    authors_or_creator: str | None
    published_at: str | None
    canonical_locator: str | None
    extraction_quality: str
    extraction_notes: list[str]
    chunks: list[DraftChunk]


class DraftSection(TypedDict):
    text: str
    chunk_ids: list[str]


class DraftOutput(TypedDict):
    summary: DraftSection
    key_points: list[DraftSection]
    limitations: list[DraftSection]


SECTION_PRIORITY = {
    "abstract": 0,
    "introduction": 1,
    "results": 2,
    "conclusion": 3,
    "discussion": 4,
}


def summarize_paragraph(paragraph: str, max_sentences: int = 3) -> str:
    cleaned = paragraph.strip()
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = " ".join(sentences[:max_sentences]).strip()
    return summary[:600]


def build_draft_packet(
    *,
    source_id: str,
    title: str,
    source_kind: str,
    authors_or_creator: str | None,
    published_at: str | None,
    canonical_locator: str | None,
    quality_label: str,
    quality_notes: list[str],
    chunks: list[DraftChunk],
) -> DraftPacket:
    ranked_chunks = sorted(chunks, key=chunk_rank)
    selected = ranked_chunks[:8]
    packet_chunks = [
        {
            **chunk,
            "chunk_id": persisted_chunk_id(source_id, chunk["chunk_id"]),
        }
        for chunk in selected
    ]
    return {
        "source_id": source_id,
        "title": title,
        "source_kind": source_kind,
        "source_type": "paper",
        "authors_or_creator": authors_or_creator,
        "published_at": published_at,
        "canonical_locator": canonical_locator,
        "extraction_quality": quality_label,
        "extraction_notes": quality_notes,
        "chunks": packet_chunks,
    }


def chunk_rank(chunk: DraftChunk) -> tuple[int, int]:
    section_path = (chunk.get("section_path") or "").lower()
    priority = next(
        (weight for label, weight in SECTION_PRIORITY.items() if label in section_path),
        99,
    )
    return priority, chunk["char_start"]


def draft_from_packet(packet: DraftPacket) -> DraftOutput:
    chunks = [
        chunk for chunk in packet["chunks"] if not is_heading_only(chunk["chunk_text"])
    ]
    if not chunks:
        chunks = packet["chunks"]
    source_id = packet["source_id"]
    summary_chunk = chunks[0] if chunks else None
    summary_text = (
        summarize_paragraph(summary_chunk["chunk_text"]) if summary_chunk else ""
    )
    if not summary_text:
        summary_text = (
            "TODO: Add evidence-backed summary after retrieval and verification."
        )

    key_points = [
        {
            "text": summarize_paragraph(chunk["chunk_text"], max_sentences=1),
            "chunk_ids": [chunk["chunk_id"]],
        }
        for chunk in chunks[1:4]
        if summarize_paragraph(chunk["chunk_text"], max_sentences=1)
    ]

    limitation_chunks = [
        chunk
        for chunk in chunks
        if any(
            token in chunk["chunk_text"].lower()
            for token in [
                "limitation",
                "future work",
                "however",
                "although",
                "we leave",
            ]
        )
    ][:2]
    limitations = [
        {
            "text": summarize_paragraph(chunk["chunk_text"], max_sentences=1),
            "chunk_ids": [chunk["chunk_id"]],
        }
        for chunk in limitation_chunks
        if summarize_paragraph(chunk["chunk_text"], max_sentences=1)
    ]

    return {
        "summary": {
            "text": summary_text,
            "chunk_ids": [summary_chunk["chunk_id"]] if summary_chunk else [],
        },
        "key_points": key_points,
        "limitations": limitations,
    }


def run_drafter(
    packet: DraftPacket,
    *,
    draft_output: DraftOutput | None = None,
    mode: Literal["heuristic", "external"] = "heuristic",
) -> DraftOutput:
    if draft_output is not None:
        return validate_draft_output(packet, draft_output, strict=(mode == "external"))
    if mode == "heuristic":
        return draft_from_packet(packet)
    raise ValueError("external drafter mode requires draft_output")


def validate_draft_output(
    packet: DraftPacket, draft_output: DraftOutput, *, strict: bool = False
) -> DraftOutput:
    allowed_chunk_ids = {chunk["chunk_id"] for chunk in packet["chunks"]}

    def normalize_section(
        section: object, *, allow_empty: bool = False
    ) -> DraftSection:
        if not isinstance(section, dict):
            raise ValueError("draft section must be an object")
        text = section.get("text", "")
        chunk_ids = section.get("chunk_ids", [])
        if not isinstance(text, str):
            raise ValueError("draft section text must be a string")
        if not isinstance(chunk_ids, list) or any(
            not isinstance(item, str) for item in chunk_ids
        ):
            raise ValueError("draft section chunk_ids must be a list of strings")
        if not allow_empty and not text.strip():
            raise ValueError("draft section text cannot be empty")
        invalid_ids = [item for item in chunk_ids if item not in allowed_chunk_ids]
        if invalid_ids:
            raise ValueError(f"unknown chunk ids in draft output: {invalid_ids}")
        return {
            "text": text.strip(),
            "chunk_ids": chunk_ids,
        }

    if not isinstance(draft_output, dict):
        raise ValueError("draft output must be an object")

    summary = normalize_section(draft_output.get("summary", {}), allow_empty=True)
    key_points_raw = draft_output.get("key_points", [])
    limitations_raw = draft_output.get("limitations", [])
    if not isinstance(key_points_raw, list) or not isinstance(limitations_raw, list):
        raise ValueError("key_points and limitations must be lists")
    if strict and any(not isinstance(item, dict) for item in key_points_raw):
        raise ValueError("all key_points entries must be objects")
    if strict and any(not isinstance(item, dict) for item in limitations_raw):
        raise ValueError("all limitations entries must be objects")

    key_points = [
        normalize_section(item) for item in key_points_raw[:5] if isinstance(item, dict)
    ]
    limitations = [
        normalize_section(item)
        for item in limitations_raw[:3]
        if isinstance(item, dict)
    ]
    normalized = {
        "summary": summary,
        "key_points": key_points,
        "limitations": limitations,
    }
    if strict and not normalized["summary"]["text"]:
        raise ValueError("external draft output must include a non-empty summary")
    return normalized


def persisted_chunk_id(source_id: str, chunk_id: str) -> str:
    return f"{source_id}_{chunk_id}"


def is_heading_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    word_count = len(stripped.split())
    return word_count <= 3 and stripped.lower() in {
        "abstract",
        "introduction",
        "background",
        "methods",
        "method",
        "approach",
        "results",
        "discussion",
        "conclusion",
    }
