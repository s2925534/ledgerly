from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from corroborly.api.deps import resolve_workspace
from corroborly.api.envelope import ApiError, ok
from corroborly.engine.backup import create_workspace_backup, inspect_backup


router = APIRouter()


class BackupCreateRequest(BaseModel):
    include_originals: bool = False


@router.post("")
def backup_create(payload: BackupCreateRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    backup_path = create_workspace_backup(workspace, include_originals=payload.include_originals)
    return ok({"backup_path": str(backup_path)})


@router.get("/inspect")
def backup_inspect_route(backup_path: str = Query(...)) -> dict[str, Any]:
    path = Path(backup_path).expanduser()
    if not path.is_file():
        raise ApiError("backup_not_found", f"Backup file does not exist: {backup_path}", status_code=404)
    return ok(inspect_backup(path))
