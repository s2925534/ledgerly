from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Header, Query

from corroborly.api.auth import SESSION_COOKIE_NAME, auth_configured, extract_token, session_is_valid
from corroborly.api.envelope import ApiError


def resolve_workspace_path(workspace: str) -> Path:
    """Resolve a raw workspace path string, enforcing the same
    CORROBORLY_WORKSPACE_ROOT sandbox as the `resolve_workspace` FastAPI
    dependency below. Factored out so any route needing more than one
    workspace path (e.g. multi-workspace comparison) can validate each one
    the same way instead of accepting arbitrary paths reachable by the
    server process.

    When CORROBORLY_WORKSPACE_ROOT is set (a deployed instance pointed at a
    mounted NAS volume), every workspace must resolve inside that root —
    relative paths are joined to it, and absolute paths outside it are
    rejected. Without it, behavior matches local-first, single-user CLI use:
    any absolute (or cwd-relative) path is accepted, same as today.
    """
    raw_path = Path(workspace).expanduser()
    root = os.environ.get("CORROBORLY_WORKSPACE_ROOT")

    if root:
        root_path = Path(root).expanduser().resolve()
        candidate = raw_path if raw_path.is_absolute() else root_path / raw_path
        candidate = candidate.resolve()
        if candidate != root_path and root_path not in candidate.parents:
            raise ApiError(
                "workspace_outside_root",
                f"Workspace must be inside CORROBORLY_WORKSPACE_ROOT ({root_path}): {workspace}",
                status_code=400,
            )
        path = candidate
    else:
        path = raw_path if raw_path.is_absolute() else raw_path.resolve()

    if not path.is_dir():
        raise ApiError("workspace_not_found", f"Workspace does not exist: {workspace}", status_code=404)
    return path


def resolve_workspace(
    workspace: str = Query(
        ...,
        description=(
            "Absolute local workspace path, or a path relative to CORROBORLY_WORKSPACE_ROOT "
            "when that is configured."
        ),
    ),
) -> Path:
    """Resolve the `workspace` query parameter without any interactive discovery.

    CLI commands may prompt to discover or select a workspace; the API has no
    interactive surface, so callers must always pass an explicit workspace path.
    """
    return resolve_workspace_path(workspace)


def require_session(
    authorization: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> None:
    """Require a valid session on every protected route.

    Fails closed (503) when no CORROBORLY_API_PASSWORD is configured, rather
    than silently allowing unauthenticated access.
    """
    if not auth_configured():
        raise ApiError(
            "auth_not_configured",
            "CORROBORLY_API_PASSWORD is not set. Configure it before using this API.",
            status_code=503,
        )
    token = extract_token(authorization, session_cookie)
    if not token or not session_is_valid(token):
        raise ApiError(
            "unauthorized",
            "A valid session is required. Log in via POST /api/v1/auth/login.",
            status_code=401,
        )
