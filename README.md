# Obsidian Research Vault Agent

Local-first research vault for Obsidian, designed to be operated through a coding CLI agent such as Codex or OpenCode.

It ingests papers and posts, stores raw sources immutably, builds Markdown pages for Obsidian, and keeps machine state in SQLite for retrieval, provenance, and workflow control.

## What it does

- ingest papers and posts into a local vault
- keep raw sources immutable in `raw/`
- create Markdown pages in `wiki/`
- maintain SQLite-backed retrieval and provenance state in `system/`
- support top-level user workflows for adding sources and asking questions

## Current scope

Implemented user-facing workflows:

- `add-source`
- `ask`
- `verify`
- `publish`

The current system is a working prototype with staged ingest, claim-aware retrieval, and direct-to-wiki page finalization.

## Requirements

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)

## Installation

```bash
uv sync
```

## Runtime config

On first run, the project creates `config.env` at the repo root with:

```bash
MODE=deploy
```

Supported values:

- `deploy`: the agent must use existing `scripts/` and `prompts/` without editing them
- `dev`: the agent may edit `scripts/` and `prompts/`

Inspect the current mode with:

```bash
uv run scripts/hub.py config --json
```

## Quick start

### Prepare an arXiv paper for drafting

```bash
uv run scripts/hub.py add-source 1706.03762v7 --json
```

This stages ingest and returns a bounded `draft_packet` plus a prepared JSON path for the coding agent to hand to one drafting subagent.
Only arXiv sources with parseable HTML are currently supported. The command uses `arxiv.org/html` first and falls back to `ar5iv`; if neither HTML source is available, ingest stops.

### Finalize and publish a staged draft

```bash
uv run scripts/hub.py add-source 1706.03762v7 --draft-output-file <draft.json> --json
```

When draft output is supplied, `add-source` finalizes the Markdown page and automatically attempts `publish`. `publish` runs verification internally. If verification fails, the page remains `needs-review` and the command returns warnings for manual review.

### Lower-level finalize only

```bash
uv run scripts/hub.py ingest-finalize system/cache/prepared-<source-id>.json --draft-output-file <draft.json>
```

`ingest-finalize` requires a structured draft from the external drafter and only writes the page as `needs-review`; it does not publish.

### Ask a question

```bash
uv run scripts/hub.py ask "attention" --json
```

### Verify a wiki page

```bash
uv run scripts/hub.py verify wiki/papers/paper-foo.md --json
```

### Mark a verified wiki page as published

```bash
uv run scripts/hub.py publish wiki/papers/paper-foo.md --json
```

## Repository layout

```text
raw/        immutable source files
wiki/       human-readable Markdown pages for Obsidian
system/     SQLite state, indexes, and logs
scripts/    workflow commands and internal helpers
docs/user/  user-facing documentation
```

## Public documentation

- `docs/user/quickstart.md`
- `docs/user/commands.md`
- `docs/user/workflows.md`
- `docs/user/github-release-checklist.md`

## Notes and current limitations

- Raw sources are immutable.
- Markdown pages are the human-facing artifact.
- `add-source` stages ingest and returns `needs-draft` unless you provide `--draft-output-file` or `--draft-output-stdin`.
- When draft output is supplied, `add-source` finalizes the page and attempts publish automatically.
- arXiv ingest is HTML-only. Local PDFs and PDF fallback are not supported.
- `ingest-finalize` requires external drafter output and writes the canonical wiki page directly into its target wiki folder with review status in frontmatter.
- Verification and synthesis are still improving; current verification is stronger than before but not yet deeply semantic.
- The repository supports external drafter handoff, but the top-level model orchestration remains the responsibility of the coding CLI agent.

## Development docs

Internal development/project-tracking docs live under `docs-internal/` and are intended for local development only. They are ignored by `.gitignore` and are not part of the release-facing documentation set.
