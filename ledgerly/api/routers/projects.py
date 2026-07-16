from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.engine.health import workspace_health_report
from ledgerly.engine.sources import source_counts
from ledgerly.engine.workspace import DEFAULT_CITATION_STYLE, init_workspace


router = APIRouter()


@router.get("/status")
def project_status(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(source_counts(workspace))


@router.get("/health")
def project_health(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(workspace_health_report(workspace))


class ResearchQuestionInit(BaseModel):
    question: str
    subquestions: list[str] = []
    status: Optional[str] = None


class ProjectInitRequest(BaseModel):
    workspace: str
    project_name: str
    project_type: str
    topic: str
    strict_evidence_mode: bool = True
    source_root: Optional[str] = None
    source_mode: str = "configure_later"
    artefact_root: Optional[str] = None
    research_questions: list[ResearchQuestionInit] = []
    supervisors: list[str] = []
    citation_style: str = DEFAULT_CITATION_STYLE
    custom_citation_style: Optional[str] = None
    primary_output_type: str = "notes"
    custom_primary_output_type: Optional[str] = None
    expects_data_files: str = "not sure"
    source_review_default: str = "pending_review"
    prevent_full_document_uploads: bool = True
    ai_preference: str = "no"


@router.post("/init")
def project_init(payload: ProjectInitRequest) -> dict[str, Any]:
    workspace = Path(payload.workspace).expanduser()
    if (workspace / "research-context.yaml").exists():
        raise ApiError(
            "workspace_already_exists",
            f"Workspace is already initialized: {payload.workspace}",
            status_code=409,
        )

    init_workspace(
        workspace,
        project_name=payload.project_name,
        project_type=payload.project_type,
        topic=payload.topic,
        strict_evidence_mode=payload.strict_evidence_mode,
        source_root=payload.source_root,
        source_mode=payload.source_mode,
        artefact_root=payload.artefact_root,
        research_questions=[question.model_dump() for question in payload.research_questions],
        supervisors=payload.supervisors,
        citation_style=payload.citation_style,
        custom_citation_style=payload.custom_citation_style,
        primary_output_type=payload.primary_output_type,
        custom_primary_output_type=payload.custom_primary_output_type,
        expects_data_files=payload.expects_data_files,
        source_review_default=payload.source_review_default,
        prevent_full_document_uploads=payload.prevent_full_document_uploads,
        ai_preference=payload.ai_preference,
    )
    return ok({"workspace": str(workspace.resolve())})
