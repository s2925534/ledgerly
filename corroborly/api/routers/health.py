from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check with no workspace or auth dependency.

    Kept outside `/api/v1` and outside workspace resolution so NAS deploy/update
    health checks succeed independently of login state or workspace validity.
    """
    return {"status": "ok"}
