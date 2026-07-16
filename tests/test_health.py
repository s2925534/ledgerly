from pathlib import Path

from ledgerly.engine.claims import add_claim
from ledgerly.engine.health import corpus_dashboard_summary, workspace_health_report
from ledgerly.engine.workspace import init_workspace


def test_workspace_health_report_writes_local_validation_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "unsupported.png").write_text("image", encoding="utf-8")

    report = workspace_health_report(workspace)

    assert report["status"] == "ok"
    assert report["unsupported_files"] == ["sources_original/manual/unsupported.png"]
    assert (workspace / "outputs" / "validation" / "workspace-health.yaml").is_file()


def test_corpus_dashboard_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    add_claim(workspace, text="A claim", linked_sources=["source-001"])

    summary = corpus_dashboard_summary(workspace)

    assert summary["claim_counts"] == {"active": 1, "total": 1}
    assert summary["artefact_count"] == 0
    assert summary["open_research_question_count"] == 0
    assert summary["days_since_last_activity"] == 0
    assert "total" in summary["source_counts"]
