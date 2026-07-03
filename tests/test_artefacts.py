from pathlib import Path

from researchboss.engine.artefacts import list_artefacts, register_artefact
from researchboss.engine.workspace import init_workspace


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
