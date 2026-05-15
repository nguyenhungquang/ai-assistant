#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from _common import (
    agent_edit_policy,
    connect_db,
    ensure_runtime_config,
    get_runtime_mode,
    init_db,
)
from _drafter import validate_draft_output


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="paper-hub orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        help="Finalize ingest from prepared packet and required external draft output",
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
    filesystem_path_keys = {
        "config_path",
        "page_path",
        "prepared_json",
        "prepared_json_path",
        "prompt_path",
        "raw_path",
        "parsed_snapshot_path",
        "extracted_path",
        "target_page_path",
        "page",
        "published_page",
        "from_path",
        "to_path",
    }
    if isinstance(obj, dict):
        normalized: dict[str, Any] = {}
        for key, value in obj.items():
            if key in filesystem_path_keys:
                normalized[key] = (
                    normalize_path(value) if isinstance(value, str) else value
                )
            else:
                normalized[key] = normalize_paths(value)
        return normalized
    if isinstance(obj, list):
        return [normalize_paths(item) for item in obj]
    return obj


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
    section = {
        "text": "string",
        "chunk_ids": ["src_..._chunk_00001"],
        "figure_ids": ["S1.F1"],
        "equation_ids": ["S3.Ex1.m1"],
    }
    entry = {
        "title": "string",
        "text": "string",
        "chunk_ids": ["src_..._chunk_00001"],
        "figure_ids": ["Figure 1"],
        "equation_ids": ["S3.Ex1.m1"],
    }
    return {
        "media_review": {
            "figures_reviewed": True,
            "equations_reviewed": True,
            "no_media_reason": "",
        },
        "big_picture": section,
        "problem_setting": section,
        "core_claims": [entry],
        "method_overview": section,
        "method_details": [entry],
        "data_or_inputs": [entry],
        "experimental_setup": [entry],
        "results": [entry],
        "analysis": [entry],
        "limitations": [entry],
        "open_questions": [entry],
    }


def load_prepared_json(prepared_json: str) -> dict[str, Any]:
    prepared_path = Path(prepared_json).expanduser()
    if not prepared_path.is_absolute():
        prepared_path = (ROOT / prepared_path).resolve(strict=False)
    return normalize_paths(json.loads(prepared_path.read_text()))


def duplicate_source_id(response: dict) -> str | None:
    for issue in response.get("issues", []):
        if not isinstance(issue, str):
            continue
        prefix = "Duplicate source detected: "
        if issue.startswith(prefix):
            return issue.removeprefix(prefix).strip()
    return None


def allowed_media_ids(draft_packet: dict, media_key: str, id_keys: tuple[str, str]) -> list[str]:
    allowed: list[str] = []
    seen: set[str] = set()
    for item in draft_packet.get(media_key, []):
        for key in id_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in seen:
                normalized_value = value.strip()
                allowed.append(normalized_value)
                seen.add(normalized_value)
    return allowed


def recover_prepared_payload(source_id: str) -> tuple[dict[str, Any] | None, str | None]:
    conn = connect_db()
    init_db(conn)
    row = conn.execute(
        "SELECT packet_json FROM prepared_packets WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None, f"No staged prepared packet row found for duplicate source: {source_id}"
    try:
        payload = json.loads(row["packet_json"])
    except json.JSONDecodeError as exc:
        return None, f"Staged prepared packet row is invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "Staged prepared packet row is not a JSON object"
    if isinstance(payload.get("draft_packet"), dict) and "page_count" in payload:
        return normalize_paths(payload), None
    return None, (
        "Prepared packet cache is missing and the staged DB row uses the legacy "
        "draft-packet-only format, so it cannot be recovered. Re-stage the source "
        "to create a recoverable prepared payload."
    )


def load_draft_output_for_precheck(
    args: argparse.Namespace, draft_input_text: str | None
) -> dict[str, Any]:
    if getattr(args, "draft_output_file", None):
        if args.draft_output_file == "-":
            raw = draft_input_text or ""
        else:
            raw = Path(args.draft_output_file).read_text()
    elif getattr(args, "draft_output_stdin", False):
        raw = draft_input_text or ""
    else:
        raise ValueError("draft output is required")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("draft output must be a JSON object")
    return parsed


def precheck_draft_output(
    prepared_payload: dict[str, Any],
    args: argparse.Namespace,
    draft_input_text: str | None,
) -> tuple[bool, str | None]:
    try:
        draft_output = load_draft_output_for_precheck(args, draft_input_text)
        validate_draft_output(
            prepared_payload.get("draft_packet", {}), draft_output, strict=True
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return False, f"Draft output failed pre-finalize validation: {exc}"
    return True, None


def handle_draft_handoff(args: argparse.Namespace) -> tuple[int, dict]:
    prepared = load_prepared_json(args.prepared_json)
    prompt_path = ROOT / "prompts" / "drafter_prompt.md"
    prompt_text = prompt_path.read_text()
    draft_packet = prepared.get("draft_packet", {}) or {}
    allowed_figure_ids = allowed_media_ids(
        draft_packet, "figures", ("figure_id", "label")
    )
    allowed_equation_ids = allowed_media_ids(
        draft_packet, "equations", ("math_id",)
    )
    media_selection_required = bool(
        draft_packet.get("figures", []) or draft_packet.get("equations", [])
    )
    prepared_rel = normalize_path(str(args.prepared_json))
    fallback_finalize_command = (
        f"uv run scripts/hub.py add-source {prepared['source_url']} --draft-output-file <draft.json> --json"
        if prepared.get("source_url")
        else f"uv run scripts/hub.py ingest-finalize {prepared_rel} --draft-output-file <draft.json> --json"
    )
    finalize_command = (
        prepared.get("coordination", {}) or {}
    ).get(
        "finalize_command",
        fallback_finalize_command,
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
                chunk["chunk_id"] for chunk in draft_packet.get("chunks", [])
            ],
            "chunk_id_rule": (
                "Chunk IDs are not guaranteed to be sequential. Use only exact IDs from allowed_chunk_ids or the packet chunks."
            ),
            "available_figure_count": len(draft_packet.get("figures", [])),
            "available_equation_count": len(draft_packet.get("equations", [])),
            "allowed_figure_ids": allowed_figure_ids,
            "allowed_equation_ids": allowed_equation_ids,
            "equation_id_rule": (
                "For equation_ids, use equation math_id values from allowed_equation_ids, not display labels such as 'Equation 1'."
            ),
            "section_shape_rule": (
                "big_picture, problem_setting, and method_overview must be objects. core_claims, method_details, data_or_inputs, experimental_setup, results, analysis, limitations, and open_questions must be lists of objects."
            ),
            "chunk_reuse_rule": (
                "Using the same chunk_id in 4 or more sections fails validation; distribute evidence across relevant chunks."
            ),
            "method_overview_rule": (
                "method_overview must explain the overall approach with method evidence and overview cues, not only equations, hyperparameters, benchmark setup, or narrow implementation details."
            ),
            "media_selection_required": media_selection_required,
            "media_selection_rule": (
                "When media_selection_required is true, media_review is required. Review available figures/equations, attach important figure_ids/equation_ids to the section that explains them, or set media_review.no_media_reason when no extracted media is useful enough to include."
            ),
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
    draft_input_text, finalize_extra_args, warnings = load_draft_input(args)
    prepare_code, prepare_response = handle_ingest_prepare(prepare_args)
    if prepare_code != 0:
        duplicate_id = duplicate_source_id(prepare_response)
        if duplicate_id and finalize_extra_args:
            prepared_path = ROOT / "system" / "cache" / f"prepared-{duplicate_id}.json"
            if not prepared_path.exists():
                recovered_payload, recovery_issue = recover_prepared_payload(duplicate_id)
                if recovered_payload is None:
                    prepare_response["command"] = "add-source"
                    prepare_response["issues"].append(
                        f"Prepared packet not found for duplicate source: {normalize_path(str(prepared_path))}"
                    )
                    if recovery_issue:
                        prepare_response["issues"].append(recovery_issue)
                    return prepare_code, prepare_response
                prepared_path.parent.mkdir(parents=True, exist_ok=True)
                prepared_path.write_text(json.dumps(recovered_payload, indent=2))
                prepared_payload = recovered_payload
                warnings.append(
                    f"Recovered missing prepared packet cache from staged DB row: {normalize_path(str(prepared_path))}"
                )
            else:
                prepared_payload = load_prepared_json(str(prepared_path))
        else:
            prepare_response["command"] = "add-source"
            return prepare_code, prepare_response
    else:
        prepared_payload = prepare_response["result"]
        cache_dir = ROOT / "system" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        prepared_path = cache_dir / f"prepared-{prepared_payload['source_id']}.json"
        prepared_path.write_text(json.dumps(prepared_payload, indent=2))

    if prepare_code != 0 and not finalize_extra_args:
        prepare_response["command"] = "add-source"
        return prepare_code, prepare_response

    if not finalize_extra_args:
        coordination = dict(prepared_payload.get("coordination") or {})
        coordination["finalize_command"] = (
            f"uv run scripts/hub.py add-source {args.source} --draft-output-file <draft.json> --json"
        )
        response = envelope(
            command="add-source",
            ok=True,
            status="needs-draft",
            issues=[],
            warnings=[
                "Prepared ingest is staged. Top-level coordinator should hand result.draft_packet to one drafting subagent, require it to read the full paper text in the packet first, then call add-source again with the structured draft output. add-source will finalize and attempt publish automatically."
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
                "coordination": coordination,
                "draft_packet": prepared_payload.get("draft_packet"),
            },
            writes={
                "prepared_json": normalize_path(str(prepared_path)),
            },
        )
        return 2, response
    precheck_ok, precheck_issue = precheck_draft_output(
        prepared_payload, args, draft_input_text
    )
    if not precheck_ok:
        return 2, envelope(
            command="add-source",
            ok=False,
            status="blocked",
            issues=[precheck_issue or "Draft output failed pre-finalize validation"],
            warnings=warnings,
            result={
                "source_id": prepared_payload.get("source_id"),
                "version_id": prepared_payload.get("version_id"),
                "page_id": prepared_payload.get("page_id"),
                "page_path": prepared_payload.get("page_path"),
                "prepared_json": normalize_path(str(prepared_path)),
            },
            writes={
                "prepared_json": normalize_path(str(prepared_path)),
            },
        )
    finalize_args = [str(prepared_path)] + finalize_extra_args
    finalize_proc = run_script(
        "ingest_finalize.py", finalize_args, input_text=draft_input_text
    )

    if finalize_proc.returncode != 0:
        code, response = map_failure(
            "add-source", finalize_proc.stderr, finalize_proc.returncode
        )
        response["warnings"] = warnings
        response["writes"] = {"prepared_json": normalize_path(str(prepared_path))}
        return code, response

    try:
        prepared_path.unlink(missing_ok=True)
    except Exception:
        pass

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
    exit_code = 2

    if finalized.get("page_path"):
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
            result["verification"] = publish_response["result"].get("verification")
            status = "published"
            exit_code = 0
        else:
            result["publish_verdict"] = "blocked"
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
    return exit_code, response


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
