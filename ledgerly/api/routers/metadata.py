from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ok
from ledgerly.engine.metadata import extract_citation_metadata
from ledgerly.engine.metadata_quality import (
    build_keyword_index,
    citation_consistency_report,
    duplicate_metadata_report,
)


router = APIRouter()


class MetadataExtractRequest(BaseModel):
    status: Optional[str] = None


@router.post("/extract")
def metadata_extract(payload: MetadataExtractRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    result = extract_citation_metadata(workspace, status=payload.status)
    return ok({"processed": result.processed, "updated": result.updated})


@router.get("/validate")
def metadata_validate(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(citation_consistency_report(workspace))


@router.get("/duplicates")
def metadata_duplicates(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(duplicate_metadata_report(workspace))


@router.post("/index")
def metadata_index(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(build_keyword_index(workspace))
