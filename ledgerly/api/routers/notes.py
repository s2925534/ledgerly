from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.engine.notes import add_note, add_note_tag, import_transcript, list_notes, search_notes


router = APIRouter()


@router.get("")
def notes_list(
    workspace: Path = Depends(resolve_workspace),
    kind: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
) -> dict[str, Any]:
    return ok(list_notes(workspace, kind=kind, tag=tag))


class NoteAddRequest(BaseModel):
    text: str
    kind: str = "note"
    tags: list[str] = []
    source_label: str = ""


@router.post("")
def notes_add(payload: NoteAddRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        note = add_note(workspace, payload.text, kind=payload.kind, tags=payload.tags, source_label=payload.source_label)
    except ValueError as exc:
        raise ApiError("invalid_note", str(exc)) from exc
    return ok(note)


class NoteTagRequest(BaseModel):
    tag: str


@router.post("/{note_id}/tags")
def notes_add_tag(note_id: str, payload: NoteTagRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        note = add_note_tag(workspace, note_id, payload.tag)
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("Unknown note_id") else 400
        raise ApiError("invalid_note_tag", str(exc), status_code=status_code) from exc
    return ok(note)


@router.get("/search")
def notes_search(query: str = Query(..., min_length=1), workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(search_notes(workspace, query))


class NoteImportTranscriptRequest(BaseModel):
    path: str
    kind: str = "transcript"
    source_label: str = ""


@router.post("/import-transcript")
def notes_import_transcript(
    payload: NoteImportTranscriptRequest, workspace: Path = Depends(resolve_workspace)
) -> dict[str, Any]:
    try:
        note = import_transcript(
            workspace, Path(payload.path).expanduser(), kind=payload.kind, source_label=payload.source_label
        )
    except ValueError as exc:
        status_code = 404 if "does not exist" in str(exc) else 400
        raise ApiError("invalid_transcript_import", str(exc), status_code=status_code) from exc
    return ok(note)
