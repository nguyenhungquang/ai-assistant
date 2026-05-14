# Commands

## Top-level workflows

### `add-source`

Add an arXiv paper to the wiki.

```bash
uv run scripts/hub.py add-source <source> [--draft-output-file <draft.json>] [--draft-output-stdin] [--json]
```

Supported source examples:

- arXiv ID
- arXiv URL
- ar5iv URL

The command requires HTML from `arxiv.org/html` or `ar5iv`. If HTML is unavailable, ingest stops.

Without draft output, the command stages ingest and returns a draft packet. With draft output, it finalizes the Markdown page and automatically attempts publish. If publish verification fails, the page remains `needs-review`.

When the staged packet includes extracted figures or equations, the draft output must include `media_review`. Select important `figure_ids` / `equation_ids` in the sections that explain them, or set `media_review.no_media_reason` if no extracted media should be included. Older cached draft JSON without `media_review` must be regenerated or amended before finalization.

### `ask`

Ask a question against the current vault.

```bash
uv run scripts/hub.py ask "<query>" [--json]
```

### `verify`

Verify a wiki page.

```bash
uv run scripts/hub.py verify <page-path> [--json]
```

### `publish`

Mark a verified wiki page as published.

```bash
uv run scripts/hub.py publish <page-path> [--json]
```

## Lower-level commands

These are mainly useful for debugging and advanced orchestration:

- `ingest-prepare`
- `ingest-finalize`
- `draft-handoff`
- `retrieve`

Most users should prefer `add-source` and `ask`.
