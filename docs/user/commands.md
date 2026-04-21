# Commands

## Top-level workflows

### `add-source`

Add a paper or post to the wiki.

```bash
uv run scripts/hub.py add-source <source> [--publish-if-pass] [--verify] [--json]
```

Supported source examples:

- local PDF path
- arXiv ID
- arXiv URL
- article/post URL

For arXiv sources, the command prefers HTML from `arxiv.org/html` or `ar5iv`. If HTML is unavailable, it stops and asks for explicit approval before PDF fallback. After approval, rerun with `--allow-pdf-fallback`.

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
