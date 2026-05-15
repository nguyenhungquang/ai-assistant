---
name: paper-hub-add-source
description: Use whenever the user asks to add, save, ingest, import, or publish a paper/source into the research vault.
---

# Paper Hub Add Source

Use this skill to add a paper/source to the local-first Obsidian research vault through the repository's deterministic command surface.

## Supported Sources

Supported inputs:

- arXiv IDs, such as `1706.03762v7`
- arXiv URLs
- ar5iv URLs

Current limitation: arXiv HTML must be available from `arxiv.org/html` or `ar5iv`. If HTML is unavailable, stop and report that the paper is unsupported for now. Do not fall back to manual wiki writing or direct raw-source edits.

## Guardrails

- Use `uv` for every repository command.
- Use `uv run scripts/hub.py` for the add-source workflow and verification/publish checks.
- Do not edit raw source artifacts. Raw sources are immutable.
- Do not write wiki pages manually during normal add-source workflows.
- Do not update SQLite state manually. Let repository commands update durable state.
- Do not bypass draft validation or final verification.
- Do not invent evidence outside the packet.
- Do not use outside knowledge to fill draft content.
- If final verification or publish fails, report the issues and leave the page as `needs-review`.

## Workflow

1. Stage the source:

   ```bash
   uv run scripts/hub.py add-source <source> --json
   ```

2. Read the JSON response.

   Important fields:

   - `status`: should be `needs-draft` when staging succeeds.
   - `result.draft_packet`: the only evidence source for drafting.
   - `result.prepared_json`: cached prepared payload path for debugging and inspection.
   - `result.page_path`: expected wiki page path.
   - `warnings` and `issues`: user-visible blockers or cautions.

   If the command reports unavailable HTML from `arxiv.org/html` and `ar5iv`, stop and tell the user this paper is unsupported for now.

3. Draft structured JSON from `result.draft_packet`.

   Read `draft_packet.full_paper_text` first. Use `candidate_groups`, `section_blocks`, figures, and equations only as packet-provided navigation and presentation aids. Every substantive statement must be supported by valid packet `chunk_ids`.

4. Review packet media.

   If the packet contains extracted figures or equations, include `media_review` and either attach important `figure_ids` / `equation_ids` to the sections that explain them or provide `media_review.no_media_reason` when extracted media exists but none is useful enough to include.

   Selected equations must be explained in prose. Define variables, indices, operators, objectives, and constraints when they have not already been introduced earlier in the generated Markdown; a short nearby "where ..." sentence is usually enough.

   Attach important framework, architecture, pipeline, or conceptual figures to `method_overview` or to the specific `method_details` entry that explains them when they materially clarify the method. Do not attach low-value or unexplained figures.

5. Save the draft JSON to a temporary or workspace file.

6. Finalize through the user-facing command:

   ```bash
   uv run scripts/hub.py add-source <source> --draft-output-file <draft.json> --json
   ```

   This writes the wiki page, updates SQLite state, verifies through publish, and publishes automatically when verification passes.

7. Report the outcome.

   Confirm these items from the final command response:

   - resulting page path from `result.page_path` or `writes.page`
   - DB state update through command output and verification persistence when available
   - verification status from `result.verification` or publish warnings
   - publish outcome from `result.publish_verdict` and `status`

   If status is `published`, report the published page path. If status remains `needs-review`, report the verification or publish issues without hiding them.

## Draft JSON Contract

Draft output must match the repository's current schema. Required top-level sections:

- `big_picture`
- `problem_setting`
- `core_claims`
- `method_overview`
- `method_details`
- `data_or_inputs`
- `experimental_setup`
- `results`
- `analysis`
- `limitations`
- `open_questions`

Every substantive section must include valid packet `chunk_ids`. Section-level `figure_ids` and `equation_ids` are allowed only when selected from the packet.

When extracted media exists, include:

```json
{
  "media_review": {
    "figures_reviewed": true,
    "equations_reviewed": true,
    "no_media_reason": ""
  }
}
```

Use `media_review.no_media_reason` only when extracted media exists but none is useful enough to include.

Typical section shapes:

```json
{
  "big_picture": {
    "text": "...",
    "chunk_ids": ["src_..._chunk_00001"],
    "figure_ids": [],
    "equation_ids": []
  },
  "core_claims": [
    {
      "title": "...",
      "text": "...",
      "chunk_ids": ["src_..._chunk_00002"],
      "figure_ids": [],
      "equation_ids": []
    }
  ]
}
```

## Verification And Publishing

The final `add-source` command automatically attempts publish. Publish runs verification internally. A passing verification publishes the page; a failing verification leaves the page as `needs-review`.

Use explicit checks when you need to inspect or retry the final state:

```bash
uv run scripts/hub.py verify <page-path> --json
```

```bash
uv run scripts/hub.py publish <page-path> --json
```

Report verification or publish failures directly, including `issues`, `warnings`, and any relevant `claim_results`.

## Advanced Debugging

Prefer `add-source` for normal user-facing work. Lower-level workflow subcommands exist for debugging or advanced orchestration only:

- `uv run scripts/hub.py ingest-prepare <source> --json`
- `uv run scripts/hub.py draft-handoff <prepared-json> --json`
- `uv run scripts/hub.py ingest-finalize <prepared-json> --draft-output-file <draft.json> --json`

`ingest-finalize` writes a `needs-review` page and does not publish. Return to the normal `add-source` path when the user asks to add and publish safely.

## Smoke Prompts

This skill should handle requests like:

- "Add arXiv 1706.03762v7 to the wiki."
- "Save this ar5iv paper into the vault."
- "Add this paper and publish it if verification passes."
- "The draft failed because media was ignored; fix the add-source flow."
