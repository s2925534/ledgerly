from __future__ import annotations

from pathlib import Path

from fastapi import Query

from researchboss.api.envelope import ApiError


def resolve_workspace(
    workspace: str = Query(..., description="Absolute local workspace path."),
) -> Path:
    """Resolve the `workspace` query parameter without any interactive discovery.

    CLI commands may prompt to discover or select a workspace; the API has no
    interactive surface, so callers must always pass an explicit workspace path.
    """
    path = Path(workspace).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if not path.is_dir():
        raise ApiError("workspace_not_found", f"Workspace does not exist: {workspace}", status_code=404)
    return path
