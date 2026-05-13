# Workflows

## Add source

User intent:

- "add this paper to the wiki"

Default behavior:

- stage source
- return a bounded draft handoff packet for the coding agent
- finalize and attempt publish automatically when draft output is supplied
- require arXiv HTML from `arxiv.org/html` or `ar5iv`

Coordinator behavior:

1. run `add-source <source>` or `ingest-prepare <source>`
2. hand `result.draft_packet` to one bounded drafting subagent
3. call `add-source <source> --draft-output-file <draft.json>`
4. `add-source` writes the Markdown page and calls `publish`
5. if publish verification fails, keep the page as `needs-review` and report warnings

If HTML is unavailable for an arXiv source:

1. stop ingest
2. tell the user the paper is unsupported until HTML is available

Lower-level `ingest-finalize` is available for debugging and advanced orchestration, but it only creates a `needs-review` page and does not publish.

To finalize and publish through the user-facing workflow, use:

```bash
uv run scripts/hub.py add-source <source> --draft-output-file <draft.json> --json
```

## Ask question

User intent:

- "tell me about attention"

Behavior:

- retrieves matching pages, claims, and chunks
- returns a grounded answer
- does not write to the vault

## Verify draft

Use when you want to check if a wiki page is supportable.

## Publish draft

Use when you want to mark a verified wiki page as published.
