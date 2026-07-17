from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from corroborly.api.deps import resolve_workspace
from corroborly.api.envelope import ApiError, ok
from corroborly.engine.research_stages import list_stages, set_stage_status, set_stage_target_date, stages_ics

router = APIRouter()


@router.get("")
def stages_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_stages(workspace))


class StageStatusRequest(BaseModel):
    status: str


@router.post("/{stage_id}/status")
def stages_set_status(
    stage_id: str, payload: StageStatusRequest, workspace: Path = Depends(resolve_workspace)
) -> dict[str, Any]:
    try:
        stage = set_stage_status(workspace, stage_id, payload.status)
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("Unknown stage_id") else 400
        raise ApiError("invalid_stage_status", str(exc), status_code=status_code) from exc
    return ok(stage)


class StageTargetDateRequest(BaseModel):
    target_date: Optional[str] = None


@router.post("/{stage_id}/target-date")
def stages_set_target_date(
    stage_id: str, payload: StageTargetDateRequest, workspace: Path = Depends(resolve_workspace)
) -> dict[str, Any]:
    try:
        stage = set_stage_target_date(workspace, stage_id, payload.target_date)
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("Unknown stage_id") else 400
        raise ApiError("invalid_stage_target_date", str(exc), status_code=status_code) from exc
    return ok(stage)


@router.get("/ics")
def stages_ics_route(workspace: Path = Depends(resolve_workspace)) -> PlainTextResponse:
    return PlainTextResponse(stages_ics(workspace), media_type="text/calendar")
