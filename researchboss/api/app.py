from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from researchboss.api.envelope import ApiError
from researchboss.api.routers import doc, health, projects


def create_app() -> FastAPI:
    """Build the local ResearchBoss FastAPI app.

    A thin transport layer over `researchboss.engine` functions: routes must not
    duplicate business logic, must not modify original source files, and must
    never write inside a local Zotero directory. See docs/api/CONTRACT.md.
    """
    app = FastAPI(title="ResearchBoss Local API")

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "data": None, "warnings": [], "errors": [{"code": exc.code, "message": exc.message}]},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "data": None,
                "warnings": [],
                "errors": [{"code": "invalid_request", "message": str(error)} for error in exc.errors()],
            },
        )

    app.include_router(health.router)
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
    app.include_router(doc.router, prefix="/api/v1/doc", tags=["document-vault"])
    return app


app = create_app()
