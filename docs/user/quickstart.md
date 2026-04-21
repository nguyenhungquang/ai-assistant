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
For arXiv sources, HTML is preferred. If HTML is unavailable, the command stops and requires explicit approval before PDF fallback; after approval, rerun with `--allow-pdf-fallback`.

## 3. Add and publish if safe

```bash
uv run scripts/hub.py add-source 1706.03762v7 --publish-if-pass --json
```

This verifies automatically and marks the final wiki page as published only if verification returns `pass`.

## 4. Ask a question

```bash
uv run scripts/hub.py ask "attention" --json
```

## 5. Open the vault in Obsidian

Use the repository root as your Obsidian vault.
