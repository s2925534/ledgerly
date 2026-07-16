from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.progress_log import record_progress_event


ARTEFACT_REVIEW_STATUSES = {"pending_review", "reviewed", "needs_revision", "accepted", "not_required"}


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
            artefact["review_status"] = status
            artefact["requires_user_review"] = status in {"pending_review", "needs_revision"}
            registry["artefacts"] = artefacts
            write_yaml(registry_path, registry)
            record_progress_event(workspace, kind="artefact_review_status_changed", entity_id=artefact_id, detail=status)
            return
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
