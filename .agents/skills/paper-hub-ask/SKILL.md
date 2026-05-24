---
name: paper-hub-ask
description: Use whenever the user asks natural research-vault questions such as what the papers say about a topic, which papers argue or explain something, whether any paper explains a mechanism, find evidence for a claim, or ask the vault about an idea.
---

# Paper Hub Ask

Use this skill to answer natural-language questions from the vault's existing SQLite FTS paper chunk index. The search command is deterministic lexical retrieval; the agent must do the question-answering by reading the returned `chunk_text` fields. Search results may include internal metadata such as chunk IDs, but user-facing answers should use human-readable citations.

## Guardrails

- Use `uv run scripts/hub.py search "<keywords-or-phrase>" --top-k 10 --json`.
- Search only the extracted keyword set or phrase, not the full user question.
- Treat the command literally: it receives already-extracted keywords and does not interpret full questions.
- Read the returned full `chunk_text` for all top results, not only snippets or excerpts.
- Do not scan PDFs, raw HTML, raw source files, or Markdown pages at query time.
- Do not edit raw sources, wiki pages, or SQLite state. Asking is read-only.
- Keep `retrieve` for verifier and evidence workflows; use `search` for user-facing paper QA.

## Query Extraction

Read the user's natural-language question and extract the smallest useful keyword set.

Remove intent words and wrappers such as:

- `which papers`
- `what papers`
- `what do the papers say about`
- `does any paper explain`
- `does the vault say anything about`
- `find evidence for`
- `ask the vault about`
- `argue`
- `explain`
- `mention`
- `discuss`
- `find`
- `search`
- `tell me`

Preserve important technical phrases, including hyphenated terms:

- `reward hacking`
- `chain of thought`
- `gradient fingerprints`
- `probe-based penalties`
- `monitorability`

Examples:

- User: `what do the papers say about reward hacking`
  Search: `reward hacking`
- User: `which papers explain gradient fingerprints`
  Search: `gradient fingerprints`
- User: `does the vault say anything about probe-based penalties`
  Search: `probe-based penalties`
- User: `find evidence for chain of thought faithfulness`
  Search: `chain of thought faithfulness`

## Workflow

1. Extract the compact query.

2. Run:

   ```bash
   uv run scripts/hub.py search "<keywords-or-phrase>" --top-k 10 --json
   ```

3. If the first search returns no results, or if the returned chunks are only lexical matches that do not answer the question, retry once with a broader or alternate phrase before reporting that the vault does not answer the question.

   Examples:

   - `chain of thought faithfulness` -> `chain of thought`
   - `probe-based penalties` -> `probe penalties`
   - `gradient fingerprints method` -> `gradient fingerprints`

4. Read the returned `chunk_text` for every top result. Classify each relevant result as:

   - `answers`: the chunk directly answers the user's question.
   - `partial`: the chunk gives related evidence but leaves part of the question unanswered.
   - `lexical`: the chunk only matches words and should not be used as support.

5. Synthesize what the relevant chunks say and answer in prose. Always mention the exact search phrase used. If a retry was needed, mention both phrases.

6. Cite supporting evidence inline or in short bullets using only user-meaningful context:

   - `paper_title`
   - `page_path`
   - `section_path`

## Answering Rules

- Give a direct answer first when the matched chunks support one, then explain the supporting evidence in readable prose.
- Separate direct answers from partial evidence when both exist.
- If no chunk clearly answers the question after one retry, say that no clear answer was found in the vault.
- Do not claim more than the matched `chunk_text` supports.
- Do not expose raw JSON, snippets, ranks, or internal IDs unless the user explicitly asks for raw search output.
- Do not list matches without explaining what the evidence says.
- Prefer concise citations such as: `Detecting and Suppressing Reward Hacking with Gradient Fingerprints, wiki/papers/detecting-and-suppressing-reward-hacking-with-gradient-fingerprints.md, Method > Setup for Reward Hacking Detection`.
