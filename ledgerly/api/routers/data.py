from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ok
from ledgerly.engine.data import data_source_counts, list_data_sources, profile_data_sources


router = APIRouter()


class DataProfileRequest(BaseModel):
    status: Optional[str] = None


@router.post("/profile")
def data_profile(payload: DataProfileRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    result = profile_data_sources(workspace, status=payload.status)
    return ok({"processed": result.processed, "profiled": result.profiled, "skipped": result.skipped})


@router.get("")
def data_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_data_sources(workspace))


@router.get("/status")
def data_status(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(data_source_counts(workspace))
