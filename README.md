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

The current system is a working prototype with staged ingest, claim-aware retrieval, and inbox-to-publish workflow support.

## Requirements

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)

## Installation

```bash
uv sync
```

## Quick start

### Add a paper as draft

```bash
uv run scripts/hub.py add-source 1706.03762v7 --json
```

### Add a paper and publish if verification passes

```bash
uv run scripts/hub.py add-source 1706.03762v7 --publish-if-pass --json
```

### Ask a question

```bash
uv run scripts/hub.py ask "attention" --json
```

### Verify a draft page

```bash
uv run scripts/hub.py verify wiki/inbox/paper-foo.md --json
```

### Publish a verified inbox page

```bash
uv run scripts/hub.py publish wiki/inbox/paper-foo.md --json
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
- Drafts normally land in `wiki/inbox/` unless you use `--publish-if-pass` and verification succeeds.
- Verification and synthesis are still improving; current verification is stronger than before but not yet deeply semantic.
- The repository supports external drafter handoff, but the top-level model orchestration remains the responsibility of the coding CLI agent.

## Development docs

Internal development/project-tracking docs live under `docs-internal/` and are intended for local development only. They are ignored by `.gitignore` and are not part of the release-facing documentation set.
