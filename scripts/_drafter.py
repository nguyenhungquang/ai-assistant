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
    paper_metadata: dict
    drafting_rules: list[str]
    draft_template: str
    candidate_groups: dict
    chunks: list[DraftChunk]


class DraftCandidate(TypedDict):
    chunk_id: str
    section_path: str | None
    page_num: int | None
    text: str
    signals: list[str]
    sentence_start: int
    sentence_end: int
    score: int


class DraftSection(TypedDict):
    text: str
    chunk_ids: list[str]


class DraftOutput(TypedDict):
    big_picture: DraftSection
    main_contributions: list[DraftSection]
    main_results: list[DraftSection]
    method_overview: DraftSection
    detailed_findings: list[DraftSection]
    limitations: list[DraftSection]
    open_questions: list[DraftSection]


SECTION_PRIORITY_KEYWORDS = [
    (("abstract", "summary"), 0),
    (("introduction", "overview"), 1),
    (("results", "findings", "evaluation", "experiment"), 2),
    (("conclusion", "conclusions"), 3),
    (("discussion",), 4),
    (
        (
            "method",
            "methods",
            "materials",
            "approach",
            "framework",
            "algorithm",
            "implementation",
            "architecture",
            "training",
            "proof",
        ),
        5,
    ),
]

CONTRIBUTION_CUES = [
    "we propose",
    "we introduce",
    "we present",
    "we develop",
    "we design",
    "we derive",
    "we formulate",
    "we study",
    "we analyze",
    "our contribution",
    "contributions",
    "our framework",
    "our approach",
    "our method",
    "this paper presents",
    "in this work",
]
RESULT_CUES = [
    "outperform",
    "improve",
    "improves over",
    "achieve",
    "superior",
    "lower than",
    "higher than",
    "compared to",
    "relative to",
    "significant",
    "substantial",
    "we find",
    "we show",
    "we observe",
    "results indicate",
    "demonstrate",
    "reduce",
    "increase",
    "state-of-the-art",
    "accuracy",
    "f1",
    "results show",
]
METHOD_CUES = [
    "we study",
    "we analyze",
    "we evaluate",
    "we design",
    "we develop",
    "we derive",
    "algorithm",
    "procedure",
    "framework",
    "architecture",
    "experimental setup",
    "data collection",
    "materials and methods",
    "simulation",
    "proof",
    "training",
    "objective",
    "approach",
    "method",
]
LIMITATION_CUES = [
    "limitation",
    "future work",
    "we leave",
    "restricted",
    "limited by",
    "cannot",
    "does not",
    "only applies",
    "under the assumption",
    "threats to validity",
    "further study is needed",
    "remains unclear",
    "we plan to",
    "we plan",
    "another research goal",
]
DETAIL_CUES = [
    "dataset",
    "benchmark",
    "sample",
    "participants",
    "evaluation",
    "baseline",
    "comparison",
    "ablat",
    "table",
    "experiment",
    "measurement",
    "simulation",
]
RESULT_SECTION_CUES = {"results", "discussion", "conclusion"}
NOISE_CUES = [
    "permission to reproduce",
    "all rights reserved",
    "copyright",
    "preprint",
    "corresponding author",
    "author affiliations",
    "arxiv:",
]


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
    ranked_chunks = [
        chunk
        for chunk in sorted(chunks, key=chunk_rank)
        if not is_heading_only(chunk["chunk_text"])
        and not is_noise_chunk(chunk)
        and not is_reference_like(chunk)
    ]
    selected = ranked_chunks[:12]
    packet_chunks = [
        {
            **chunk,
            "chunk_id": persisted_chunk_id(source_id, chunk["chunk_id"]),
        }
        for chunk in selected
    ]
    big_picture_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: "abstract" in (chunk.get("section_path") or "").lower()
        or "introduction" in (chunk.get("section_path") or "").lower()
        or "conclusion" in (chunk.get("section_path") or "").lower(),
        limit=4,
        role="big_picture",
    )
    contribution_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: text_matches(chunk, CONTRIBUTION_CUES)
        or "abstract" in (chunk.get("section_path") or "").lower(),
        limit=5,
        role="contribution",
    )
    result_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: is_result_like(chunk) and supports_result_role(chunk),
        limit=5,
        role="result",
    )
    method_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: text_matches(chunk, METHOD_CUES),
        limit=4,
        role="method",
    )
    detail_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: (
            (is_result_like(chunk) and supports_result_role(chunk))
            or text_matches(chunk, DETAIL_CUES)
        ),
        limit=6,
        role="detail",
    )
    limitation_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: text_matches(chunk, LIMITATION_CUES),
        limit=4,
        role="limitation",
    )
    big_picture_candidates = pick_candidate_spans(
        big_picture_chunks,
        predicate=lambda _chunk: True,
        limit=4,
        role="big_picture",
        top_chunk_limit=4,
    )
    contribution_candidates = pick_candidate_spans(
        contribution_chunks,
        predicate=lambda _chunk: True,
        limit=5,
        role="contribution",
        top_chunk_limit=5,
    )
    result_candidates = pick_candidate_spans(
        result_chunks,
        predicate=lambda _chunk: True,
        limit=5,
        role="result",
        top_chunk_limit=5,
    )
    method_candidates = pick_candidate_spans(
        method_chunks,
        predicate=lambda _chunk: True,
        limit=4,
        role="method",
        top_chunk_limit=4,
    )
    detail_candidates = pick_candidate_spans(
        detail_chunks,
        predicate=lambda _chunk: True,
        limit=6,
        role="detail",
        top_chunk_limit=6,
    )
    limitation_candidates = pick_candidate_spans(
        limitation_chunks,
        predicate=lambda _chunk: True,
        limit=4,
        role="limitation",
        top_chunk_limit=4,
    )

    def bundle_candidates(items: list[DraftCandidate]) -> list[dict]:
        bundled: list[dict] = []
        for candidate in items:
            bundled.append(
                {
                    "chunk_id": candidate["chunk_id"],
                    "section_path": candidate.get("section_path"),
                    "page_num": candidate.get("page_num"),
                    "text": candidate["text"],
                    "signals": candidate["signals"],
                    "sentence_start": candidate["sentence_start"],
                    "sentence_end": candidate["sentence_end"],
                    "score": candidate["score"],
                }
            )
        return bundled

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
        "paper_metadata": {
            "title": title,
            "authors_or_creator": authors_or_creator,
            "published_at": published_at,
            "canonical_locator": canonical_locator,
            "source_kind": source_kind,
        },
        "drafting_rules": [
            "Write for a human reader using a top-down structure.",
            "Start with high-level ideas and main contributions before details.",
            "Do not invent facts or use evidence outside this packet.",
            "Use only packet chunk IDs for evidence linkage.",
            "Prefer plain-English synthesis over copied source text when possible.",
            "Method Overview must explain how the paper works using method evidence, not result evidence.",
            "If the source contains equations or formal expressions, render them using Obsidian-compatible math syntax with $...$ or $$...$$.",
        ],
        "draft_template": (
            "Write a top-down research note with: big_picture, main_contributions, "
            "main_results, method_overview, detailed_findings, limitations, open_questions. "
            "Use only packet chunk IDs as evidence."
        ),
        "candidate_groups": {
            "big_picture_candidates": bundle_candidates(big_picture_candidates),
            "main_contribution_candidates": bundle_candidates(contribution_candidates),
            "main_result_candidates": bundle_candidates(result_candidates),
            "method_candidates": bundle_candidates(method_candidates),
            "detailed_finding_candidates": bundle_candidates(detail_candidates),
            "limitation_candidates": bundle_candidates(limitation_candidates),
        },
        "chunks": packet_chunks,
    }


def chunk_rank(chunk: DraftChunk) -> tuple[int, int]:
    section_path = (chunk.get("section_path") or "").lower()
    priority = next(
        (
            weight
            for labels, weight in SECTION_PRIORITY_KEYWORDS
            if any(label in section_path for label in labels)
        ),
        99,
    )
    return priority, chunk["char_start"]


def text_matches(chunk: DraftChunk, cues: list[str]) -> bool:
    text = chunk["chunk_text"].lower()
    return any(cue in text for cue in cues)


def candidate_signals(chunk: DraftChunk) -> list[str]:
    signals: list[str] = []
    section_path = (chunk.get("section_path") or "").lower()
    if section_path:
        signals.append(f"section:{section_path}")
    if text_matches(chunk, CONTRIBUTION_CUES):
        signals.append("cue:contribution")
    if text_matches(chunk, METHOD_CUES):
        signals.append("cue:method")
    if text_matches(chunk, LIMITATION_CUES):
        signals.append("cue:limitation")
    if text_matches(chunk, DETAIL_CUES):
        signals.append("cue:detail")
    if is_result_like(chunk):
        signals.append("cue:result")
    if is_noise_chunk(chunk):
        signals.append("cue:noise")
    return signals


def is_result_like(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"].lower()
    return text_matches(chunk, RESULT_CUES) or bool(
        re.search(
            r"\b\d+(?:\.\d+)?\s*(?:%|percent|accuracy|f1|auc|r2|rmse|mae|hours?|days?|seconds?|ms|x)\b",
            text,
        )
        or re.search(
            r"\b(vs\.?|versus|compared to|relative to|baseline|control)\b",
            text,
        )
    )


def is_reference_like(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"].strip().lower()
    return (
        text.startswith("references [1]")
        or text.startswith("references ")
        or "arxiv preprint arxiv:" in text
        or bool(re.match(r"^\[\d+\]\s+[a-z]", text))
    )


def is_table_heavy(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"].strip()
    lowered = text.lower()
    if lowered.startswith(("table ", "figure ")):
        return True
    numeric_cells = len(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    citations = len(re.findall(r"\[\d+\]", text))
    return numeric_cells >= 12 and citations >= 4


def is_visualization_chunk(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"].lower()
    return (
        "<eos>" in text
        or "<pad>" in text
        or "input-input layer" in text
        or text.startswith("attention visualizations")
    )


def is_noise_chunk(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"].lower()
    if any(cue in text for cue in NOISE_CUES):
        return True
    if text.count("@") >= 2:
        return True
    if len(re.findall(r"\bdepartment\b|\buniversity\b|\binstitute\b|\bschool\b|\blaboratory\b", text)) >= 4:
        return True
    if len(re.findall(r"\bvol\.?\b|\bno\.?\b|\bpp\.?\b|\bdoi\b", text)) >= 3:
        return True
    if is_reference_like(chunk):
        return True
    if is_visualization_chunk(chunk):
        return True
    if len(text.split()) < 6:
        return True
    return False


def supports_result_role(chunk: DraftChunk) -> bool:
    section = (chunk.get("section_path") or "").lower()
    text = chunk["chunk_text"].lower()
    return (
        any(label in section for label in RESULT_SECTION_CUES)
        or bool(
            re.search(
                r"\b\d+(?:\.\d+)?\s*(?:%|percent|accuracy|f1|auc|r2|rmse|mae|hours?|days?|seconds?|ms|x)\b",
                text,
            )
        )
        or bool(re.search(r"\b(vs\.?|versus|compared to|relative to|baseline|control)\b", text))
    )


def strip_leading_heading(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(
        r"^(?:\d+(?:\.\d+)*\s+)?(Abstract|Introduction|Background|Related Work|Literature Review|Preliminaries|Problem Setup|Methods?|Materials(?:\s+and\s+Methods)?|Approach|Framework|Algorithm|Algorithms|Implementation|Architecture|Training|Experimental Setup|Setup|Data Collection|Analysis|Experiments?|Evaluation|Results?|Findings|Ablations?|Case Study|Discussion|Conclusions?|Limitations?|Threats to Validity|Future Work|Appendix|Supplementary|Supplemental)\b[:.\s-]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:\d+(?:\.\d+)*)\s+[A-Z][A-Za-z0-9][A-Za-z0-9 ,/&()-]{2,80}\b[:.\s-]*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def split_sentences_with_indices(text: str) -> list[tuple[int, str]]:
    sentences = split_sentences(text)
    return list(enumerate(sentences))


def normalized_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "by",
        "at",
        "is",
        "are",
        "was",
        "were",
        "this",
        "that",
        "these",
        "those",
        "our",
        "we",
    }
    return {token for token in tokens if token not in stop_words}


def lexical_overlap(a: str, b: str) -> float:
    left = normalized_tokens(a)
    right = normalized_tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def spans_overlap(a: DraftCandidate, b: DraftCandidate) -> bool:
    if a["chunk_id"] != b["chunk_id"]:
        return False
    return not (
        a["sentence_end"] < b["sentence_start"]
        or b["sentence_end"] < a["sentence_start"]
    )


def is_near_duplicate(candidate: DraftCandidate, picked: list[DraftCandidate]) -> bool:
    for existing in picked:
        if candidate["chunk_id"] != existing["chunk_id"]:
            continue
        if spans_overlap(candidate, existing):
            return True
        if lexical_overlap(candidate["text"], existing["text"]) >= 0.75:
            return True
    return False


def sentence_quality(sentence: str) -> int:
    score = 0
    if re.match(r"^[A-Z(]", sentence):
        score += 2
    elif re.match(r"^[a-z]", sentence):
        score -= 4
    if len(sentence.split()) < 6:
        score -= 3
    if re.search(r"\b\d+(?:\.\d+)?\b", sentence):
        score += 1
    if sentence.lower().startswith(("table ", "figure ", "references ")):
        score -= 6
    return score


def role_sentence_score(sentence: str, role: str) -> int:
    lowered = sentence.lower()
    score = sentence_quality(sentence)
    if role == "big_picture":
        if any(cue in lowered for cue in CONTRIBUTION_CUES):
            score += 4
        if "this paper" in lowered or "in this work" in lowered:
            score += 3
    elif role == "contribution":
        if any(cue in lowered for cue in CONTRIBUTION_CUES):
            score += 5
    elif role == "result":
        if any(cue in lowered for cue in RESULT_CUES):
            score += 5
    elif role == "method":
        if any(cue in lowered for cue in METHOD_CUES):
            score += 5
    elif role == "detail":
        if any(cue in lowered for cue in DETAIL_CUES):
            score += 4
        if any(cue in lowered for cue in RESULT_CUES):
            score += 2
    elif role == "limitation":
        if any(cue in lowered for cue in LIMITATION_CUES):
            score += 5
    if lowered.startswith(("table ", "figure ", "references ")):
        score -= 8
    return score


def normalized_candidate_text(
    chunk: DraftChunk, *, role: str = "detail", max_sentences: int = 2
) -> str:
    text = strip_leading_heading(chunk["chunk_text"])
    if not text:
        return ""
    sentences = split_sentences(text)
    if not sentences:
        return summarize_paragraph(text, max_sentences=max_sentences)

    ranked_sentences = sorted(
        sentences,
        key=lambda sentence: role_sentence_score(sentence, role),
        reverse=True,
    )
    picked: list[str] = []
    for sentence in ranked_sentences:
        if role_sentence_score(sentence, role) < 0:
            continue
        if sentence in picked:
            continue
        picked.append(sentence)
        if len(picked) >= max_sentences:
            break
    if not picked:
        picked = [sentences[0]]
    return " ".join(picked).strip()


def sentence_span_candidates(
    chunk: DraftChunk, *, role: str, max_grouped_sentences: int = 2
) -> list[DraftCandidate]:
    text = strip_leading_heading(chunk["chunk_text"])
    sentence_items = split_sentences_with_indices(text)
    if not sentence_items:
        return []

    candidates: list[DraftCandidate] = []
    for index, sentence in sentence_items:
        base_score = role_sentence_score(sentence, role)
        if base_score < 0:
            continue
        candidates.append(
            {
                "chunk_id": chunk["chunk_id"],
                "section_path": chunk.get("section_path"),
                "page_num": chunk.get("page_num"),
                "text": sentence,
                "signals": candidate_signals(chunk),
                "sentence_start": index,
                "sentence_end": index,
                "score": base_score + candidate_score(chunk, role),
            }
        )

    if max_grouped_sentences < 2:
        return candidates

    for index in range(len(sentence_items) - 1):
        left_idx, left = sentence_items[index]
        right_idx, right = sentence_items[index + 1]
        merged = f"{left} {right}".strip()
        merged_score = (
            role_sentence_score(left, role)
            + role_sentence_score(right, role)
            + candidate_score(chunk, role)
        )
        if merged_score < candidate_score(chunk, role):
            continue
        candidates.append(
            {
                "chunk_id": chunk["chunk_id"],
                "section_path": chunk.get("section_path"),
                "page_num": chunk.get("page_num"),
                "text": merged,
                "signals": candidate_signals(chunk),
                "sentence_start": left_idx,
                "sentence_end": right_idx,
                "score": merged_score,
            }
        )
    return candidates


def section_score(chunk: DraftChunk, preferred: set[str]) -> int:
    section = (chunk.get("section_path") or "").lower()
    if not section:
        return 0
    return 3 if any(label in section for label in preferred) else 0


def candidate_score(chunk: DraftChunk, role: str) -> int:
    score = 0
    if is_noise_chunk(chunk):
        score -= 100
    if is_table_heavy(chunk):
        score -= 12 if role in {"big_picture", "contribution", "method", "limitation"} else 4
    if role == "big_picture":
        score += section_score(chunk, {"abstract", "introduction", "conclusion"})
        if text_matches(chunk, CONTRIBUTION_CUES):
            score += 3
        if "this paper" in chunk["chunk_text"].lower() or "in this work" in chunk["chunk_text"].lower():
            score += 2
        if is_result_like(chunk):
            score -= 1
    elif role == "contribution":
        score += section_score(chunk, {"abstract", "introduction"})
        if text_matches(chunk, CONTRIBUTION_CUES):
            score += 4
    elif role == "result":
        score += section_score(chunk, {"abstract", "results", "discussion", "conclusion"})
        if is_result_like(chunk):
            score += 4
    elif role == "method":
        score += section_score(chunk, {"method", "approach", "architecture"})
        if text_matches(chunk, METHOD_CUES):
            score += 4
        if is_result_like(chunk):
            score -= 1
    elif role == "detail":
        score += section_score(chunk, {"results", "discussion", "method"})
        if text_matches(chunk, DETAIL_CUES):
            score += 3
        if is_result_like(chunk):
            score += 2
    elif role == "limitation":
        score += section_score(chunk, {"discussion", "conclusion", "limitations"})
        if text_matches(chunk, LIMITATION_CUES):
            score += 4
    score += min(len(chunk["chunk_text"].split()) // 25, 3)
    if normalized_candidate_text(chunk, role=role, max_sentences=1):
        score += 1
    return score


def pick_chunks(chunks: list[DraftChunk], *, predicate, limit: int, role: str) -> list[DraftChunk]:
    picked: list[DraftChunk] = []
    seen_texts: set[str] = set()
    ranked = sorted(
        [chunk for chunk in chunks if predicate(chunk)],
        key=lambda chunk: (-candidate_score(chunk, role), chunk_rank(chunk)),
    )
    for chunk in ranked:
        if is_noise_chunk(chunk):
            continue
        if not predicate(chunk):
            continue
        normalized = normalized_candidate_text(chunk, role=role, max_sentences=1)
        if not normalized or normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        picked.append(chunk)
        if len(picked) >= limit:
            break
    return picked


def pick_candidate_spans(
    chunks: list[DraftChunk],
    *,
    predicate,
    limit: int,
    role: str,
    top_chunk_limit: int = 12,
) -> list[DraftCandidate]:
    ranked_chunks = sorted(
        [chunk for chunk in chunks if predicate(chunk) and not is_noise_chunk(chunk)],
        key=lambda chunk: (-candidate_score(chunk, role), chunk_rank(chunk)),
    )[:top_chunk_limit]

    span_pool: list[DraftCandidate] = []
    for chunk in ranked_chunks:
        span_pool.extend(sentence_span_candidates(chunk, role=role))

    seen_texts: set[str] = set()
    picked: list[DraftCandidate] = []
    for candidate in sorted(span_pool, key=lambda item: item["score"], reverse=True):
        normalized = re.sub(r"\s+", " ", candidate["text"]).strip()
        if not normalized or normalized in seen_texts:
            continue
        if is_near_duplicate(candidate, picked):
            continue
        seen_texts.add(normalized)
        picked.append(candidate)
        if len(picked) >= limit:
            break
    return picked


def make_section(
    chunk: DraftChunk | None, *, role: str = "detail", max_sentences: int = 2
) -> DraftSection:
    if chunk is None:
        return {"text": "", "chunk_ids": []}
    return {
        "text": normalized_candidate_text(chunk, role=role, max_sentences=max_sentences),
        "chunk_ids": [chunk["chunk_id"]],
    }


def make_sections(
    chunks: list[DraftChunk], *, role: str, max_sentences: int = 1
) -> list[DraftSection]:
    return [
        {
            "text": normalized_candidate_text(
                chunk, role=role, max_sentences=max_sentences
            ),
            "chunk_ids": [chunk["chunk_id"]],
        }
        for chunk in chunks
        if normalized_candidate_text(chunk, role=role, max_sentences=max_sentences)
    ]


def draft_from_packet(packet: DraftPacket) -> DraftOutput:
    chunks = [
        chunk
        for chunk in packet["chunks"]
        if not is_heading_only(chunk["chunk_text"]) and not is_reference_like(chunk)
    ]
    if not chunks:
        chunks = packet["chunks"]

    big_picture_chunk = next(
        iter(
            pick_chunks(
                chunks,
                predicate=lambda chunk: (
                    "abstract" in (chunk.get("section_path") or "").lower()
                    or "introduction" in (chunk.get("section_path") or "").lower()
                    or text_matches(chunk, CONTRIBUTION_CUES)
                ),
                limit=1,
                role="big_picture",
            )
        ),
        chunks[0] if chunks else None,
    )
    method_candidates = pick_chunks(
        chunks,
        predicate=lambda chunk: text_matches(chunk, METHOD_CUES),
        limit=2,
        role="method",
    )
    method_chunk = next(
        iter(method_candidates),
        chunks[1] if len(chunks) > 1 else big_picture_chunk,
    )
    contribution_chunks = pick_chunks(
        chunks,
        predicate=lambda chunk: text_matches(chunk, CONTRIBUTION_CUES)
        or "abstract" in (chunk.get("section_path") or "").lower(),
        limit=4,
        role="contribution",
    )
    result_chunks = pick_chunks(
        chunks,
        predicate=lambda chunk: is_result_like(chunk) and supports_result_role(chunk),
        limit=4,
        role="result",
    )
    limitation_chunks = pick_chunks(
        chunks,
        predicate=lambda chunk: text_matches(chunk, LIMITATION_CUES),
        limit=3,
        role="limitation",
    )
    detail_chunks = pick_chunks(
        chunks,
        predicate=lambda chunk: (
            (is_result_like(chunk) and supports_result_role(chunk))
            or text_matches(chunk, DETAIL_CUES)
        ),
        limit=4,
        role="detail",
    )

    open_questions = []
    if limitation_chunks:
        open_questions = [
            {
                "text": (
                    f"Open question from {chunk.get('section_path') or 'the paper'}: "
                    f"{summarize_paragraph(chunk['chunk_text'], max_sentences=1)}"
                ),
                "chunk_ids": [chunk["chunk_id"]],
            }
            for chunk in limitation_chunks[:2]
            if summarize_paragraph(chunk["chunk_text"], max_sentences=1)
        ]

    return {
        "big_picture": make_section(
            big_picture_chunk, role="big_picture", max_sentences=3
        ),
        "main_contributions": make_sections(
            contribution_chunks[:3], role="contribution", max_sentences=1
        ),
        "main_results": make_sections(
            result_chunks[:3], role="result", max_sentences=1
        ),
        "method_overview": make_section(
            method_chunk, role="method", max_sentences=2
        ),
        "detailed_findings": make_sections(
            detail_chunks[:4], role="detail", max_sentences=1
        ),
        "limitations": make_sections(
            limitation_chunks[:3], role="limitation", max_sentences=1
        ),
        "open_questions": open_questions,
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
    allowed_chunk_id_count = max(len(allowed_chunk_ids), 1)

    def normalize_section(section: object, *, allow_empty: bool = False) -> DraftSection:
        if not isinstance(section, dict):
            raise ValueError("draft section must be an object")
        text = section.get("text", "")
        chunk_ids = section.get("chunk_ids", [])
        if not isinstance(text, str):
            raise ValueError("draft section text must be a string")
        if not isinstance(chunk_ids, list) or any(not isinstance(item, str) for item in chunk_ids):
            raise ValueError("draft section chunk_ids must be a list of strings")
        if not allow_empty and not text.strip():
            raise ValueError("draft section text cannot be empty")
        invalid_ids = [item for item in chunk_ids if item not in allowed_chunk_ids]
        if invalid_ids:
            raise ValueError(f"unknown chunk ids in draft output: {invalid_ids}")
        return {"text": text.strip(), "chunk_ids": chunk_ids}

    def normalize_section_list(items: object, *, limit: int) -> list[DraftSection]:
        if not isinstance(items, list):
            raise ValueError("draft section list must be a list")
        if strict and any(not isinstance(item, dict) for item in items):
            raise ValueError("all draft list entries must be objects")
        return [
            normalize_section(item)
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    if not isinstance(draft_output, dict):
        raise ValueError("draft output must be an object")

    normalized = {
        "big_picture": normalize_section(
            draft_output.get("big_picture", {}), allow_empty=True
        ),
        "main_contributions": normalize_section_list(
            draft_output.get("main_contributions", []), limit=5
        ),
        "main_results": normalize_section_list(
            draft_output.get("main_results", []), limit=5
        ),
        "method_overview": normalize_section(
            draft_output.get("method_overview", {}), allow_empty=False
        ),
        "detailed_findings": normalize_section_list(
            draft_output.get("detailed_findings", []), limit=6
        ),
        "limitations": normalize_section_list(
            draft_output.get("limitations", []), limit=4
        ),
        "open_questions": normalize_section_list(
            draft_output.get("open_questions", []), limit=4
        ),
    }

    def all_sections() -> list[tuple[str, DraftSection]]:
        items: list[tuple[str, DraftSection]] = [
            ("big_picture", normalized["big_picture"]),
            ("method_overview", normalized["method_overview"]),
        ]
        for key in (
            "main_contributions",
            "main_results",
            "detailed_findings",
            "limitations",
            "open_questions",
        ):
            for index, item in enumerate(normalized[key], start=1):
                items.append((f"{key}[{index}]", item))
        return items

    def word_count(text: str) -> int:
        return len(re.findall(r"\b\w+\b", text))

    def normalized_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    sections = all_sections()
    nonempty_sections = [(name, section) for name, section in sections if section["text"]]
    text_to_section: dict[str, str] = {}
    chunk_usage: dict[str, list[str]] = {}

    if strict and not normalized["big_picture"]["text"]:
        raise ValueError("external draft output must include a non-empty big_picture")
    if strict and not normalized["main_contributions"]:
        raise ValueError("external draft output must include at least one main_contribution")
    if strict and not normalized["main_results"]:
        raise ValueError("external draft output must include at least one main_result")
    if strict and not normalized["method_overview"]["text"]:
        raise ValueError("external draft output must include a non-empty method_overview")
    if strict and not normalized["method_overview"]["chunk_ids"]:
        raise ValueError("external draft output must link method_overview to at least one supporting chunk_id")

    for name, section in nonempty_sections:
        text = section["text"]
        if strict and word_count(text) < 6:
            raise ValueError(f"{name} is too short to be useful")
        if strict and not section["chunk_ids"] and not name.startswith("open_questions"):
            raise ValueError(f"{name} must include at least one supporting chunk_id")

        normalized_body = normalized_text(text)
        previous = text_to_section.get(normalized_body)
        if previous:
            raise ValueError(f"{name} duplicates the text in {previous}")
        text_to_section[normalized_body] = name

        for chunk_id in section["chunk_ids"]:
            chunk_usage.setdefault(chunk_id, []).append(name)

    repeated_chunks = {
        chunk_id: users
        for chunk_id, users in chunk_usage.items()
        if len(users) >= 4
    }
    if strict and repeated_chunks:
        worst_chunk, users = max(repeated_chunks.items(), key=lambda item: len(item[1]))
        raise ValueError(
            f"chunk_id {worst_chunk} is reused too broadly across sections: {users}"
        )

    unique_chunk_ratio = len(chunk_usage) / allowed_chunk_id_count
    if strict and chunk_usage and unique_chunk_ratio < 0.1:
        raise ValueError("draft output uses too narrow a slice of the available evidence")

    return normalized


def persisted_chunk_id(source_id: str, chunk_id: str) -> str:
    return f"{source_id}_{chunk_id}"


def is_heading_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    word_count = len(stripped.split())
    return word_count <= 3 and stripped.lower() in {
        "6",
        "7",
        "8",
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
