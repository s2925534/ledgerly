from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException


class ApiError(HTTPException):
    """Raised by route handlers; converted into the documented error envelope."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
        self.message = message


def ok(data: Any = None, *, warnings: Optional[list[str]] = None) -> dict[str, Any]:
    return {"ok": True, "data": data, "warnings": warnings or [], "errors": []}
