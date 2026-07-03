from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from researchboss.core.yamlio import read_yaml, write_yaml


def _paths(workspace: Path) -> tuple[Path, Path, Path]:
    return (
        workspace / "research-questions.yaml",
        workspace / "research-question-candidates.yaml",
        workspace / "rejected-research-questions.yaml",
    )


def list_research_questions(workspace: Path) -> dict[str, list[dict[str, Any]]]:
    approved_path, candidates_path, rejected_path = _paths(workspace)
    return {
        "approved": list(read_yaml(approved_path).get("research_questions", [])),
        "candidates": list(read_yaml(candidates_path).get("candidates", [])),
        "rejected": list(read_yaml(rejected_path).get("rejected", [])),
    }


def _find_and_remove(items: list[dict[str, Any]], rq_id: str) -> Optional[dict[str, Any]]:
    for index, item in enumerate(items):
        if item.get("id") == rq_id:
            return items.pop(index)
    return None


def approve_research_question(workspace: Path, rq_id: str) -> None:
    approved_path, candidates_path, _rejected_path = _paths(workspace)
    approved_doc = read_yaml(approved_path)
    candidates_doc = read_yaml(candidates_path)
    approved = list(approved_doc.get("research_questions", []))
    candidates = list(candidates_doc.get("candidates", []))
    item = _find_and_remove(candidates, rq_id)
    if item is None:
        raise ValueError(f"Unknown candidate research question: {rq_id}")
    item.pop("status", None)
    approved.append(item)
    approved_doc["research_questions"] = approved
    candidates_doc["candidates"] = candidates
    write_yaml(approved_path, approved_doc)
    write_yaml(candidates_path, candidates_doc)


def reject_research_question(workspace: Path, rq_id: str, *, reason: str = "") -> None:
    _move_to_rejected(workspace, rq_id, status="rejected", reason=reason)


def archive_research_question(workspace: Path, rq_id: str, *, reason: str = "") -> None:
    _move_to_rejected(workspace, rq_id, status="archived", reason=reason)


def _move_to_rejected(workspace: Path, rq_id: str, *, status: str, reason: str) -> None:
    approved_path, candidates_path, rejected_path = _paths(workspace)
    approved_doc = read_yaml(approved_path)
    candidates_doc = read_yaml(candidates_path)
    rejected_doc = read_yaml(rejected_path)
    approved = list(approved_doc.get("research_questions", []))
    candidates = list(candidates_doc.get("candidates", []))
    item = _find_and_remove(candidates, rq_id) or _find_and_remove(approved, rq_id)
    if item is None:
        raise ValueError(f"Unknown research question: {rq_id}")
    item["status"] = status
    item["reason"] = reason
    rejected = list(rejected_doc.get("rejected", []))
    rejected.append(item)
    approved_doc["research_questions"] = approved
    candidates_doc["candidates"] = candidates
    rejected_doc["rejected"] = rejected
    write_yaml(approved_path, approved_doc)
    write_yaml(candidates_path, candidates_doc)
    write_yaml(rejected_path, rejected_doc)
