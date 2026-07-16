from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from ledgerly.core.constants import WORKSPACE_FILES
from ledgerly.core.yamlio import read_yaml, write_yaml


NOTE_KINDS = {"note", "meeting", "transcript"}

_TIMESTAMP_LINE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")
_CUE_NUMBER_LINE = re.compile(r"^\d+$")


def _ledger_path(workspace: Path) -> Path:
    return workspace / WORKSPACE_FILES.personal_notes_ledger


def list_notes(workspace: Path, *, kind: Optional[str] = None, tag: Optional[str] = None) -> list[dict[str, Any]]:
    ledger = read_yaml(_ledger_path(workspace))
    notes = [note for note in ledger.get("notes", []) if isinstance(note, dict)]
    if kind is not None:
        notes = [note for note in notes if note.get("kind") == kind]
    if tag is not None:
        notes = [note for note in notes if tag in (note.get("tags") or [])]
    return notes


def add_note(
    workspace: Path,
    text: str,
    *,
    kind: str = "note",
    tags: Optional[list[str]] = None,
    source_label: str = "",
) -> dict[str, Any]:
    """Add a personal note, meeting note, or transcript to the workspace's own note store.

    Distinct from per-source notes and supervisor/stakeholder feedback --
    this is the user's own working material, not tied to a single accepted
    source. Never sent anywhere; stored as plain workspace YAML like
    everything else, only usable as AI context once AI is explicitly
    opted in (see AGENTS.md's Core Rule: No Hallucinations).
    """
    if kind not in NOTE_KINDS:
        allowed = ", ".join(sorted(NOTE_KINDS))
        raise ValueError(f"Invalid note kind: {kind!r}. Expected one of: {allowed}")
    text = text.strip()
    if not text:
        raise ValueError("Note text is required.")

    ledger_path = _ledger_path(workspace)
    ledger = read_yaml(ledger_path)
    notes = [note for note in ledger.get("notes", []) if isinstance(note, dict)]
    note = {
        "id": f"note-{len(notes) + 1:03d}",
        "kind": kind,
        "text": text,
        "tags": tags or [],
        "source_label": source_label,
    }
    notes.append(note)
    ledger["notes"] = notes
    ledger.setdefault("version", 1)
    write_yaml(ledger_path, ledger)
    return note


def add_note_tag(workspace: Path, note_id: str, tag: str) -> dict[str, Any]:
    tag = tag.strip()
    if not tag:
        raise ValueError("Tag cannot be empty")
    ledger_path = _ledger_path(workspace)
    ledger = read_yaml(ledger_path)
    notes = [note for note in ledger.get("notes", []) if isinstance(note, dict)]
    for note in notes:
        if note.get("id") == note_id:
            tags = list(note.get("tags") or [])
            if tag not in tags:
                tags.append(tag)
            note["tags"] = tags
            ledger["notes"] = notes
            write_yaml(ledger_path, ledger)
            return note
    raise ValueError(f"Unknown note_id: {note_id}")


def search_notes(workspace: Path, query: str) -> list[dict[str, Any]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    matches = []
    for note in list_notes(workspace):
        haystack = " ".join(
            [note.get("text", ""), note.get("source_label", ""), " ".join(note.get("tags") or [])]
        ).lower()
        if all(term in haystack for term in terms):
            matches.append(note)
    return matches


def _strip_caption_markup(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper() == "WEBVTT":
            continue
        if _TIMESTAMP_LINE.match(stripped):
            continue
        if _CUE_NUMBER_LINE.match(stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def import_transcript(
    workspace: Path,
    path: Path,
    *,
    kind: str = "transcript",
    source_label: str = "",
) -> dict[str, Any]:
    """Deterministically normalize a transcript export (plain text, VTT, or SRT) into the note store.

    No AI processing at import time — this only strips WebVTT/SRT cue
    numbers and timestamp lines and joins the remaining spoken-text lines.
    """
    if not path.is_file():
        raise ValueError(f"Transcript file does not exist: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_caption_markup(raw) if path.suffix.lower() in {".vtt", ".srt"} else raw.strip()
    if not text:
        raise ValueError(f"No text content found in transcript file: {path}")
    return add_note(workspace, text, kind=kind, source_label=source_label or path.name)
