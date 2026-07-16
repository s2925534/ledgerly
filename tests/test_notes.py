from pathlib import Path

import pytest

from ledgerly.engine.notes import add_note, add_note_tag, import_transcript, list_notes, search_notes
from ledgerly.engine.workspace import init_workspace


def test_add_and_list_notes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    note = add_note(workspace, "Discussed scope with supervisor", kind="meeting", tags=["scope"])
    other = add_note(workspace, "Freeform idea about container reuse")

    assert note["id"] == "note-001"
    assert note["kind"] == "meeting"
    assert other["id"] == "note-002"
    assert other["kind"] == "note"

    assert [n["id"] for n in list_notes(workspace)] == ["note-001", "note-002"]
    assert [n["id"] for n in list_notes(workspace, kind="meeting")] == ["note-001"]
    assert [n["id"] for n in list_notes(workspace, tag="scope")] == ["note-001"]


def test_add_note_rejects_invalid_kind_or_blank_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    with pytest.raises(ValueError):
        add_note(workspace, "text", kind="not-a-kind")
    with pytest.raises(ValueError):
        add_note(workspace, "   ")


def test_add_note_tag(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    note = add_note(workspace, "Some note")

    updated = add_note_tag(workspace, note["id"], "important")

    assert updated["tags"] == ["important"]
    with pytest.raises(ValueError):
        add_note_tag(workspace, "note-999", "x")


def test_search_notes_matches_text_tags_and_source_label(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    add_note(workspace, "Container reuse reduces port congestion", tags=["congestion"])
    add_note(workspace, "Unrelated note about funding")

    hits = search_notes(workspace, "congestion")

    assert len(hits) == 1
    assert "Container reuse" in hits[0]["text"]
    assert search_notes(workspace, "") == []
    assert search_notes(workspace, "nonexistent term") == []


def test_import_transcript_strips_vtt_markup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    vtt_path = tmp_path / "meeting.vtt"
    vtt_path.write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\nHello there.\n\n2\n00:00:02.000 --> 00:00:04.000\nLet's discuss scope.\n",
        encoding="utf-8",
    )

    note = import_transcript(workspace, vtt_path)

    assert note["kind"] == "transcript"
    assert note["source_label"] == "meeting.vtt"
    assert "Hello there." in note["text"]
    assert "Let's discuss scope." in note["text"]
    assert "00:00:00.000" not in note["text"]
    assert "WEBVTT" not in note["text"]


def test_import_transcript_plain_text_passthrough(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("Just plain meeting notes.", encoding="utf-8")

    note = import_transcript(workspace, text_path, kind="meeting")

    assert note["kind"] == "meeting"
    assert note["text"] == "Just plain meeting notes."


def test_import_transcript_missing_file_raises(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    with pytest.raises(ValueError):
        import_transcript(workspace, tmp_path / "missing.vtt")
