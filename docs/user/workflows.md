# Workflows

## Add source

User intent:

- "add this paper to the wiki"

Default behavior:

- stage source
- return a bounded draft handoff packet for the coding agent

Coordinator behavior:

1. run `add-source <source>` or `ingest-prepare <source>`
2. hand `result.draft_packet` to one bounded drafting subagent
3. call `ingest-finalize <prepared-json> --draft-output-file <draft.json>`
4. optionally run `verify`
5. optionally run `publish`

If you want safe automatic publishing, use:

```bash
uv run scripts/hub.py add-source <source> --draft-output-file <draft.json> --publish-if-pass --json
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
