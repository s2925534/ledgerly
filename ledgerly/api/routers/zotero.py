from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.engine.sources import iter_source_files
from ledgerly.engine.zotero import (
    keyword_terms,
    list_zotero_collections,
    resolve_zotero_paths,
    search_zotero_storage,
    write_zotero_config,
)
from ledgerly.engine.zotero_api import (
    ZoteroApiError,
    clear_zotero_api_credentials,
    save_zotero_api_credentials,
    zotero_api_collections,
    zotero_api_credentials,
    zotero_api_readiness,
)


router = APIRouter()


@router.get("/local/collections")
def zotero_local_collections(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        _storage_root, zotero_root, _zotero_config = resolve_zotero_paths(workspace)
    except ValueError as exc:
        raise ApiError("zotero_not_configured", str(exc)) from exc
    if not zotero_root:
        raise ApiError("zotero_root_not_found", "Could not derive Zotero root from workspace configuration.", status_code=404)

    collections = list_zotero_collections(zotero_root)
    return ok(
        [{"key": item.key, "name": item.name, "path": item.path, "item_count": item.item_count} for item in collections]
    )


@router.get("/local/search")
def zotero_local_search(
    query: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    try:
        storage_root, zotero_root, _zotero_config = resolve_zotero_paths(workspace)
    except ValueError as exc:
        raise ApiError("zotero_not_configured", str(exc)) from exc
    if not storage_root.exists():
        raise ApiError(
            "zotero_storage_not_found", f"Zotero storage root does not exist: {storage_root}", status_code=404
        )

    terms = keyword_terms(query)
    if not terms:
        raise ApiError("empty_search_query", "Provide at least one keyword.")

    candidates = list(iter_source_files(storage_root))
    hits = search_zotero_storage(storage_root, terms, candidates, limit=limit, zotero_root=zotero_root)
    return ok(
        [
            {
                "file_path": str(hit.file_path),
                "storage_key": hit.storage_key,
                "score": hit.score,
                "matched_terms": hit.matched_terms,
                "matched_in": hit.matched_in,
                "has_fulltext_cache": hit.has_fulltext_cache,
                "snippet": hit.snippet,
            }
            for hit in hits
        ]
    )


class ZoteroApiCredentialsRequest(BaseModel):
    api_key: str
    user_id: str


@router.post("/api/credentials")
def zotero_web_api_save_credentials(
    payload: ZoteroApiCredentialsRequest,
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    """Link a Zotero Web API account by saving credentials into the workspace's `.env`.

    Never echoes, logs, or returns the submitted key or user ID — only
    confirms the save succeeded. Call `GET /api/test` afterwards to verify
    the saved credentials actually work.
    """
    try:
        save_zotero_api_credentials(workspace, payload.api_key, payload.user_id)
    except ZoteroApiError as exc:
        raise ApiError("zotero_credentials_invalid", str(exc)) from exc
    return ok({"configured": True})


@router.delete("/api/credentials")
def zotero_web_api_clear_credentials(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Unlink a Zotero Web API account by removing saved credentials from `.env`."""
    clear_zotero_api_credentials(workspace)
    return ok({"configured": False})


@router.get("/api/test")
def zotero_web_api_test(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        credentials = zotero_api_credentials(workspace)
        report = zotero_api_readiness(credentials)
    except ZoteroApiError as exc:
        raise ApiError("zotero_api_error", str(exc)) from exc
    return ok(report)


@router.get("/api/collections")
def zotero_web_api_collections(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        credentials = zotero_api_credentials(workspace)
        collections = zotero_api_collections(credentials)
    except ZoteroApiError as exc:
        raise ApiError("zotero_api_error", str(exc)) from exc
    return ok(collections)


class ZoteroApiSelectCollectionsRequest(BaseModel):
    collection_keys: list[str]
    include_subcollections: bool = True


@router.post("/api/collections/select")
def zotero_web_api_select_collections(
    payload: ZoteroApiSelectCollectionsRequest,
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    """Store the selected Web API collection keys in the workspace only.

    Never calls a Zotero write endpoint and never writes inside the local
    Zotero directory.
    """
    write_zotero_config(
        workspace,
        {
            "api_mode": "selected_collections",
            "api_selected_collections": [{"key": key} for key in payload.collection_keys],
            "api_include_subcollections": payload.include_subcollections,
            "api_access": "read_only",
        },
    )
    return ok({"collection_keys": payload.collection_keys, "include_subcollections": payload.include_subcollections})
