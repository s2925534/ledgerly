from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ok
from ledgerly.engine.export import export_evidence_bundle


router = APIRouter()


@router.post("/evidence")
def export_evidence(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    bundle_path = export_evidence_bundle(workspace)
    return ok({"bundle_path": str(bundle_path)})
