from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.progress_log import record_progress_event


ARTEFACT_REVIEW_STATUSES = {"pending_review", "reviewed", "needs_revision", "accepted", "not_required"}
PAPER_REVIEW_GATE_STATUSES = {"requires_validate", "cleared"}


def list_artefacts(workspace: Path) -> list[dict[str, Any]]:
    registry = read_yaml(workspace / "artefact-registry.yaml")
    return [item for item in registry.get("artefacts", []) if isinstance(item, dict)]


def register_artefact(
    workspace: Path,
    *,
    title: str,
    artefact_type: str,
    path: Path,
    linked_sources: list[str] | None = None,
    linked_research_questions: list[str] | None = None,
    requires_user_review: bool = True,
) -> dict[str, Any]:
    registry_path = workspace / "artefact-registry.yaml"
    registry = read_yaml(registry_path)
    artefacts = [item for item in registry.get("artefacts", []) if isinstance(item, dict)]
    artefact_id = f"artefact-{len(artefacts) + 1:03d}"
    record = {
        "id": artefact_id,
        "title": title,
        "type": artefact_type,
        "path": str(path),
        "linked_sources": linked_sources or [],
        "linked_research_questions": linked_research_questions or [],
        "ai_generated": False,
        "requires_user_review": requires_user_review,
        "review_status": "pending_review" if requires_user_review else "not_required",
    }
    artefacts.append(record)
    registry["artefacts"] = artefacts
    write_yaml(registry_path, registry)
    record_progress_event(workspace, kind="artefact_registered", entity_id=artefact_id, detail=title)
    return record


def set_artefact_review_status(workspace: Path, artefact_id: str, status: str) -> None:
    if status not in ARTEFACT_REVIEW_STATUSES:
        allowed = ", ".join(sorted(ARTEFACT_REVIEW_STATUSES))
        raise ValueError(f"Invalid artefact review status: {status!r}. Expected one of: {allowed}")
    registry_path = workspace / "artefact-registry.yaml"
    registry = read_yaml(registry_path)
    artefacts = [item for item in registry.get("artefacts", []) if isinstance(item, dict)]
    for artefact in artefacts:
        if artefact.get("id") == artefact_id:
            if artefact.get("paper_review_gate") == "requires_validate" and status in {"reviewed", "accepted"}:
                raise ValueError(
                    f"Artefact {artefact_id} is an AI-touched paper draft with an open review gate — it cannot be "
                    "marked reviewed/accepted this way. Run `ledgerly validate` against it, then "
                    "`ledgerly paper clear-review-gate` (AGENTS.md Core Rule: a paper must never silently become "
                    "final just because AI produced it)."
                )
            artefact["review_status"] = status
            artefact["requires_user_review"] = status in {"pending_review", "needs_revision"}
            registry["artefacts"] = artefacts
            write_yaml(registry_path, registry)
            record_progress_event(workspace, kind="artefact_review_status_changed", entity_id=artefact_id, detail=status)
            return
    raise ValueError(f"Unknown artefact_id: {artefact_id}")


def promote_ai_paper_draft(workspace: Path, artefact_id: str, applied_content_path: Path) -> dict[str, Any]:
    """Adopt an applied AI edit session's output as an AI-drafted paper's
    real content, and open its mandatory review gate (TODO.md Phase 28,
    per Pedro's explicit requirement): the artefact is marked
    `requires_user_review: true` / `paper_review_gate: "requires_validate"`,
    and per `set_artefact_review_status` above, nothing except
    `clear_paper_review_gate` (which itself requires a genuine, up-to-date
    `ledgerly validate` run) can clear it. A paper must never silently
    become "final" just because AI produced it.
    """
    if not applied_content_path.is_file():
        raise ValueError(f"Applied content file does not exist: {applied_content_path}")
    registry_path = workspace / "artefact-registry.yaml"
    registry = read_yaml(registry_path)
    artefacts = [item for item in registry.get("artefacts", []) if isinstance(item, dict)]
    for artefact in artefacts:
        if artefact.get("id") == artefact_id:
            from ledgerly.engine.vault import create_document_version

            target_path = Path(str(artefact["path"]))
            pre_promotion_version = None
            if target_path.is_file():
                pre_promotion_version = create_document_version(
                    workspace, str(target_path), creation_reason="pre_ai_paper_draft_promotion_snapshot"
                )
            shutil.copy2(applied_content_path, target_path)
            create_document_version(
                workspace,
                str(target_path),
                creation_reason="ai_paper_draft_promoted",
                parent_version_id=pre_promotion_version.get("version_id") if pre_promotion_version else None,
            )
            artefact["ai_generated"] = True
            artefact["requires_user_review"] = True
            artefact["review_status"] = "pending_review"
            artefact["paper_review_gate"] = "requires_validate"
            registry["artefacts"] = artefacts
            write_yaml(registry_path, registry)
            record_progress_event(workspace, kind="ai_paper_draft_promoted", entity_id=artefact_id, detail="requires_validate")
            return artefact
    raise ValueError(f"Unknown artefact_id: {artefact_id}")


def clear_paper_review_gate(workspace: Path, artefact_id: str) -> dict[str, Any]:
    """The only way to clear an AI-touched paper draft's review gate: a
    real, up-to-date `ledgerly validate <target>` run must already exist
    for this exact artefact. "Up-to-date" is checked by file modification
    time (the validation report must be newer than the artefact's current
    content) rather than a passed-in report ID, so this can't be satisfied
    by a stale validation from before the AI draft was promoted or edited
    further -- re-running `validate` after any further change is required.
    """
    from ledgerly.engine.doc_validation import validation_report_path

    registry_path = workspace / "artefact-registry.yaml"
    registry = read_yaml(registry_path)
    artefacts = [item for item in registry.get("artefacts", []) if isinstance(item, dict)]
    for artefact in artefacts:
        if artefact.get("id") == artefact_id:
            if artefact.get("paper_review_gate") != "requires_validate":
                raise ValueError(f"Artefact {artefact_id} has no open review gate to clear.")
            target_path = Path(str(artefact["path"]))
            report_path = validation_report_path(workspace, target_path, ".yaml")
            if not report_path.is_file():
                raise ValueError(
                    f"No validation report found for {target_path}. Run `ledgerly validate` against it first."
                )
            if report_path.stat().st_mtime < target_path.stat().st_mtime:
                raise ValueError(
                    f"The validation report for {target_path} is older than the artefact's current content. "
                    "Run `ledgerly validate` again after the most recent edit."
                )
            artefact["paper_review_gate"] = "cleared"
            artefact["review_status"] = "reviewed"
            artefact["requires_user_review"] = False
            registry["artefacts"] = artefacts
            write_yaml(registry_path, registry)
            record_progress_event(workspace, kind="ai_paper_review_gate_cleared", entity_id=artefact_id, detail="cleared")
            return artefact
    raise ValueError(f"Unknown artefact_id: {artefact_id}")


def artefact_dependency_report(workspace: Path) -> dict[str, Any]:
    source_register = read_yaml(workspace / "source-register.yaml")
    sources = {source.get("source_id"): source for source in source_register.get("sources", []) if isinstance(source, dict)}
    approved_doc = read_yaml(workspace / "research-questions.yaml")
    approved_rqs = {
        rq.get("id")
        for rq in approved_doc.get("research_questions", [])
        if isinstance(rq, dict)
    }
    rows = []
    for artefact in list_artefacts(workspace):
        issues = []
        for source_id in artefact.get("linked_sources", []):
            source = sources.get(source_id)
            if not source:
                issues.append({"kind": "missing_source", "id": source_id})
            elif source.get("status") != "accepted":
                issues.append({"kind": "source_not_accepted", "id": source_id, "status": source.get("status")})
        for rq_id in artefact.get("linked_research_questions", []):
            if rq_id not in approved_rqs:
                issues.append({"kind": "rq_not_approved", "id": rq_id})
        rows.append({"artefact_id": artefact.get("id"), "status": "ok" if not issues else "needs_review", "issues": issues})
    report = {"version": 1, "artefacts": rows}
    write_yaml(workspace / "outputs" / "validation" / "artefact-dependencies.yaml", report)
    return report
