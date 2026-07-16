from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.core.yamlio import write_yaml
from ledgerly.engine.sources import iter_source_files
from ledgerly.engine.zotero import (
    attachment_health_report,
    duplicate_metadata_candidates,
    ensure_path_not_in_zotero,
    export_bibtex_from_metadata,
    fulltext_availability_report,
    keyword_terms,
    list_zotero_collections,
    metadata_quality_report,
    resolve_zotero_paths,
    search_zotero_storage,
    write_zotero_config,
    zotero_metadata_snapshot,
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


def _require_zotero_root(workspace: Path) -> Path:
    try:
        _storage_root, zotero_root, _zotero_config = resolve_zotero_paths(workspace)
    except ValueError as exc:
        raise ApiError("zotero_not_configured", str(exc)) from exc
    if not zotero_root:
        raise ApiError("zotero_root_not_found", "Could not derive Zotero root from workspace configuration.", status_code=404)
    return zotero_root


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


class ZoteroLocalSelectCollectionsRequest(BaseModel):
    collection_keys: list[str]
    include_subcollections: bool = True


@router.post("/local/collections/select")
def zotero_local_select_collections(
    payload: ZoteroLocalSelectCollectionsRequest,
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    """Configure selected local Zotero collections for future scans (mirrors `ledgerly zotero select-collections`)."""
    zotero_root = _require_zotero_root(workspace)
    known = {item.key: item for item in list_zotero_collections(zotero_root)}
    missing = [key for key in payload.collection_keys if key not in known]
    if missing:
        raise ApiError("unknown_collection_keys", f"Unknown Zotero collection keys: {', '.join(missing)}", status_code=404)

    selected = [{"key": key, "name": known[key].name, "path": known[key].path} for key in payload.collection_keys]
    write_zotero_config(
        workspace,
        {
            "mode": "selected_collections",
            "selected_collections": selected,
            "include_subcollections": payload.include_subcollections,
        },
    )
    return ok({"collection_keys": payload.collection_keys, "include_subcollections": payload.include_subcollections})


@router.post("/local/use-entire-library")
def zotero_local_use_entire_library(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Configure local Zotero scans to use the entire storage library (mirrors `ledgerly zotero use-entire-library`)."""
    write_zotero_config(workspace, {"mode": "entire_library", "selected_collections": []})
    return ok({"mode": "entire_library"})


@router.get("/local/metadata-report")
def zotero_local_metadata_report(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Report missing local Zotero metadata fields from read-only zotero.sqlite."""
    zotero_root = _require_zotero_root(workspace)
    report = metadata_quality_report(zotero_root)
    write_yaml(workspace / "outputs" / "validation" / "zotero-metadata-report.yaml", report)
    return ok(report)


@router.get("/local/attachment-health")
def zotero_local_attachment_health(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Compare local Zotero storage files with attachment records in zotero.sqlite."""
    zotero_root = _require_zotero_root(workspace)
    storage_root, _zotero_root, _zotero_config = resolve_zotero_paths(workspace)
    paths = list(iter_source_files(storage_root))
    report = attachment_health_report(zotero_root, storage_root, paths)
    write_yaml(workspace / "outputs" / "validation" / "zotero-attachment-health.yaml", report)
    return ok(report)


@router.get("/local/fulltext-report")
def zotero_local_fulltext_report(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Report which local Zotero storage files have `.zotero-ft-cache` available."""
    storage_root, _zotero_root, _zotero_config = resolve_zotero_paths(workspace)
    paths = list(iter_source_files(storage_root))
    report = fulltext_availability_report(storage_root, paths)
    write_yaml(workspace / "outputs" / "validation" / "zotero-fulltext-report.yaml", report)
    return ok(report)


@router.get("/local/duplicates")
def zotero_local_duplicates(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Find possible local Zotero metadata duplicates by DOI or title/year."""
    zotero_root = _require_zotero_root(workspace)
    report = {"version": 1, "duplicates": duplicate_metadata_candidates(zotero_root)}
    write_yaml(workspace / "outputs" / "validation" / "zotero-duplicates.yaml", report)
    return ok(report)


@router.get("/local/snapshot")
def zotero_local_snapshot(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Write a reproducible local Zotero metadata snapshot into the workspace."""
    zotero_root = _require_zotero_root(workspace)
    output_path = workspace / "sources_metadata" / "zotero-snapshot.yaml"
    ensure_path_not_in_zotero(output_path, zotero_root)
    snapshot = zotero_metadata_snapshot(zotero_root)
    write_yaml(output_path, snapshot)
    return ok({"snapshot_path": str(output_path), "snapshot": snapshot})


@router.get("/local/export-bibtex")
def zotero_local_export_bibtex(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Export conservative BibTeX from local Zotero SQLite metadata."""
    zotero_root = _require_zotero_root(workspace)
    output_path = workspace / "outputs" / "reports" / "zotero-references.bib"
    ensure_path_not_in_zotero(output_path, zotero_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = export_bibtex_from_metadata(zotero_root)
    output_path.write_text(content, encoding="utf-8")
    entries = content.count("\n@") + (1 if content.startswith("@") else 0)
    return ok({"bibtex_path": str(output_path), "entries": entries})


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
