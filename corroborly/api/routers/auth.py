from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Cookie, Depends, Header, Response
from pydantic import BaseModel

from corroborly.api.auth import (
    REMEMBER_ME_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    CredentialChangeError,
    auth_configured,
    clear_all_sessions,
    create_session,
    extract_token,
    invalidate_session,
    set_credentials,
    verify_credentials,
)
from corroborly.api.deps import require_session
from corroborly.api.envelope import ApiError, ok


router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    if not auth_configured():
        raise ApiError(
            "auth_not_configured",
            "CORROBORLY_API_USERNAME and CORROBORLY_API_PASSWORD are not set. Configure both before logging in.",
            status_code=503,
        )
    if not verify_credentials(payload.username, payload.password):
        raise ApiError("invalid_credentials", "Incorrect username or password.", status_code=401)

    token, expires_at = create_session(REMEMBER_ME_TTL_SECONDS if payload.remember else None)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=max(1, int(expires_at - time.time())),
    )
    return ok({"token": token, "expires_at": expires_at})


@router.post("/logout")
def logout(
    response: Response,
    authorization: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> dict[str, Any]:
    token = extract_token(authorization, session_cookie)
    if token:
        invalidate_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return ok({"logged_out": True})


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", dependencies=[Depends(require_session)])
def change_password(payload: ChangePasswordRequest, response: Response) -> dict[str, Any]:
    """Self-service credential change for the single shared login (TODO.md
    Phase 9's theme/login-options item, 2026-07-17) -- not a per-account
    "forgot password" flow, since no per-account system exists (that's
    Phase 29, not started). Requires the current password even though the
    caller already has a valid session, as defense in depth against a
    hijacked session token. Invalidates every existing session on success,
    including the caller's own -- a fresh login with the new password is
    required, everywhere.
    """
    from corroborly.api.auth import _configured_username

    username = _configured_username() or ""
    if not verify_credentials(username, payload.current_password):
        raise ApiError("invalid_credentials", "Current password is incorrect.", status_code=401)
    if not payload.new_password:
        raise ApiError("invalid_new_password", "New password must not be empty.", status_code=400)

    try:
        set_credentials(payload.new_password)
    except CredentialChangeError as exc:
        raise ApiError("credential_change_failed", str(exc), status_code=409) from exc

    clear_all_sessions()
    response.delete_cookie(SESSION_COOKIE_NAME)
    return ok({"changed": True})
