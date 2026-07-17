from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from corroborly.core.yamlio import read_yaml
from corroborly.api.deps import resolve_workspace
from corroborly.api.envelope import ApiError, ok
from corroborly.engine.research_questions import (
    QUESTION_TYPES,
    add_research_question_candidate,
    approve_research_question,
    archive_research_question,
    assess_research_question_readiness,
    check_research_question_readiness,
    compose_research_question,
    list_research_questions,
    reject_research_question,
    split_candidate_relations,
)


router = APIRouter()


@router.get("")
def rqs_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_research_questions(workspace))


class RqCheckRequest(BaseModel):
    rq_id: Optional[str] = None


@router.post("/check")
def rqs_check(payload: RqCheckRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        report = check_research_question_readiness(workspace, rq_id=payload.rq_id)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok(report)


@router.post("/{rq_id}/approve")
def rqs_approve(rq_id: str, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        approve_research_question(workspace, rq_id)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "approved"})


class RqRejectRequest(BaseModel):
    reason: str = ""


@router.post("/{rq_id}/reject")
def rqs_reject(rq_id: str, payload: RqRejectRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        reject_research_question(workspace, rq_id, reason=payload.reason)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "rejected"})


@router.post("/{rq_id}/archive")
def rqs_archive(rq_id: str, payload: RqRejectRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        archive_research_question(workspace, rq_id, reason=payload.reason)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "archived"})


class RqWizardPreviewRequest(BaseModel):
    scope: str = ""
    relation: str
    question_type: str


@router.post("/wizard/preview")
def rqs_wizard_preview(payload: RqWizardPreviewRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Stateless preview step of the web equivalent of `corroborly rqs wizard`
    (TODO.md Phase 28's "multi-step web UI flow" item): composes each
    candidate question from the wizard's answers so far and scores its
    deterministic readiness, without saving anything -- mirrors the CLI's
    per-candidate readiness preview shown before its "Save this?" prompt.
    The "one guiding question at a time" step-through is a client-side
    concern (no server-side wizard session exists, matching this API's
    existing stateless-per-request convention); this route only needs the
    final relation/scope/question_type answers, not the ones before them.
    """
    if payload.question_type not in QUESTION_TYPES:
        allowed = ", ".join(sorted(QUESTION_TYPES))
        raise ApiError("invalid_question_type", f"Invalid question_type: {payload.question_type!r}. Expected one of: {allowed}", status_code=400)
    if not payload.relation.strip():
        raise ApiError("missing_relation", "relation is required.", status_code=400)

    project_type = str(read_yaml(workspace / "research-context.yaml").get("project", {}).get("type", ""))
    candidates = []
    for phrase in split_candidate_relations(payload.relation):
        question = compose_research_question(phrase, payload.scope, payload.question_type)
        readiness = assess_research_question_readiness(question, project_type=project_type)
        candidates.append({"question": question, "readiness": readiness})
    return ok({"candidates": candidates})


class RqWizardSaveRequest(BaseModel):
    question: str
    hypothesis: str = ""
    question_type: str
    proof_criteria: str = ""
    disproof_criteria: str = ""


@router.post("/wizard/save")
def rqs_wizard_save(payload: RqWizardSaveRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Saves one previewed candidate as a draft research question -- called once
    per candidate the user chooses to keep, mirroring the CLI wizard's
    per-candidate "Save this as a draft research question?" confirm loop.
    """
    try:
        record = add_research_question_candidate(
            workspace,
            payload.question,
            hypothesis=payload.hypothesis or None,
            question_type=payload.question_type or None,
            proof_criteria=payload.proof_criteria or None,
            disproof_criteria=payload.disproof_criteria or None,
        )
    except ValueError as exc:
        raise ApiError("rq_wizard_save_failed", str(exc), status_code=400) from exc
    return ok(record)
