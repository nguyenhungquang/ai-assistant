# Quickstart

## 1. Install dependencies

```bash
uv sync
```

## 2. Add a paper

```bash
uv run scripts/hub.py add-source 1706.03762v7 --json
```

This stages ingest, returns a bounded `draft_packet`, and prepares the final wiki page path.
This stages ingest and returns a prepared handoff for one drafting subagent.
For arXiv sources, HTML is required. If neither `arxiv.org/html` nor `ar5iv` is available, ingest stops.

## 3. Finalize and publish

```bash
uv run scripts/hub.py add-source 1706.03762v7 --draft-output-file <draft.json> --json
```

After a drafter returns structured JSON, rerun `add-source` with that draft file. The command writes the Markdown page and automatically attempts publish. If verification fails, the page remains `needs-review`.

For packets with extracted figures or equations, draft JSON must include `media_review` and either select important `figure_ids` / `equation_ids` in the relevant sections or provide `media_review.no_media_reason`. Use equation `math_id` values in `equation_ids`, not display labels such as `Equation 1`. Regenerate or amend older cached drafts before finalizing them.

## 4. Ask a question

```bash
uv run scripts/hub.py ask "attention" --json
```

## 5. Open the vault in Obsidian

Use the repository root as your Obsidian vault.
