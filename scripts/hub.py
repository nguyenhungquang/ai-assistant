#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from _common import agent_edit_policy, ensure_runtime_config, get_runtime_mode


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="paper-hub orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest a paper source")
    ingest.add_argument("source")
    ingest.add_argument("--title")
    ingest.add_argument("--canonical-locator")
    ingest.add_argument("--json", action="store_true")

    add_source = subparsers.add_parser(
        "add-source",
        help="User-facing workflow wrapper for adding a source to the wiki",
    )
    add_source.add_argument("source")
    add_source.add_argument("--title")
    add_source.add_argument("--canonical-locator")
    add_source.add_argument("--draft-output-file")
    add_source.add_argument("--draft-output-stdin", action="store_true")
    add_source.add_argument("--verify", action="store_true")
    add_source.add_argument("--publish-if-pass", action="store_true")
    add_source.add_argument("--json", action="store_true")

    ingest_prepare = subparsers.add_parser(
        "ingest-prepare", help="Prepare ingest and emit a draft packet"
    )
    ingest_prepare.add_argument("source")
    ingest_prepare.add_argument("--title")
    ingest_prepare.add_argument("--canonical-locator")
    ingest_prepare.add_argument("--json", action="store_true")

    draft_handoff = subparsers.add_parser(
        "draft-handoff",
        help="Emit the canonical external-drafter handoff payload for a prepared ingest",
    )
    draft_handoff.add_argument("prepared_json")
    draft_handoff.add_argument("--json", action="store_true")

    config_cmd = subparsers.add_parser(
        "config", help="Show the runtime config and current agent mode"
    )
    config_cmd.add_argument("--json", action="store_true")

    ingest_finalize = subparsers.add_parser(
        "ingest-finalize",
        help="Finalize ingest from prepared packet and optional draft output",
    )
    ingest_finalize.add_argument("prepared_json")
    ingest_finalize.add_argument("--draft-output-file")
    ingest_finalize.add_argument("--draft-output-stdin", action="store_true")
    ingest_finalize.add_argument("--json", action="store_true")

    retrieve = subparsers.add_parser("retrieve", help="Retrieve evidence")
    retrieve.add_argument("query")
    retrieve.add_argument("--top-k", type=int, default=5)
    retrieve.add_argument("--json", action="store_true")

    ask = subparsers.add_parser(
        "ask", help="User-facing workflow wrapper for question answering"
    )
    ask.add_argument("query")
    ask.add_argument("--top-k", type=int, default=5)
    ask.add_argument("--json", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify a wiki page")
    verify.add_argument("page_path")
    verify.add_argument("--json", action="store_true")

    publish = subparsers.add_parser("publish", help="Mark a verified wiki page as published")
    publish.add_argument("page_path")
    publish.add_argument("--json", action="store_true")

    return parser


def run_script(
    script_name: str, args: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text,
    )


def envelope(
    *,
    command: str,
    ok: bool,
    status: str,
    issues: list[str],
    warnings: list[str],
    result: dict,
    writes: dict,
) -> dict:
    return {
        "ok": ok,
        "command": command,
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "result": result,
        "writes": writes,
    }


def map_failure(command: str, stderr: str, returncode: int) -> tuple[int, dict]:
    message = stderr.strip() or f"{command} failed"
    status = "blocked" if returncode == 2 else "error"
    code = 2 if status == "blocked" else 1
    return code, envelope(
        command=command,
        ok=False,
        status=status,
        issues=[message],
        warnings=[],
        result={},
        writes={},
    )


def format_human(response: dict) -> str:
    lines = [f"{response['command']}: {response['status']}"]
    if response["issues"]:
        lines.extend(f"- issue: {issue}" for issue in response["issues"])
    if response["warnings"]:
        lines.extend(f"- warning: {warning}" for warning in response["warnings"])
    if response["result"]:
        lines.extend(f"- {key}: {value}" for key, value in response["result"].items())
    if response["writes"]:
        lines.extend(
            f"- wrote {key}: {value}" for key, value in response["writes"].items()
        )
    return "\n".join(lines)


def normalize_path(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve(strict=False)
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def normalize_paths(obj: Any) -> Any:
    if isinstance(obj, dict):
        normalized: dict[str, Any] = {}
        for key, value in obj.items():
            if key.endswith("path") or key in {
                "page",
                "published_page",
                "from_path",
                "to_path",
            }:
                normalized[key] = (
                    normalize_path(value) if isinstance(value, str) else value
                )
            else:
                normalized[key] = normalize_paths(value)
        return normalized
    if isinstance(obj, list):
        return [normalize_paths(item) for item in obj]
    return obj


def handle_ingest(args: argparse.Namespace) -> tuple[int, dict]:
    script_args = [args.source]
    if args.title:
        script_args.extend(["--title", args.title])
    if args.canonical_locator:
        script_args.extend(["--canonical-locator", args.canonical_locator])
    proc = run_script("ingest_source.py", script_args)
    if proc.returncode != 0:
        return map_failure("ingest", proc.stderr, proc.returncode)

    parsed = normalize_paths(json.loads(proc.stdout))
    page_path = parsed.get("page_path")
    source_id = parsed.get("source_id")
    source_kind = parsed.get("source_kind")
    chunk_count = parsed.get("chunk_count")
    response = envelope(
        command="ingest",
        ok=True,
        status=parsed.get("status", "needs-review"),
        issues=[],
        warnings=[],
        result={
            "source_id": source_id,
            "version_id": parsed.get("version_id"),
            "page_id": parsed.get("page_id"),
            "page_path": page_path,
            "source_kind": source_kind,
            "chunk_count": chunk_count,
        },
        writes={
            "page": page_path,
        },
    )
    return 2, response


def load_draft_input(
    args: argparse.Namespace,
) -> tuple[str | None, list[str], list[str]]:
    warnings: list[str] = []
    script_args: list[str] = []
    draft_input_text: str | None = None
    if getattr(args, "draft_output_file", None) and getattr(
        args, "draft_output_stdin", False
    ):
        raise SystemExit(
            "Use either --draft-output-file or --draft-output-stdin, not both."
        )
    if getattr(args, "draft_output_file", None):
        draft_path = args.draft_output_file
        if draft_path == "-":
            draft_input_text = sys.stdin.read()
            script_args.extend(["--draft-output-file", "-"])
        else:
            script_args.extend(["--draft-output-file", draft_path])
    elif getattr(args, "draft_output_stdin", False):
        draft_input_text = sys.stdin.read()
        script_args.append("--draft-output-stdin")
    return draft_input_text, script_args, warnings


def handle_ingest_prepare(args: argparse.Namespace) -> tuple[int, dict]:
    script_args = [args.source]
    if args.title:
        script_args.extend(["--title", args.title])
    if args.canonical_locator:
        script_args.extend(["--canonical-locator", args.canonical_locator])
    proc = run_script("ingest_prepare.py", script_args)
    if proc.returncode != 0:
        return map_failure("ingest-prepare", proc.stderr, proc.returncode)
    parsed = normalize_paths(json.loads(proc.stdout))
    response = envelope(
        command="ingest-prepare",
        ok=True,
        status="prepared",
        issues=[],
        warnings=[],
        result=parsed,
        writes={
            "source": parsed.get("source_id"),
            "draft_packet": "stdout",
        },
    )
    return 0, response


def handle_ingest_finalize(args: argparse.Namespace) -> tuple[int, dict]:
    script_args = [args.prepared_json]
    draft_input_text, extra_args, warnings = load_draft_input(args)
    script_args.extend(extra_args)
    proc = run_script("ingest_finalize.py", script_args, input_text=draft_input_text)
    if proc.returncode != 0:
        return map_failure("ingest-finalize", proc.stderr, proc.returncode)
    parsed = normalize_paths(json.loads(proc.stdout))
    response = envelope(
        command="ingest-finalize",
        ok=True,
        status=parsed.get("status", "needs-review"),
        issues=[],
        warnings=warnings,
        result={
            "source_id": parsed.get("source_id"),
            "version_id": parsed.get("version_id"),
            "page_id": parsed.get("page_id"),
            "page_path": parsed.get("page_path"),
            "source_kind": parsed.get("source_kind"),
            "chunk_count": parsed.get("chunk_count"),
        },
        writes={
            "page": parsed.get("page_path"),
        },
    )
    return 2, response


def expected_draft_output_schema() -> dict[str, Any]:
    section = {"text": "string", "chunk_ids": ["src_..._chunk_00001"]}
    return {
        "big_picture": section,
        "main_contributions": [section],
        "main_results": [section],
        "method_overview": section,
        "detailed_findings": [section],
        "limitations": [section],
        "open_questions": [section],
    }


def load_prepared_json(prepared_json: str) -> dict[str, Any]:
    prepared_path = Path(prepared_json).expanduser()
    if not prepared_path.is_absolute():
        prepared_path = (ROOT / prepared_path).resolve(strict=False)
    return normalize_paths(json.loads(prepared_path.read_text()))


def handle_draft_handoff(args: argparse.Namespace) -> tuple[int, dict]:
    prepared = load_prepared_json(args.prepared_json)
    prompt_path = ROOT / "prompts" / "drafter_prompt.md"
    prompt_text = prompt_path.read_text()
    prepared_rel = normalize_path(str(args.prepared_json))
    finalize_command = (
        prepared.get("coordination", {}) or {}
    ).get(
        "finalize_command",
        f"uv run scripts/hub.py ingest-finalize {prepared_rel} --draft-output-file <draft.json> --json",
    )
    verify_command = (
        prepared.get("coordination", {}) or {}
    ).get(
        "verify_command",
        f"uv run scripts/hub.py verify {prepared.get('page_path')} --json",
    )
    handoff = {
        "handoff_version": "v1",
        "description": (
            "Canonical external-drafter handoff. Give payload.draft_packet to one drafting subagent, require it to read draft_packet.full_paper_text before drafting, return JSON-only output matching expected_output_schema, then pass the returned file into finalize_command."
        ),
        "workspace_mode": get_runtime_mode(),
        "agent_policy": agent_edit_policy(),
        "prompt_path": normalize_path(str(prompt_path)),
        "prompt_text": prompt_text,
        "payload": {
            "draft_packet": prepared.get("draft_packet"),
        },
        "expected_output_schema": expected_draft_output_schema(),
        "constraints": {
            "json_only": True,
            "use_only_packet_evidence": True,
            "allowed_chunk_ids": [
                chunk["chunk_id"] for chunk in prepared.get("draft_packet", {}).get("chunks", [])
            ],
        },
        "next_steps": {
            "finalize_command": finalize_command,
            "verify_command": verify_command,
            "target_page_path": prepared.get("page_path"),
        },
    }
    response = envelope(
        command="draft-handoff",
        ok=True,
        status="ready",
        issues=[],
        warnings=[],
        result=handoff,
        writes={},
    )
    return 0, response


def handle_add_source(args: argparse.Namespace) -> tuple[int, dict]:
    prepare_args = argparse.Namespace(
        source=args.source,
        title=args.title,
        canonical_locator=args.canonical_locator,
    )
    prepare_code, prepare_response = handle_ingest_prepare(prepare_args)
    if prepare_code != 0:
        prepare_response["command"] = "add-source"
        return prepare_code, prepare_response

    prepared_payload = prepare_response["result"]
    cache_dir = ROOT / "system" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = cache_dir / f"prepared-{prepared_payload['source_id']}.json"
    prepared_path.write_text(json.dumps(prepared_payload, indent=2))

    draft_input_text, finalize_extra_args, warnings = load_draft_input(args)
    if not finalize_extra_args:
        response = envelope(
            command="add-source",
            ok=True,
            status="needs-draft",
            issues=[],
            warnings=[
                "Prepared ingest is staged. Top-level coordinator should hand result.draft_packet to one drafting subagent, require it to read the full paper text in the packet first, then call ingest-finalize with the structured draft output."
            ],
            result={
                "source_id": prepared_payload.get("source_id"),
                "version_id": prepared_payload.get("version_id"),
                "page_id": prepared_payload.get("page_id"),
                "page_path": prepared_payload.get("page_path"),
                "source_kind": prepared_payload.get("source_kind"),
                "workspace_mode": get_runtime_mode(),
                "agent_policy": agent_edit_policy(),
                "chunk_count": prepared_payload.get("chunk_count"),
                "prepared_json": normalize_path(str(prepared_path)),
                "coordination": prepared_payload.get("coordination"),
                "draft_packet": prepared_payload.get("draft_packet"),
            },
            writes={
                "prepared_json": normalize_path(str(prepared_path)),
            },
        )
        return 2, response
    finalize_args = [str(prepared_path)] + finalize_extra_args
    finalize_proc = run_script(
        "ingest_finalize.py", finalize_args, input_text=draft_input_text
    )
    try:
        prepared_path.unlink(missing_ok=True)
    except Exception:
        pass

    if finalize_proc.returncode != 0:
        code, response = map_failure(
            "add-source", finalize_proc.stderr, finalize_proc.returncode
        )
        response["warnings"] = warnings
        return code, response

    finalized = normalize_paths(json.loads(finalize_proc.stdout))
    result = {
        "source_id": finalized.get("source_id"),
        "version_id": finalized.get("version_id"),
        "page_id": finalized.get("page_id"),
        "page_path": finalized.get("page_path"),
        "source_kind": finalized.get("source_kind"),
        "chunk_count": finalized.get("chunk_count"),
    }
    writes = {"page": finalized.get("page_path")}
    status = finalized.get("status", "needs-review")

    should_verify = args.verify or args.publish_if_pass
    if should_verify and finalized.get("page_path"):
        verify_args = argparse.Namespace(page_path=finalized["page_path"])
        verify_code, verify_response = handle_verify(verify_args)
        result["verify_verdict"] = verify_response["status"]
        if verify_response["issues"]:
            warnings.extend(verify_response["issues"])
        if verify_code == 1:
            return 1, envelope(
                command="add-source",
                ok=False,
                status="error",
                issues=verify_response["issues"],
                warnings=warnings,
                result=result,
                writes=writes,
            )

        if args.publish_if_pass and verify_response["status"] == "pass":
            publish_args = argparse.Namespace(page_path=finalized["page_path"])
            publish_code, publish_response = handle_publish(publish_args)
            if publish_code == 1:
                return 1, envelope(
                    command="add-source",
                    ok=False,
                    status="error",
                    issues=publish_response["issues"],
                    warnings=warnings,
                    result=result,
                    writes=writes,
                )
            if publish_code == 0:
                published_path = publish_response["result"].get("to_path")
                result["page_path"] = published_path
                writes["page"] = published_path
                result["publish_verdict"] = "published"
                status = "published"
            else:
                warnings.extend(publish_response.get("issues", []))

    response = envelope(
        command="add-source",
        ok=True,
        status=status,
        issues=[],
        warnings=warnings,
        result=result,
        writes=writes,
    )
    return 2, response


def handle_retrieve(args: argparse.Namespace) -> tuple[int, dict]:
    proc = run_script("retrieve_evidence.py", [args.query, "--top-k", str(args.top_k)])
    if proc.returncode != 0:
        return map_failure("retrieve", proc.stderr, proc.returncode)
    parsed = normalize_paths(json.loads(proc.stdout))
    response = envelope(
        command="retrieve",
        ok=True,
        status="ok",
        issues=[],
        warnings=[],
        result={
            "query": parsed.get("query"),
            "pages": parsed.get("pages", []),
            "claims": parsed.get("claims", []),
            "chunks": parsed.get("chunks", []),
            "confidence_notes": [],
        },
        writes={},
    )
    return 0, response


def synthesize_answer(
    query: str, pages: list[dict], claims: list[dict], chunks: list[dict]
) -> dict[str, Any]:
    summary_parts: list[str] = []
    if claims:
        top_claim = claims[0]
        claim_text = (top_claim.get("claim_text") or "").strip()
        claim_source = top_claim.get("page_title") or "unknown source"
        if claim_text:
            summary_parts.append(
                f"Top matching claim from {claim_source}: {claim_text}"
            )
    if pages:
        page_titles = ", ".join(page.get("title", "unknown") for page in pages[:3])
        summary_parts.append(f"Top matching pages: {page_titles}.")
    if chunks:
        top_chunk = chunks[0]
        section = top_chunk.get("section_path") or "unknown section"
        excerpt = (top_chunk.get("excerpt") or "").strip()
        chunk_source = top_chunk.get("page_title") or top_chunk.get("source_id")
        if excerpt:
            summary_parts.append(f"Best evidence came from {section}: {excerpt}")
        if chunk_source:
            summary_parts.append(f"Top evidence source: {chunk_source}.")
    if not summary_parts:
        summary_parts.append(
            "No strong evidence was found in the current vault for this query."
        )

    supporting_sources = []
    seen_titles: set[str] = set()
    for claim in claims:
        title = claim.get("page_title")
        if title and title not in seen_titles:
            supporting_sources.append(title)
            seen_titles.add(title)
    for chunk in chunks:
        title = chunk.get("page_title")
        if title and title not in seen_titles:
            supporting_sources.append(title)
            seen_titles.add(title)
    if not supporting_sources:
        for page in pages:
            title = page.get("title")
            if title and title not in seen_titles:
                supporting_sources.append(title)
                seen_titles.add(title)

    confidence_notes = []
    if not pages and not chunks and not claims:
        confidence_notes.append("No matching pages, claims, or chunks were found.")
    elif len(chunks) < 2:
        confidence_notes.append("Answer is based on limited retrieved evidence.")

    return {
        "answer": " ".join(summary_parts),
        "supporting_sources": supporting_sources,
        "supporting_claims": claims[:3],
        "supporting_chunks": chunks[:3],
        "confidence_notes": confidence_notes,
    }


def handle_ask(args: argparse.Namespace) -> tuple[int, dict]:
    retrieve_args = argparse.Namespace(query=args.query, top_k=args.top_k)
    retrieve_code, retrieve_response = handle_retrieve(retrieve_args)
    if retrieve_code != 0:
        retrieve_response["command"] = "ask"
        return retrieve_code, retrieve_response

    retrieved = retrieve_response["result"]
    synthesized = synthesize_answer(
        args.query,
        retrieved.get("pages", []),
        retrieved.get("claims", []),
        retrieved.get("chunks", []),
    )
    response = envelope(
        command="ask",
        ok=True,
        status="answered",
        issues=[],
        warnings=[],
        result={
            "query": args.query,
            "answer": synthesized["answer"],
            "supporting_sources": synthesized["supporting_sources"],
            "supporting_claims": synthesized["supporting_claims"],
            "supporting_chunks": synthesized["supporting_chunks"],
            "confidence_notes": synthesized["confidence_notes"],
        },
        writes={},
    )
    return 0, response


def handle_verify(args: argparse.Namespace) -> tuple[int, dict]:
    proc = run_script("verify_draft.py", [args.page_path])
    if proc.returncode != 0:
        return map_failure("verify", proc.stderr, proc.returncode)
    parsed = normalize_paths(json.loads(proc.stdout))
    verdict = parsed.get("verdict", "error")
    code = 0 if verdict == "pass" else 2
    supporting_spans = []
    persisted = parsed.get("persisted")
    if persisted:
        supporting_spans.extend(persisted.get("supporting_spans", []))
    response = envelope(
        command="verify",
        ok=True,
        status=verdict,
        issues=parsed.get("issues", []),
        warnings=[],
        result={
            "page_path": parsed.get("page"),
            "verdict": verdict,
            "summary_claim": parsed.get("summary_claim"),
            "supporting_spans": supporting_spans,
            "claim_results": parsed.get("claim_results", []),
        },
        writes={"verification_state": "sqlite"} if parsed.get("persisted") else {},
    )
    return code, response


def handle_publish(args: argparse.Namespace) -> tuple[int, dict]:
    proc = run_script("publish_page.py", [args.page_path])
    if proc.returncode != 0:
        return map_failure("publish", proc.stderr, proc.returncode)
    parsed = normalize_paths(json.loads(proc.stdout))
    response = envelope(
        command="publish",
        ok=True,
        status="published",
        issues=[],
        warnings=[],
        result={
            "from_path": normalize_path(args.page_path),
            "to_path": parsed.get("published_page"),
            "verification": normalize_paths(parsed.get("verification")),
        },
        writes={
            "page": parsed.get("published_page"),
            "index": "index.md",
            "log": "log.md",
        },
    )
    return 0, response


def handle_config(args: argparse.Namespace) -> tuple[int, dict]:
    config_path = ensure_runtime_config()
    response = envelope(
        command="config",
        ok=True,
        status="ready",
        issues=[],
        warnings=[],
        result={
            "config_path": normalize_path(str(config_path)),
            "workspace_mode": get_runtime_mode(),
            "agent_policy": agent_edit_policy(),
        },
        writes={"config": normalize_path(str(config_path))},
    )
    return 0, response


def main() -> None:
    ensure_runtime_config()
    parser = build_parser()
    args = parser.parse_args()

    handler_map = {
        "ingest": handle_ingest,
        "add-source": handle_add_source,
        "ask": handle_ask,
        "ingest-prepare": handle_ingest_prepare,
        "draft-handoff": handle_draft_handoff,
        "config": handle_config,
        "ingest-finalize": handle_ingest_finalize,
        "retrieve": handle_retrieve,
        "verify": handle_verify,
        "publish": handle_publish,
    }
    exit_code, response = handler_map[args.command](args)

    if getattr(args, "json", False):
        print(json.dumps(response, indent=2))
    else:
        print(format_human(response))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
