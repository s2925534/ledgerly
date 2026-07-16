from pathlib import Path

import pytest

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.artefact_creation import create_deterministic_artefact
from ledgerly.engine.artefacts import (
    artefact_dependency_report,
    list_artefacts,
    register_artefact,
    set_artefact_review_status,
)
from ledgerly.engine.claims import add_claim
from ledgerly.engine.workspace import init_workspace


def test_register_artefact_records_links_and_review_flags(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    artefact_path = workspace / "artefacts" / "reports" / "summary.md"
    artefact_path.write_text("# Summary", encoding="utf-8")

    record = register_artefact(
        workspace,
        title="Summary",
        artefact_type="report",
        path=artefact_path,
        linked_sources=["source-001"],
        linked_research_questions=["rq-001"],
        requires_user_review=True,
    )

    assert record["id"] == "artefact-001"
    assert record["linked_sources"] == ["source-001"]
    assert record["linked_research_questions"] == ["rq-001"]
    assert record["ai_generated"] is False
    assert record["requires_user_review"] is True
    assert record["review_status"] == "pending_review"
    assert list_artefacts(workspace) == [record]


def test_create_source_summary_uses_accepted_sources_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "accepted-001",
                    "status": "accepted",
                    "file_name": "accepted.pdf",
                    "file_ext": "pdf",
                    "citation_metadata": {"title": "Accepted Paper", "authors": ["A. Author"], "year": 2024},
                },
                {"source_id": "ignored-001", "status": "ignored", "file_name": "ignored.pdf", "file_ext": "pdf"},
                {"source_id": "maybe-001", "status": "maybe", "file_name": "maybe.pdf", "file_ext": "pdf"},
            ],
        },
    )

    result = create_deterministic_artefact(workspace, "source-summary-report")

    content = result.path.read_text(encoding="utf-8")
    assert "Accepted Paper" in content
    assert "ignored-001" not in content
    assert "maybe-001" not in content
    assert "No interpretation performed." in content
    assert "User review required." in content
    assert result.record["ai_generated"] is False
    assert result.record["requires_user_review"] is True
    assert result.record["linked_sources"] == ["accepted-001"]


def test_create_source_summary_can_include_maybe_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {"source_id": "accepted-001", "status": "accepted", "file_name": "accepted.pdf", "file_ext": "pdf"},
                {"source_id": "maybe-001", "status": "maybe", "file_name": "maybe.pdf", "file_ext": "pdf"},
            ],
        },
    )

    result = create_deterministic_artefact(workspace, "source-summary-report", include_maybe=True)

    content = result.path.read_text(encoding="utf-8")
    assert "accepted-001" in content
    assert "maybe-001" in content
    assert result.record["linked_sources"] == ["accepted-001", "maybe-001"]


def test_create_claim_evidence_table_does_not_infer_support(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    add_claim(workspace, text="Supported claim", linked_sources=["source-001"], linked_research_questions=["rq-001"])
    add_claim(workspace, text="Unsupported claim")

    result = create_deterministic_artefact(workspace, "claim-evidence-table")

    content = result.path.read_text(encoding="utf-8")
    assert "Supported claim" in content
    assert "Linked evidence" in content
    assert "Unsupported claim" in content
    assert "No linked evidence" in content
    assert result.record["linked_sources"] == ["source-001"]
    assert result.record["linked_research_questions"] == ["rq-001"]


def test_create_research_question_brief_links_questions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {"question": "How does X work?", "status": "approved", "subquestions": ["What is X?"]},
            {"question": "Should Y be studied?", "status": "draft", "subquestions": []},
        ],
    )

    result = create_deterministic_artefact(workspace, "research-question-brief")

    content = result.path.read_text(encoding="utf-8")
    assert "How does X work?" in content
    assert "Should Y be studied?" in content
    assert result.record["linked_research_questions"] == ["rq-001", "rq-002"]


def test_create_data_profile_summary_uses_profile_metadata_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "outputs" / "data-profiles" / "source-001.yaml",
        {
            "version": 1,
            "source_id": "source-001",
            "profile": {"type": "csv", "row_count": 2, "column_count": 3},
        },
    )

    result = create_deterministic_artefact(workspace, "data-profile-summary")

    content = result.path.read_text(encoding="utf-8")
    assert "Full datasets are not copied into this artefact." in content
    assert "| source-001 | csv | 2 | 3 |" in content
    assert result.record["linked_sources"] == ["source-001"]


def test_create_artefact_requires_overwrite_for_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    create_deterministic_artefact(workspace, "source-summary-report")

    with pytest.raises(ValueError, match="already exists"):
        create_deterministic_artefact(workspace, "source-summary-report")

    result = create_deterministic_artefact(workspace, "source-summary-report", overwrite=True)
    assert result.path.is_file()


def test_artefact_review_status_and_dependency_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="M.Phil",
        topic="",
        research_questions=[{"question": "Approved?", "status": "approved", "subquestions": []}],
    )
    write_yaml(
        workspace / "source-register.yaml",
        {"version": 1, "sources": [{"source_id": "source-001", "status": "maybe"}]},
    )
    record = register_artefact(
        workspace,
        title="Report",
        artefact_type="report",
        path=workspace / "artefacts" / "reports" / "report.md",
        linked_sources=["source-001"],
        linked_research_questions=["rq-001"],
    )

    set_artefact_review_status(workspace, record["id"], "needs_revision")
    report = artefact_dependency_report(workspace)

    assert list_artefacts(workspace)[0]["review_status"] == "needs_revision"
    assert report["artefacts"][0]["status"] == "needs_review"
    assert report["artefacts"][0]["issues"][0]["kind"] == "source_not_accepted"
