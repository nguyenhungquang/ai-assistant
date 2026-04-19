# AGENTS

## Scope

This repository builds a local-first research vault for Obsidian.

## Rules

- Keep the project compact.
- Raw sources are immutable.
- Durable vault writes should stay evidence-backed.
- Use `uv` to manage Python dependencies and run scripts.

## Current runtime split

- Coordinator
- Ingest
- Retrieve
- Verifier

## First implementation slice

- local PDF ingest
- SQLite state initialization
- draft page creation
- basic lexical retrieval
- basic verification output
