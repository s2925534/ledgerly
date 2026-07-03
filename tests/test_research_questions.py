from pathlib import Path

import pytest

from researchboss.core.yamlio import read_yaml
from researchboss.engine.research_questions import (
    approve_research_question,
    archive_research_question,
    list_research_questions,
    reject_research_question,
)
from researchboss.engine.workspace import init_workspace


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {"question": "Approved question?", "status": "approved", "subquestions": []},
            {"question": "Draft question?", "status": "draft", "subquestions": ["Sub?"]},
        ],
    )
    return workspace


def test_approve_research_question_moves_candidate_to_approved(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    approve_research_question(workspace, "rq-002")

    groups = list_research_questions(workspace)
    assert [item["id"] for item in groups["approved"]] == ["rq-001", "rq-002"]
    assert groups["candidates"] == []


def test_reject_and_archive_research_questions(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    reject_research_question(workspace, "rq-002", reason="Too broad")
    archive_research_question(workspace, "rq-001", reason="Superseded")

    rejected = read_yaml(workspace / "rejected-research-questions.yaml")["rejected"]
    assert rejected[0]["status"] == "rejected"
    assert rejected[0]["reason"] == "Too broad"
    assert rejected[1]["status"] == "archived"
    assert rejected[1]["reason"] == "Superseded"


def test_approve_research_question_rejects_unknown_id(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    with pytest.raises(ValueError, match="Unknown candidate"):
        approve_research_question(workspace, "rq-999")
