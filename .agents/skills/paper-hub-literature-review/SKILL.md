---
name: paper-hub-literature-review
description: Use whenever the user asks to find related papers, review papers around a seed paper, create a literature review, or identify primary research papers connected to a topic or paper.
---

# Literature Review

Use this skill to create evidence-backed Markdown literature review pages in the local-first Obsidian research vault. A literature review page lists primary research papers with a concrete scholarly relationship to a seed paper or topic.

## Scope

This skill writes review pages only:

- Create pages under `wiki/reviews/`.
- Do not update `index.md`.
- Do not add discovered papers to `wiki/papers/`.
- Do not ingest, stage, draft, verify, publish, or update SQLite state for discovered papers.
- If the user asks to save, add, ingest, or publish one of the discovered papers, switch to the `paper-hub-add-source` skill for that separate request.

Review creation is a durable vault write. Every listed paper must have public-source evidence for the paper metadata and the relationship claim.

## Request Classification

Classify the request before searching:

- `topic review`: primary papers related to a topic.
- `seed-paper review`: primary papers related to a specific seed paper.

Use a `seed-paper review` when the user provides a paper title, DOI, arXiv ID, URL, or an existing `wiki/papers/*.md` page. Use a `topic review` when the user asks around a concept, method family, benchmark, dataset, phenomenon, or research question.

## Search Sources

Search public scholarly sources using stable APIs and official pages where practical:

- arXiv
- Semantic Scholar
- OpenAlex
- Crossref
- conference and proceedings pages
- publisher, lab, project, benchmark, dataset, or author pages when they provide stable metadata or relationship evidence

Do not use Google Scholar as the default workflow.

For seed-paper reviews, search for citation and relationship evidence:

- papers that cite the seed
- papers cited by the seed
- follow-up papers by the same or adjacent authors
- papers sharing the same method, benchmark, dataset, or experimental protocol
- critique, replication, or limitation papers

For topic reviews, search for core papers, benchmark papers, method papers, applications, and critique or limitation papers directly tied to the topic.

## Candidate Collection

For each candidate, record enough evidence to support inclusion:

- title
- authors when available
- published date or year
- public URL
- DOI, arXiv ID, OpenReview ID, proceedings URL, or other stable identifier when available
- source used for metadata
- concrete relationship evidence

Reject candidates that are only keyword matches. A paper must have a concrete scholarly relationship to the seed or topic, not merely overlapping words in the title or abstract.

## Deduplication

Deduplicate candidates before ranking. Merge duplicate records by:

- DOI
- arXiv ID
- OpenReview ID
- normalized title
- author/year match

When arXiv, conference, OpenReview, and publisher versions refer to the same paper, keep one row. Prefer the most stable public full-text or official version URL, then proceedings URL, then arXiv URL.

## Exclusions

Exclude survey-like and background-only papers by default, unless the user explicitly asks for background material:

- survey
- review
- overview
- tutorial
- primer
- perspective
- position
- roadmap
- systematic literature review

Use title and abstract cues for filtering. If a paper is ambiguous, include it only when it is clearly primary research with original experiments, methods, datasets, theory, or empirical analysis.

## Relationship Labels

Assign at least one relationship label before including a paper. The final table must explain the relationship in prose; do not show only the label.

For `seed-paper review`, allowed labels are:

- `cites-seed`
- `cited-by-seed`
- `same-method`
- `same-benchmark`
- `same-dataset`
- `follow-up`
- `critique-or-replication`

For `topic review`, allowed labels are:

- `core-topic`
- `foundational`
- `same-method-family`
- `same-benchmark`
- `application`
- `critique-or-limitation`

Reject a candidate if no allowed relationship label can be justified from public evidence.

## Ranking

Sort included papers by importance using:

- relationship strength to the seed or topic
- centrality to the research question
- citation or venue signal when available
- recency when the topic is fast-moving or the user asks for recent papers
- public full-text availability

Do not rank survey, overview, tutorial, or position papers above primary research because they should be excluded by default.

## Review Page Path

Create one Markdown page under `wiki/reviews/`.

Build the slug from the seed paper title or topic:

- lowercase
- ASCII where practical
- replace spaces and punctuation with hyphens
- collapse repeated hyphens
- trim leading and trailing hyphens

Example paths:

- `wiki/reviews/faithful-chain-of-thought.md`
- `wiki/reviews/detecting-and-suppressing-reward-hacking-with-gradient-fingerprints.md`

If a page already exists, update it only when the user asked to refresh or revise that review. Otherwise, choose a clear non-conflicting slug or ask before overwriting.

## Page Format

Start each page with this structure:

```markdown
# Literature Review: <Topic or Seed Paper>

This review lists primary research papers related to <topic or seed paper>. Survey and overview papers are excluded by default.
```

Then include a ranked table:

```markdown
| Rank | Title | Published date | Relation to seed/topic |
|---:|---|---|---|
| 1 | [Paper Title](https://...) | 2024-05-12 | Cites the seed paper and evaluates the same benchmark. |
```

Table rules:

- Use one row per deduplicated included paper.
- Link each title to the selected public URL.
- Use the most specific published date available; otherwise use the year.
- Explain the concrete relationship in prose in `Relation to seed/topic`.
- Keep relation prose concise but specific enough to justify inclusion.
- Do not include papers with broad keyword overlap only.

Optional sections may follow the table when useful:

- `## Search Notes`
- `## Excluded Papers`
- `## Open Questions`

If using `## Excluded Papers`, briefly state why each important excluded paper was omitted, such as survey-like format, duplicate version, or keyword-only match.

## Verification Checklist

Before reporting completion, verify:

- `wiki/reviews/<slug>.md` exists.
- The page starts with the required description.
- The page contains a ranked Markdown table.
- Every included row is a primary research paper.
- Survey, review, overview, tutorial, position, primer, roadmap, and systematic literature review papers are excluded unless explicitly requested.
- Every included row has concrete relationship prose.
- Duplicate arXiv, conference, OpenReview, and publisher versions are merged.
- `index.md` is unchanged.
- No discovered paper was ingested into `wiki/papers/`.
- SQLite state was not manually updated.

## Smoke Prompts

This skill should handle requests like:

- "Find related papers around arXiv 1706.03762."
- "Create a literature review for faithful chain-of-thought."
- "Review papers related to this seed paper but skip surveys."
- "Find primary research papers connected to reward hacking monitors."
- "Make a review page for papers that cite this benchmark paper."
