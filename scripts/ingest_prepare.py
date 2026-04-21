#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from ingest_source import prepare_ingest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare ingest and emit a bounded draft packet."
    )
    parser.add_argument("source_input")
    parser.add_argument("--title")
    parser.add_argument("--canonical-locator")
    parser.add_argument("--allow-pdf-fallback", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prepared = prepare_ingest(
        source_input=args.source_input,
        title_override=args.title,
        canonical_locator_override=args.canonical_locator,
        allow_pdf_fallback=args.allow_pdf_fallback,
    )
    print(json.dumps(prepared, indent=2))


if __name__ == "__main__":
    main()
