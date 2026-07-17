from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.ai import (
    OpenAiCredentials,
    OpenAiError,
    build_safe_context,
    default_openai_model,
    extract_response_text,
    openai_post,
    record_ai_usage,
    require_full_target_document_ai_opt_in,
)
from ledgerly.engine.derived_text import build_derived_text_snapshot
from ledgerly.engine.document_targets import resolve_document_target
from ledgerly.engine.grounding import citation_instruction, validate_grounding, wrap_ai_edit_span
from ledgerly.engine.vault import create_document_version, ensure_vault_dirs

EDIT_REVIEW_STATUSES = {"needs_human_review", "accepted", "approved", "rejected"}

_EDIT_BLOCK_RE = re.compile(
    r"###\s*EDIT\s+paragraph_id=(?P<paragraph_id>\S+)\s+sentence_id=(?P<sentence_id>\S+)\s*\n"
    r"ORIGINAL:\s*(?P<original>.*?)\s*\n"
    r"PROPOSED:\s*(?P<proposed>.*?)\s*\n"
    r"RATIONALE:\s*(?P<rationale>.*?)\s*\n"
    r"###\s*END EDIT",
    re.DOTALL,
)


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _sentence_lookup(derived: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`{sentence_id: {paragraph_id, text}}` for every sentence anchor in a
    derived-text snapshot -- the ground truth `create_ai_edit_session`
    validates every proposed edit's claimed anchor against, so a model
    can never silently invent an anchor that doesn't exist.
    """
    lookup: dict[str, dict[str, Any]] = {}
    for paragraph in derived.get("paragraphs", []):
        for sentence in paragraph.get("sentences", []):
            sentence_id = sentence.get("sentence_id")
            if sentence_id:
                lookup[sentence_id] = {"paragraph_id": paragraph.get("paragraph_id"), "text": sentence.get("text")}
    return lookup


def _edit_session_prompt(derived: dict[str, Any], context: dict[str, Any], instructions: str) -> str:
    sentence_map = [
        {
            "paragraph_id": paragraph.get("paragraph_id"),
            "sentence_id": sentence.get("sentence_id"),
            "text": sentence.get("text"),
        }
        for paragraph in derived.get("paragraphs", [])
        for sentence in paragraph.get("sentences", [])
    ]
    return (
        "You are proposing reviewable edits to one document in a local-first, evidence-first research workspace.\n"
        "Do not rewrite the whole document. Propose edits only for specific sentences that genuinely need "
        "improvement, grounded in the supplied safe context. If nothing needs improvement, propose no edits at all.\n\n"
        "For each proposed edit, use exactly this format, one block per edit:\n\n"
        "### EDIT paragraph_id=<id> sentence_id=<id>\n"
        "ORIGINAL: <the exact original sentence, copied verbatim from the document map below>\n"
        "PROPOSED: <the proposed replacement sentence>\n"
        "RATIONALE: <why this change improves the document>\n"
        "### END EDIT\n\n"
        "Only use paragraph_id/sentence_id values that appear in the document map below -- never invent one.\n\n"
        f"{citation_instruction()}\n\n"
        f"User instructions: {instructions or 'General improvement pass.'}\n\n"
        f"Document map (paragraph_id/sentence_id -> text) JSON:\n{json.dumps(sentence_map, ensure_ascii=False, indent=2)}\n\n"
        f"Safe context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _parse_proposed_edits(text: str, sentence_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edits = []
    for index, match in enumerate(_EDIT_BLOCK_RE.finditer(text or ""), start=1):
        paragraph_id = match.group("paragraph_id").strip()
        sentence_id = match.group("sentence_id").strip()
        original_text = match.group("original").strip()
        proposed_text = match.group("proposed").strip()
        rationale = match.group("rationale").strip()

        anchor = sentence_lookup.get(sentence_id)
        anchor_verified = (
            anchor is not None
            and anchor.get("paragraph_id") == paragraph_id
            and _normalize(anchor.get("text", "")) == _normalize(original_text)
        )
        edits.append(
            {
                "edit_id": f"edit-{index:03d}",
                "paragraph_id": paragraph_id,
                "sentence_id": sentence_id,
                "original_text": original_text,
                "proposed_text": proposed_text,
                "rationale": rationale,
                "anchor_verified": anchor_verified,
                "review_status": "needs_human_review",
            }
        )
    return edits


def _session_path(workspace: Path, session_id: str) -> Path:
    return ensure_vault_dirs(workspace)["ai_edit_sessions"] / f"{session_id}.yaml"


def list_ai_edit_sessions(workspace: Path) -> list[dict[str, Any]]:
    directory = ensure_vault_dirs(workspace)["ai_edit_sessions"]
    return [read_yaml(path) for path in sorted(directory.glob("aiedit-*.yaml"))]


def get_ai_edit_session(workspace: Path, session_id: str) -> dict[str, Any]:
    path = _session_path(workspace, session_id)
    if not path.is_file():
        raise ValueError(f"Unknown AI edit session_id: {session_id}")
    return read_yaml(path)


def create_ai_edit_session(
    workspace: Path,
    credentials: OpenAiCredentials,
    target: str,
    *,
    instructions: str = "",
    full_target_document_ai: bool = False,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Propose reviewable AI edits to a target document, anchored to specific
    paragraph/sentence IDs from the Phase 8 derived-text snapshot -- never
    modifies the target itself, mirroring the deterministic citation-plan
    propose-then-apply pattern (`engine.citations.create_citation_plan` /
    `apply_citation_plan`). Requires the same `full_target_document_ai`
    opt-in as `cite ai-plan`, since the whole document's sentence map (not
    just excerpts) has to be sent for the model to anchor edits to it.
    """
    require_full_target_document_ai_opt_in(ai=True, full_target_document=full_target_document_ai)
    resolved = resolve_document_target(workspace, target, cwd=cwd)
    if resolved.path.suffix.lower() != ".md":
        raise OpenAiError(
            "AI edit sessions currently support Markdown (.md) targets only -- derived-text section/paragraph "
            "anchors are only recovered for .md sources."
        )

    snapshot_version = create_document_version(
        workspace,
        str(resolved.path),
        creation_reason="pre_ai_edit_session_snapshot",
        source_command="ai edit-session create",
        cwd=cwd,
    )
    derived = build_derived_text_snapshot(workspace, snapshot_version["version_id"])
    sentence_lookup = _sentence_lookup(derived)

    topic = read_yaml(workspace / "research-context.yaml").get("project", {}).get("topic")
    query = topic.strip() if isinstance(topic, str) and topic.strip() else None
    context = build_safe_context(workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=query)

    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {"model": model, "input": _edit_session_prompt(derived, context, instructions)},
        opener=opener,
    )
    text = extract_response_text(response)
    edits = _parse_proposed_edits(text, sentence_lookup)
    grounding = validate_grounding(text, context=context)

    sessions = list_ai_edit_sessions(workspace)
    session_id = f"aiedit-{len(sessions) + 1:03d}"
    session = {
        "version": 1,
        "session_id": session_id,
        "target": resolved.target,
        "target_path": str(resolved.path),
        "source_version_id": snapshot_version["version_id"],
        "derived_text_path": derived["derived_text_path"],
        "instructions": instructions,
        "kind": "ai_edit_session",
        "provider": "openai",
        "model": model,
        "ai_used": True,
        "requires_user_review": True,
        "original_document_modified": False,
        "response_id": response.get("id") if isinstance(response, dict) else None,
        "raw_response_text": text,
        "grounding": grounding,
        "edit_count": len(edits),
        "unverified_anchor_count": sum(1 for edit in edits if not edit["anchor_verified"]),
        "edits": edits,
    }
    write_yaml(_session_path(workspace, session_id), session)
    return record_ai_usage(workspace, session)


def set_ai_edit_review_status(workspace: Path, session_id: str, edit_id: str, review_status: str) -> dict[str, Any]:
    if review_status not in EDIT_REVIEW_STATUSES:
        allowed = ", ".join(sorted(EDIT_REVIEW_STATUSES))
        raise ValueError(f"Invalid review_status: {review_status!r}. Expected one of: {allowed}")
    path = _session_path(workspace, session_id)
    if not path.is_file():
        raise ValueError(f"Unknown AI edit session_id: {session_id}")
    session = read_yaml(path)
    for edit in session.get("edits", []):
        if edit.get("edit_id") == edit_id:
            edit["review_status"] = review_status
            write_yaml(path, session)
            return edit
    raise ValueError(f"No edit found with edit_id={edit_id} in session {session_id}")


def apply_ai_edit_session(workspace: Path, session_id: str, *, cwd: Path | None = None) -> dict[str, Any]:
    """Apply only the edits explicitly marked `accepted`/`approved`, writing
    a new document version whose parent is the pre-session snapshot -- the
    original target file is never modified in place. Every applied edit's
    replacement text is wrapped in a plain-text `[[AI-EDIT-START]] ...
    [[AI-EDIT-END]]` marker (`engine.grounding.wrap_ai_edit_span`) so it
    stays visibly distinguishable from the surrounding human-authored prose
    (AGENTS.md Core Rule item 4), directly in the raw file -- not just a
    UI-only affordance that disappears the moment someone opens the file in
    a plain editor.
    """
    session = get_ai_edit_session(workspace, session_id)
    resolved = resolve_document_target(workspace, session["target"], cwd=cwd)
    text = resolved.path.read_text(encoding="utf-8", errors="replace")

    approved = [edit for edit in session.get("edits", []) if edit.get("review_status") in {"accepted", "approved"}]
    applied = 0
    skipped_not_found = []
    for edit in approved:
        original = edit["original_text"]
        if original and original in text:
            text = text.replace(original, wrap_ai_edit_span(edit["proposed_text"]), 1)
            applied += 1
        else:
            skipped_not_found.append(edit["edit_id"])

    output_path = resolved.path.with_name(f"{resolved.path.stem}.ai-edited{resolved.path.suffix}")
    output_path.write_text(text, encoding="utf-8")

    applied_version = create_document_version(
        workspace,
        str(output_path),
        creation_reason="ai_edit_session_apply",
        source_command="ai edit-session apply",
        parent_version_id=session["source_version_id"],
        model_metadata={"model": session.get("model"), "response_id": session.get("response_id")},
        cwd=cwd,
    )
    report = {
        "version": 1,
        "session_id": session_id,
        "output_path": str(output_path),
        "original_document_modified": False,
        "applied_edit_count": applied,
        "skipped_edit_count": len(session.get("edits", [])) - applied,
        "skipped_not_found_in_current_text": skipped_not_found,
        "document_version_id": applied_version["version_id"],
        "source_snapshot_version_id": session["source_version_id"],
    }
    return report
