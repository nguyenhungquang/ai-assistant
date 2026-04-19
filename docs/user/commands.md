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

### `ask`

Ask a question against the current vault.

```bash
uv run scripts/hub.py ask "<query>" [--json]
```

### `verify`

Verify a draft page.

```bash
uv run scripts/hub.py verify <page-path> [--json]
```

### `publish`

Publish a verified inbox page.

```bash
uv run scripts/hub.py publish <page-path> [--json]
```

## Lower-level commands

These are mainly useful for debugging and advanced orchestration:

- `ingest`
- `ingest-prepare`
- `ingest-finalize`
- `retrieve`

Most users should prefer `add-source` and `ask`.
