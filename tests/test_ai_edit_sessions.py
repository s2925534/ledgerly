import json
from pathlib import Path
from urllib.request import Request

import pytest

from corroborly.engine.ai import OpenAiCredentials, OpenAiError
from corroborly.engine.ai_edit_sessions import (
    apply_ai_edit_session,
    create_ai_edit_session,
    get_ai_edit_session,
    list_ai_edit_sessions,
    set_ai_edit_review_status,
)
from corroborly.engine.workspace import init_workspace


class FakeResponse:
    def __init__(self, data: object):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.data


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="Container automation")
    return workspace


def _target(workspace: Path) -> Path:
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Introduction\n\nContainer terminals require automation. It reduces delays significantly.\n",
        encoding="utf-8",
    )
    return target


def _edit_block(paragraph_id: str, sentence_id: str, original: str, proposed: str, rationale: str = "Clearer wording.") -> str:
    return (
        f"### EDIT paragraph_id={paragraph_id} sentence_id={sentence_id}\n"
        f"ORIGINAL: {original}\n"
        f"PROPOSED: {proposed}\n"
        f"RATIONALE: {rationale}\n"
        "### END EDIT\n"
    )


def test_create_ai_edit_session_requires_full_target_document_ai_flag(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    with pytest.raises(OpenAiError, match="--full-target-document-ai"):
        create_ai_edit_session(
            workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=False
        )


def test_create_ai_edit_session_rejects_non_markdown_targets(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Plain text target.", encoding="utf-8")

    with pytest.raises(OpenAiError, match="Markdown"):
        create_ai_edit_session(
            workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=True
        )


def test_create_ai_edit_session_parses_and_verifies_anchored_edit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse(
            {
                "id": "resp_edit",
                "output_text": _edit_block(
                    "para-001",
                    "para-001-sent-01",
                    "Container terminals require automation.",
                    "Container terminals require automation to remain competitive.",
                ),
            }
        )

    session = create_ai_edit_session(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        str(target),
        full_target_document_ai=True,
        opener=opener,
    )

    assert session["ai_used"] is True
    assert session["original_document_modified"] is False
    assert session["edit_count"] == 1
    assert session["unverified_anchor_count"] == 0
    edit = session["edits"][0]
    assert edit["paragraph_id"] == "para-001"
    assert edit["sentence_id"] == "para-001-sent-01"
    assert edit["anchor_verified"] is True
    assert edit["review_status"] == "needs_human_review"
    assert target.read_text(encoding="utf-8") == (
        "# Introduction\n\nContainer terminals require automation. It reduces delays significantly.\n"
    )  # target itself is never modified

    # Recorded in the AI-usage audit ledger like every other engine.ai call.
    from corroborly.engine.ai import list_ai_usage

    usage = list_ai_usage(workspace)
    assert usage[-1]["kind"] == "ai_edit_session"


def test_create_ai_edit_session_flags_unverified_anchor(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse(
            {
                "id": "resp_edit",
                "output_text": _edit_block(
                    "para-001",
                    "para-001-sent-01",
                    "This sentence does not actually appear in the document.",
                    "A fabricated replacement.",
                ),
            }
        )

    session = create_ai_edit_session(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        str(target),
        full_target_document_ai=True,
        opener=opener,
    )

    assert session["unverified_anchor_count"] == 1
    assert session["edits"][0]["anchor_verified"] is False


def test_create_ai_edit_session_ignores_unparseable_response(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse({"id": "resp_edit", "output_text": "No edits needed here."})

    session = create_ai_edit_session(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        str(target),
        full_target_document_ai=True,
        opener=opener,
    )

    assert session["edit_count"] == 0
    assert session["edits"] == []


def test_list_and_get_ai_edit_sessions(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse({"id": "resp_edit", "output_text": ""})

    session = create_ai_edit_session(
        workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=True, opener=opener
    )

    sessions = list_ai_edit_sessions(workspace)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session["session_id"]
    assert get_ai_edit_session(workspace, session["session_id"])["session_id"] == session["session_id"]

    with pytest.raises(ValueError, match="Unknown AI edit session_id"):
        get_ai_edit_session(workspace, "aiedit-999")


def test_set_ai_edit_review_status_updates_one_edit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse(
            {
                "id": "resp_edit",
                "output_text": _edit_block(
                    "para-001", "para-001-sent-01", "Container terminals require automation.", "Improved sentence."
                ),
            }
        )

    session = create_ai_edit_session(
        workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=True, opener=opener
    )
    edit_id = session["edits"][0]["edit_id"]

    updated = set_ai_edit_review_status(workspace, session["session_id"], edit_id, "accepted")
    assert updated["review_status"] == "accepted"
    assert get_ai_edit_session(workspace, session["session_id"])["edits"][0]["review_status"] == "accepted"

    with pytest.raises(ValueError, match="Invalid review_status"):
        set_ai_edit_review_status(workspace, session["session_id"], edit_id, "maybe")

    with pytest.raises(ValueError, match="No edit found"):
        set_ai_edit_review_status(workspace, session["session_id"], "edit-999", "accepted")


def test_apply_ai_edit_session_only_applies_approved_edits_with_visible_marker(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse(
            {
                "id": "resp_edit",
                "output_text": _edit_block(
                    "para-001",
                    "para-001-sent-01",
                    "Container terminals require automation.",
                    "Container terminals require automation to remain competitive.",
                ),
            }
        )

    session = create_ai_edit_session(
        workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=True, opener=opener
    )
    edit_id = session["edits"][0]["edit_id"]
    set_ai_edit_review_status(workspace, session["session_id"], edit_id, "accepted")

    report = apply_ai_edit_session(workspace, session["session_id"])

    assert report["applied_edit_count"] == 1
    assert report["original_document_modified"] is False
    output_path = Path(report["output_path"])
    revised = output_path.read_text(encoding="utf-8")
    assert "[[AI-EDIT-START]]Container terminals require automation to remain competitive.[[AI-EDIT-END]]" in revised
    assert target.read_text(encoding="utf-8") == (
        "# Introduction\n\nContainer terminals require automation. It reduces delays significantly.\n"
    )  # original target still untouched


def test_apply_ai_edit_session_skips_unapproved_edits(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _target(workspace)

    def opener(request: Request):
        return FakeResponse(
            {
                "id": "resp_edit",
                "output_text": _edit_block(
                    "para-001", "para-001-sent-01", "Container terminals require automation.", "Improved sentence."
                ),
            }
        )

    session = create_ai_edit_session(
        workspace, OpenAiCredentials(api_key="sk-secret"), str(target), full_target_document_ai=True, opener=opener
    )

    report = apply_ai_edit_session(workspace, session["session_id"])

    assert report["applied_edit_count"] == 0
    assert report["skipped_edit_count"] == 1
