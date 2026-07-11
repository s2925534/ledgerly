from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from researchboss.api.deps import resolve_workspace
from researchboss.api.envelope import ApiError, ok
from researchboss.engine.derived_text import build_derived_text_snapshot


router = APIRouter()


@router.post("/{version_id}")
def derived_text_build(version_id: str, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Build (or rebuild) a derived text snapshot with paragraph/sentence anchors for a document version."""
    try:
        snapshot = build_derived_text_snapshot(workspace, version_id)
    except ValueError as exc:
        status_code = 404 if "Unknown document version_id" in str(exc) else 400
        raise ApiError("derived_text_build_failed", str(exc), status_code=status_code) from exc
    return ok(snapshot)
