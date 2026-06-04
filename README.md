# Obsidian Research Vault Agent

A local-first research vault for Obsidian, operated through agent skills.

This project helps you build an evidence-backed paper vault without managing the
workflow by hand. You ask an agent to add papers, ask questions, or create
literature reviews. The agent uses the repository's skills and deterministic
commands to write Markdown pages, preserve raw sources, update SQLite state, and
verify support from the source material.

## What You Can Do

- Add supported papers to an Obsidian-ready vault.
- Ask natural-language questions about papers already in the vault.
- Create evidence-backed literature review pages.
- Keep raw source files immutable.
- Keep durable wiki pages grounded in retrieved evidence.

## How You Use It

Most users should talk to an agent from the repository root. The public interface
is the agent skill layer, not the lower-level command line.

Example requests:

```text
Add arXiv 1706.03762v7 to the vault.
```

```text
What do the papers say about reward hacking?
```

```text
Create a literature review for faithful chain-of-thought.
```

```text
Add this paper to the Faithful CoT topic: https://arxiv.org/abs/1706.03762
```

The agent will choose the right skill, run the repository commands it needs, and
report the final page path, verification status, or search evidence.

## Agent Skills

The user-facing workflows are defined as local agent skills:

- `paper-hub-add-source`: add, ingest, draft, verify, publish, or associate a
  supported source with an existing topic.
- `paper-hub-ask`: answer questions from the vault's existing paper index.
- `paper-hub-literature-review`: create Markdown review pages for primary
  research papers related to a topic or seed paper.

These skills are the intended way to use the project. They enforce the project
guardrails: raw sources stay immutable, wiki writes stay evidence-backed, and
SQLite state is updated through repository commands rather than by hand.

## Setup

Requirements:

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv)
- Obsidian, if you want to browse the generated vault visually

Install dependencies:

```bash
uv sync
```

Then open this repository root as an Obsidian vault.

## Current Support

The main add-source workflow currently supports:

- arXiv IDs, such as `1706.03762v7`
- arXiv URLs
- ar5iv URLs

For arXiv sources, HTML must be available from `arxiv.org/html` or `ar5iv`.
If HTML is unavailable, ingest stops. Local PDF ingest and PDF fallback are not
currently supported.

## What Gets Written

```text
raw/       immutable source files and extracted assets
wiki/      human-readable Markdown pages for Obsidian
system/    SQLite state, indexes, cache, and logs
scripts/   deterministic workflow commands used by skills
docs/user/ additional user-facing documentation
```

Markdown pages in `wiki/` are the main human-facing artifact. SQLite state under
`system/` supports retrieval, provenance, and workflow control.

## For Agents And Debugging

The skills use `uv run scripts/hub.py` as the deterministic command surface.
Most users should not need to run these commands directly.

Useful examples when debugging:

```bash
uv run scripts/hub.py add-source 1706.03762v7 --json
```

```bash
uv run scripts/hub.py search "reward hacking" --top-k 10 --json
```

```bash
uv run scripts/hub.py verify wiki/papers/paper-foo.md --json
```

```bash
uv run scripts/hub.py publish wiki/papers/paper-foo.md --json
```

Lower-level ingest and drafting commands exist for advanced orchestration, but
normal user requests should go through the skills.

## Runtime Config

On first run, the project creates `config.env` at the repo root with:

```bash
MODE=deploy
```

Supported values:

- `deploy`: agents must use existing `scripts/` and `prompts/` without editing
  them
- `dev`: agents may edit `scripts/` and `prompts/`

Inspect the current mode with:

```bash
uv run scripts/hub.py config --json
```

## Documentation

- `docs/user/quickstart.md`
- `docs/user/commands.md`
- `docs/user/workflows.md`
- `docs/user/github-release-checklist.md`

Internal development notes live under `docs-internal/` when present. They are
ignored by `.gitignore` and are not part of the release-facing documentation set.
