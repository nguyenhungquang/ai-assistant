# Quickstart

## 1. Install dependencies

```bash
uv sync
```

## 2. Add a paper

```bash
uv run scripts/hub.py add-source 1706.03762v7 --json
```

This creates a draft page in `wiki/inbox/`.

## 3. Add and publish if safe

```bash
uv run scripts/hub.py add-source 1706.03762v7 --publish-if-pass --json
```

This verifies automatically and publishes only if verification returns `pass`.

## 4. Ask a question

```bash
uv run scripts/hub.py ask "attention" --json
```

## 5. Open the vault in Obsidian

Use the repository root as your Obsidian vault.
