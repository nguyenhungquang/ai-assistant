# GitHub Release Checklist

Use this checklist before pushing or tagging a public release.

## Repository contents

- [ ] `README.md` reflects the current public workflows.
- [ ] `docs/user/` contains the user-facing docs you want to publish.
- [ ] Internal development docs under `docs-internal/` are ignored and not staged.
- [ ] Local runtime artifacts are not staged:
  - `system/state.db`
  - `system/cache/`
  - generated `raw/` files
  - generated `wiki/` files
- [ ] `.venv/`, caches, and editor state are ignored.

## Product behavior

- [ ] `add-source` works for a representative paper.
- [ ] `add-source --draft-output-file` finalizes and auto-publishes a passable draft.
- [ ] `ask` works for a known query.
- [ ] `ask` behaves cleanly for a no-match query.
- [ ] `verify` and `publish` behave as documented.

## Docs quality

- [ ] Quickstart commands are correct.
- [ ] Command reference matches the current CLI.
- [ ] Workflow docs match actual behavior.
- [ ] Known limitations are described honestly.

## Packaging / release readiness

- [ ] `pyproject.toml` version is correct.
- [ ] dependency installation via `uv sync` works from a clean checkout.
- [ ] repository root works as an Obsidian vault.
- [ ] release notes / changelog summary is prepared if needed.

## Final pre-push check

- [ ] run through one end-to-end add-source example
- [ ] run through one end-to-end ask example
- [ ] inspect `git status` and confirm only intended files are staged
