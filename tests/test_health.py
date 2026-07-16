from pathlib import Path

from ledgerly.engine.health import workspace_health_report
from ledgerly.engine.workspace import init_workspace


def test_workspace_health_report_writes_local_validation_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "unsupported.png").write_text("image", encoding="utf-8")

    report = workspace_health_report(workspace)

    assert report["status"] == "ok"
    assert report["unsupported_files"] == ["sources_original/manual/unsupported.png"]
    assert (workspace / "outputs" / "validation" / "workspace-health.yaml").is_file()
