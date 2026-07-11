from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from researchboss.api.envelope import ApiError
from researchboss.api.routers import (
    artefacts,
    backup,
    claims,
    conversion,
    data,
    doc,
    export,
    health,
    metadata,
    project_log,
    projects,
    reports,
    rqs,
    sources,
    zotero,
)


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
    app.include_router(sources.router, prefix="/api/v1/sources", tags=["sources"])
    app.include_router(conversion.router, prefix="/api/v1/conversion", tags=["conversion"])
    app.include_router(metadata.router, prefix="/api/v1/metadata", tags=["metadata"])
    app.include_router(data.router, prefix="/api/v1/data", tags=["data"])
    app.include_router(artefacts.router, prefix="/api/v1/artefacts", tags=["artefacts"])
    app.include_router(claims.router, prefix="/api/v1/claims", tags=["claims"])
    app.include_router(rqs.router, prefix="/api/v1/rqs", tags=["research-questions"])
    app.include_router(zotero.router, prefix="/api/v1/zotero", tags=["zotero"])
    app.include_router(doc.router, prefix="/api/v1/doc", tags=["document-vault"])
    app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
    app.include_router(export.router, prefix="/api/v1/export", tags=["export"])
    app.include_router(backup.router, prefix="/api/v1/backup", tags=["backup"])
    app.include_router(project_log.router, prefix="/api/v1", tags=["project-log"])
    return app


app = create_app()
