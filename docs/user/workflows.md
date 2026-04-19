# Workflows

## Add source

User intent:

- "add this paper to the wiki"

Default behavior:

- stage source
- draft notes
- finalize to `wiki/inbox/`

If you want safe automatic publishing, use:

```bash
uv run scripts/hub.py add-source <source> --publish-if-pass --json
```

## Ask question

User intent:

- "tell me about attention"

Behavior:

- retrieves matching pages, claims, and chunks
- returns a grounded answer
- does not write to the vault

## Verify draft

Use when you want to check if an inbox page is supportable.

## Publish draft

Use when you want to move a verified inbox page into the published wiki folders.
