#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingest_source import finalize_ingest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Finalize ingest from a prepared packet and required draft output."
    )
    parser.add_argument("prepared_json")
    parser.add_argument("--draft-output-file")
    parser.add_argument("--draft-output-stdin", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        prepared = json.loads(Path(args.prepared_json).read_text())
        if "result" in prepared and isinstance(prepared["result"], dict):
            prepared = prepared["result"]

        draft_output = None
        if args.draft_output_file and args.draft_output_stdin:
            raise SystemExit(
                "Use either --draft-output-file or --draft-output-stdin, not both."
            )
        if args.draft_output_file:
            if args.draft_output_file == "-":
                draft_output = json.loads(sys.stdin.read())
            else:
                draft_output = json.loads(Path(args.draft_output_file).read_text())
        elif args.draft_output_stdin:
            draft_output = json.loads(sys.stdin.read())
        payload = finalize_ingest(prepared, draft_output=draft_output)
        print(json.dumps(payload, indent=2))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON supplied to ingest-finalize: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"Invalid draft output: {exc}") from exc


if __name__ == "__main__":
    main()
