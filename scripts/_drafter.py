from __future__ import annotations

import re
from typing import NotRequired, TypedDict


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
    full_paper_text: str
    drafting_rules: list[str]
    draft_template: str
    candidate_groups: dict
    section_blocks: dict
    chunks: list[DraftChunk]
    figures: NotRequired[list[dict]]
    equations: NotRequired[list[dict]]


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
    figure_ids: NotRequired[list[str]]
    equation_ids: NotRequired[list[str]]


class DraftEntry(TypedDict):
    title: str
    text: str
    chunk_ids: list[str]
    figure_ids: NotRequired[list[str]]
    equation_ids: NotRequired[list[str]]


class DraftMediaReview(TypedDict):
    figures_reviewed: bool
    equations_reviewed: bool
    no_media_reason: str


class DraftOutput(TypedDict):
    media_review: NotRequired[DraftMediaReview]
    big_picture: DraftSection
    problem_setting: DraftSection
    core_claims: list[DraftEntry]
    method_overview: DraftSection
    method_details: list[DraftEntry]
    data_or_inputs: list[DraftEntry]
    experimental_setup: list[DraftEntry]
    results: list[DraftEntry]
    analysis: list[DraftEntry]
    limitations: list[DraftEntry]
    open_questions: list[DraftEntry]


SECTION_PRIORITY_KEYWORDS = [
    (("abstract", "summary"), 0),
    (("introduction", "overview"), 1),
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
        2,
    ),
    (("results", "findings", "evaluation", "experiment"), 3),
    (("conclusion", "conclusions"), 4),
    (("discussion",), 5),
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
METHOD_OVERVIEW_CUES = [
    "we propose",
    "we present",
    "in this work",
    "our approach",
    "our method",
    "framework",
    "architecture",
    "algorithm",
    "pipeline",
    "system",
    "consists of",
    "is based on",
]
METHOD_DETAIL_CUES = [
    "training",
    "optimizer",
    "regularization",
    "hyperparameter",
    "learning rate",
    "batch",
    "dataset",
    "evaluation",
    "baseline",
    "implementation",
]
METHOD_OVERVIEW_EXCLUSION_CUES = [
    "table ",
    "development set",
    "beam search",
    "checkpoint averaging",
    "newstest",
    "bleu",
    "state-of-the-art",
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
EQUATION_CUES = [
    "softmax",
    "argmax",
    "attention(",
    "ffn(",
    "loss",
    "objective",
    "probability",
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
    full_paper_text: str,
    chunks: list[DraftChunk],
    section_blocks: dict | None = None,
) -> DraftPacket:
    ranked_chunks = [
        chunk
        for chunk in sorted(chunks, key=chunk_rank)
        if not is_heading_only(chunk["chunk_text"])
        and not is_noise_chunk(chunk)
        and not is_reference_like(chunk)
    ]

    selected = ranked_chunks
    packet_chunks = [
        {
            **chunk,
            "chunk_id": persisted_chunk_id(source_id, chunk["chunk_id"]),
        }
        for chunk in selected
    ]
    big_picture_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(
            chunk, {"abstract", "introduction", "conclusion"}
        ),
        limit=4,
        role="big_picture",
    )
    contribution_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(
            chunk, {"abstract", "introduction", "conclusion"}
        )
        or text_matches(chunk, CONTRIBUTION_CUES),
        limit=5,
        role="contribution",
    )
    result_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: (
            has_section_ancestry(chunk, {"results", "discussion", "conclusion"})
            and supports_result_role(chunk)
        ),
        limit=5,
        role="result",
    )
    method_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(chunk, {"method"})
        and text_matches(chunk, METHOD_CUES),
        limit=4,
        role="method",
    )
    method_overview_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: is_method_overview_like(chunk),
        limit=4,
        role="method_overview",
    )
    method_equation_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(chunk, {"method"})
        and text_matches(chunk, METHOD_CUES)
        and is_equation_heavy(chunk),
        limit=4,
        role="method_equation",
    )
    technical_method_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(chunk, {"method"})
        and text_matches(chunk, METHOD_CUES),
        limit=6,
        role="method",
    )
    detail_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: (
            (
                has_section_ancestry(chunk, {"results", "discussion"})
                and is_result_like(chunk)
                and supports_result_role(chunk)
            )
            or (has_section_ancestry(chunk, {"method"}) and text_matches(chunk, DETAIL_CUES))
        ),
        limit=6,
        role="detail",
    )
    limitation_chunks = pick_chunks(
        packet_chunks,
        predicate=lambda chunk: has_section_ancestry(
            chunk, {"limitations", "discussion", "conclusion"}
        )
        or text_matches(chunk, LIMITATION_CUES),
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
    method_overview_candidates = pick_candidate_spans(
        method_overview_chunks,
        predicate=lambda _chunk: True,
        limit=4,
        role="method_overview",
        top_chunk_limit=4,
    )
    method_equation_candidates = pick_candidate_spans(
        method_equation_chunks,
        predicate=lambda _chunk: True,
        limit=4,
        role="method_equation",
        top_chunk_limit=4,
    )
    technical_method_candidates = pick_candidate_spans(
        technical_method_chunks,
        predicate=lambda _chunk: True,
        limit=6,
        role="method",
        top_chunk_limit=6,
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

    def compact_section_blocks() -> dict:
        if not section_blocks:
            return {}
        compact: dict[str, list[dict[str, str]]] = {}
        for role, blocks in section_blocks.items():
            trimmed: list[dict[str, str]] = []
            for block in blocks[:3]:
                text = re.sub(r"\s+", " ", (block.get("text") or "").strip())
                if not text:
                    continue
                trimmed.append(
                    {
                        "section_path": block.get("section_path") or role,
                        "text": text[:4000],
                    }
                )
            if trimmed:
                compact[role] = trimmed
        return compact

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
        "full_paper_text": full_paper_text,
        "drafting_rules": [
            "Write for a human reader using a top-down structure.",
            "Read the full paper text before drafting; do not rely only on the candidate groups.",
            "Start with high-level ideas before low-level details.",
            "Do not invent facts or use evidence outside this packet.",
            "Use only packet chunk IDs for evidence linkage.",
            "Prefer plain-English synthesis over copied source text when possible.",
            "Method Overview must explain how the paper works using method evidence, not result evidence.",
            "Use equations to clarify the method only when they are central; explain them in plain language instead of turning Method Overview into a derivation dump.",
            "If the source contains equations or formal expressions, render them using Obsidian-compatible math syntax with $...$ or $$...$$.",
            "Review all available figures and equations before drafting.",
            "Use figure_ids and equation_ids only for important media; place selected media in the section that explains it.",
            "If extracted figures or equations are available but none are useful enough to include, set media_review.no_media_reason.",
            "Do not attach every extracted figure or equation to the draft.",
        ],
        "draft_template": (
            "Write a generalized technical reference page with: big_picture, "
            "problem_setting, core_claims, method_overview, method_details, "
            "data_or_inputs, experimental_setup, results, analysis, limitations, "
            "open_questions. Use only packet chunk IDs as evidence."
        ),
        "candidate_groups": {
            "big_picture_candidates": bundle_candidates(big_picture_candidates),
            "main_contribution_candidates": bundle_candidates(contribution_candidates),
            "main_result_candidates": bundle_candidates(result_candidates),
            "method_overview_candidates": bundle_candidates(method_overview_candidates),
            "method_equation_candidates": bundle_candidates(method_equation_candidates),
            "method_candidates": bundle_candidates(method_candidates),
            "technical_method_candidates": bundle_candidates(technical_method_candidates),
            "detailed_finding_candidates": bundle_candidates(detail_candidates),
            "limitation_candidates": bundle_candidates(limitation_candidates),
        },
        "section_blocks": compact_section_blocks(),
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


def section_parts(chunk: DraftChunk) -> list[str]:
    section_path = (chunk.get("section_path") or "").lower()
    return [part.strip() for part in section_path.split(" > ") if part.strip()]


def primary_section_role(chunk: DraftChunk) -> str | None:
    parts = section_parts(chunk)
    return parts[0] if parts else None


def has_section_ancestry(chunk: DraftChunk, roles: set[str]) -> bool:
    return primary_section_role(chunk) in roles


def rhetorical_function(chunk: DraftChunk) -> str:
    primary = primary_section_role(chunk)
    if primary in {"method", "results", "limitations", "discussion", "conclusion", "background", "introduction", "abstract"}:
        return primary
    if text_matches(chunk, LIMITATION_CUES):
        return "limitations"
    if is_result_like(chunk):
        return "results"
    if text_matches(chunk, METHOD_CUES):
        return "method"
    if text_matches(chunk, CONTRIBUTION_CUES):
        return "introduction"
    return "body"


def text_matches(chunk: DraftChunk, cues: list[str]) -> bool:
    text = chunk["chunk_text"].lower()
    return any(cue in text for cue in cues)


def candidate_signals(chunk: DraftChunk) -> list[str]:
    signals: list[str] = []
    section_path = (chunk.get("section_path") or "").lower()
    if section_path:
        signals.append(f"section:{section_path}")
    signals.append(f"rhetoric:{rhetorical_function(chunk)}")
    if text_matches(chunk, CONTRIBUTION_CUES):
        signals.append("cue:contribution")
    if text_matches(chunk, METHOD_CUES):
        signals.append("cue:method")
    if text_matches(chunk, METHOD_OVERVIEW_CUES):
        signals.append("cue:method-overview")
    if is_equation_heavy(chunk) or text_matches(chunk, EQUATION_CUES):
        signals.append("cue:equation")
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


def is_equation_heavy(chunk: DraftChunk) -> bool:
    text = chunk["chunk_text"]
    return len(re.findall(r"(?:=|\\|√|∈|∑|β|ϵ|α|λ|\bO\()", text)) >= 4


def is_method_overview_like(chunk: DraftChunk) -> bool:
    if has_section_ancestry(chunk, {"results", "discussion", "limitations", "conclusion"}):
        return False
    section = (chunk.get("section_path") or "").lower()
    if has_section_ancestry(chunk, {"method"}) or any(
        label in section for label in {"method", "approach", "framework", "architecture"}
    ):
        if text_matches(chunk, METHOD_OVERVIEW_CUES):
            return True
        if (
            not text_matches(chunk, METHOD_DETAIL_CUES)
            and not is_equation_heavy(chunk)
            and not is_result_like(chunk)
        ):
            return True
    return (
        has_section_ancestry(chunk, {"abstract", "introduction"})
        and text_matches(
            chunk,
            ["we propose", "we present", "in this work", "our approach", "our method"],
        )
        and not is_equation_heavy(chunk)
        and not is_result_like(chunk)
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
        has_section_ancestry(chunk, {"results", "discussion", "conclusion"})
        or any(label in section for label in RESULT_SECTION_CUES)
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
    elif role == "method_overview":
        if any(cue in lowered for cue in METHOD_OVERVIEW_CUES):
            score += 6
        if any(cue in lowered for cue in METHOD_DETAIL_CUES):
            score -= 2
        if any(cue in lowered for cue in RESULT_CUES):
            score -= 2
        if any(cue in lowered for cue in METHOD_OVERVIEW_EXCLUSION_CUES):
            score -= 6
    elif role == "method_equation":
        if any(cue in lowered for cue in EQUATION_CUES):
            score += 4
        if re.search(r"(?:=|\\|√|∈|∑|β|ϵ|α|λ|\bO\()", sentence):
            score += 4
        if any(cue in lowered for cue in RESULT_CUES):
            score -= 2
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
    elif role == "method_overview":
        score += section_score(chunk, {"method", "approach", "architecture", "framework"})
        if text_matches(chunk, METHOD_OVERVIEW_CUES):
            score += 5
        if text_matches(chunk, METHOD_DETAIL_CUES):
            score -= 2
        if is_result_like(chunk):
            score -= 3
        if is_equation_heavy(chunk):
            score -= 4
        if text_matches(chunk, METHOD_OVERVIEW_EXCLUSION_CUES):
            score -= 8
    elif role == "method_equation":
        score += section_score(chunk, {"method", "approach", "architecture", "framework"})
        if is_equation_heavy(chunk):
            score += 6
        if text_matches(chunk, EQUATION_CUES):
            score += 3
        if is_result_like(chunk):
            score -= 3
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


def run_drafter(
    packet: DraftPacket,
    *,
    draft_output: DraftOutput | None = None,
) -> DraftOutput:
    if draft_output is not None:
        return validate_draft_output(packet, draft_output, strict=True)
    raise ValueError("draft output is required; heuristic drafting has been removed")


def validate_draft_output(
    packet: DraftPacket, draft_output: DraftOutput, *, strict: bool = False
) -> DraftOutput:
    allowed_chunk_ids = {chunk["chunk_id"] for chunk in packet["chunks"]}
    chunk_lookup = {chunk["chunk_id"]: chunk for chunk in packet["chunks"]}
    allowed_figure_ids: set[str] = set()
    for figure in packet.get("figures", []):
        for key in ("figure_id", "label"):
            value = figure.get(key)
            if isinstance(value, str) and value.strip():
                allowed_figure_ids.add(value.strip())
    allowed_equation_ids: set[str] = set()
    for equation in packet.get("equations", []):
        value = equation.get("math_id")
        if isinstance(value, str) and value.strip():
            allowed_equation_ids.add(value.strip())
    has_figures = bool(packet.get("figures", []))
    has_equations = bool(packet.get("equations", []))
    has_media = has_figures or has_equations

    def normalize_media_ids(
        section: dict,
        *,
        field_name: str,
        allowed_ids: set[str],
        media_name: str,
    ) -> list[str]:
        values = section.get(field_name, [])
        if values is None:
            return []
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise ValueError(f"draft section {field_name} must be a list of strings")
        normalized_values = [item.strip() for item in values if item.strip()]
        invalid_ids = [item for item in normalized_values if item not in allowed_ids]
        if invalid_ids:
            raise ValueError(f"unknown {media_name} ids in draft output: {invalid_ids}")
        return normalized_values

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
        return {
            "text": text.strip(),
            "chunk_ids": chunk_ids,
            "figure_ids": normalize_media_ids(
                section,
                field_name="figure_ids",
                allowed_ids=allowed_figure_ids,
                media_name="figure",
            ),
            "equation_ids": normalize_media_ids(
                section,
                field_name="equation_ids",
                allowed_ids=allowed_equation_ids,
                media_name="equation",
            ),
        }

    def normalize_entry(entry: object) -> DraftEntry:
        if not isinstance(entry, dict):
            raise ValueError("draft entry must be an object")
        title = entry.get("title", "")
        if not isinstance(title, str):
            raise ValueError("draft entry title must be a string")
        normalized_section = normalize_section(entry)
        return {
            "title": title.strip(),
            "text": normalized_section["text"],
            "chunk_ids": normalized_section["chunk_ids"],
            "figure_ids": normalized_section["figure_ids"],
            "equation_ids": normalized_section["equation_ids"],
        }

    def normalize_section_list(items: object, *, limit: int) -> list[DraftEntry]:
        if not isinstance(items, list):
            raise ValueError("draft section list must be a list")
        if strict and any(not isinstance(item, dict) for item in items):
            raise ValueError("all draft list entries must be objects")
        return [
            normalize_entry(item)
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    if not isinstance(draft_output, dict):
        raise ValueError("draft output must be an object")

    media_review = draft_output.get("media_review")
    normalized_media_review: DraftMediaReview = {
        "figures_reviewed": False,
        "equations_reviewed": False,
        "no_media_reason": "",
    }
    if media_review is not None:
        if not isinstance(media_review, dict):
            raise ValueError("draft output media_review must be an object")
        figures_reviewed = media_review.get("figures_reviewed", False)
        equations_reviewed = media_review.get("equations_reviewed", False)
        no_media_reason = media_review.get("no_media_reason", "")
        if not isinstance(figures_reviewed, bool):
            raise ValueError("media_review.figures_reviewed must be a boolean")
        if not isinstance(equations_reviewed, bool):
            raise ValueError("media_review.equations_reviewed must be a boolean")
        if not isinstance(no_media_reason, str):
            raise ValueError("media_review.no_media_reason must be a string")
        normalized_media_review = {
            "figures_reviewed": figures_reviewed,
            "equations_reviewed": equations_reviewed,
            "no_media_reason": no_media_reason.strip(),
        }

    normalized = {
        "media_review": normalized_media_review,
        "big_picture": normalize_section(
            draft_output.get("big_picture", {}), allow_empty=True
        ),
        "problem_setting": normalize_section(
            draft_output.get("problem_setting", {}), allow_empty=True
        ),
        "core_claims": normalize_section_list(
            draft_output.get("core_claims", []), limit=10
        ),
        "method_overview": normalize_section(
            draft_output.get("method_overview", {}), allow_empty=False
        ),
        "method_details": normalize_section_list(
            draft_output.get("method_details", []), limit=16
        ),
        "data_or_inputs": normalize_section_list(
            draft_output.get("data_or_inputs", []), limit=12
        ),
        "experimental_setup": normalize_section_list(
            draft_output.get("experimental_setup", []), limit=12
        ),
        "results": normalize_section_list(
            draft_output.get("results", []), limit=16
        ),
        "analysis": normalize_section_list(
            draft_output.get("analysis", []), limit=16
        ),
        "limitations": normalize_section_list(
            draft_output.get("limitations", []), limit=8
        ),
        "open_questions": normalize_section_list(
            draft_output.get("open_questions", []), limit=8
        ),
    }

    def all_sections() -> list[tuple[str, DraftSection | DraftEntry]]:
        items: list[tuple[str, DraftSection | DraftEntry]] = [
            ("big_picture", normalized["big_picture"]),
            ("problem_setting", normalized["problem_setting"]),
            ("method_overview", normalized["method_overview"]),
        ]
        for key in (
            "core_claims",
            "method_details",
            "data_or_inputs",
            "experimental_setup",
            "results",
            "analysis",
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
    selected_figure_ids = [
        figure_id
        for _, section in sections
        for figure_id in section.get("figure_ids", [])
    ]
    selected_equation_ids = [
        equation_id
        for _, section in sections
        for equation_id in section.get("equation_ids", [])
    ]

    if strict and not normalized["big_picture"]["text"]:
        raise ValueError("external draft output must include a non-empty big_picture")
    if strict and not normalized["core_claims"]:
        raise ValueError("external draft output must include at least one core_claim")
    if strict and not normalized["method_overview"]["text"]:
        raise ValueError("external draft output must include a non-empty method_overview")
    if strict and not normalized["method_overview"]["chunk_ids"]:
        raise ValueError("external draft output must link method_overview to at least one supporting chunk_id")
    if strict and word_count(normalized["method_overview"]["text"]) < 12:
        raise ValueError("method_overview is too short to explain how the paper works")
    if strict and not normalized["method_details"]:
        raise ValueError("external draft output must include method_details")
    if strict and not normalized["results"]:
        raise ValueError("external draft output must include results")
    if strict and has_media:
        if media_review is None:
            raise ValueError(
                "external draft output must include media_review when the packet contains figures or equations"
            )
        if has_figures and not normalized_media_review["figures_reviewed"]:
            raise ValueError(
                "media_review.figures_reviewed must be true when figures are available"
            )
        if has_equations and not normalized_media_review["equations_reviewed"]:
            raise ValueError(
                "media_review.equations_reviewed must be true when equations are available"
            )
        if (
            not selected_figure_ids
            and not selected_equation_ids
            and not normalized_media_review["no_media_reason"]
        ):
            raise ValueError(
                "draft output selected no media despite available figures or equations; select important figure_ids/equation_ids or set media_review.no_media_reason"
            )

    for name, section in nonempty_sections:
        if "title" in section and strict and not section["title"]:
            raise ValueError(f"{name} must include a non-empty title")
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

    min_distinct_chunks = min(4, max(1, len(nonempty_sections)))
    if strict and chunk_usage and len(chunk_usage) < min_distinct_chunks:
        raise ValueError(
            "draft output uses too few distinct supporting chunks for the filled sections"
        )

    if strict:
        method_text = normalized["method_overview"]["text"]
        method_chunks = [
            chunk_lookup[chunk_id]
            for chunk_id in normalized["method_overview"]["chunk_ids"]
            if chunk_id in chunk_lookup
        ]
        if method_chunks:
            if all(is_result_like(chunk) for chunk in method_chunks):
                raise ValueError(
                    "method_overview relies on result-oriented evidence instead of method evidence"
                )
            if all(is_equation_heavy(chunk) for chunk in method_chunks):
                raise ValueError(
                    "method_overview relies too heavily on equation-like chunks; use explanatory method text instead"
                )
        if text_matches({"chunk_text": method_text}, METHOD_DETAIL_CUES) and not text_matches(
            {"chunk_text": method_text}, METHOD_OVERVIEW_CUES
        ):
            raise ValueError(
                "method_overview focuses on narrow technical details instead of explaining the overall approach"
            )
        if len(normalized["results"]) + len(normalized["analysis"]) < 2:
            raise ValueError(
                "draft output must include more result or analysis coverage for a durable reference page"
            )

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
