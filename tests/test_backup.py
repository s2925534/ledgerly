from pathlib import Path
from zipfile import ZipFile

from ledgerly.engine.backup import create_workspace_backup, inspect_backup
from ledgerly.engine.workspace import init_workspace


def test_create_workspace_backup_excludes_original_sources_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "secret.txt").write_text("source", encoding="utf-8")
    (workspace / "memory.md").write_text("# Memory\nnote", encoding="utf-8")

    output_path = create_workspace_backup(workspace)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())
    assert "memory.md" in names
    assert "sources_original/manual/secret.txt" not in names


def test_create_workspace_backup_can_include_original_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "source.txt").write_text("source", encoding="utf-8")

    output_path = create_workspace_backup(workspace, include_originals=True)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())
    assert "sources_original/manual/source.txt" in names


def test_inspect_backup_reports_contents_without_restoring(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "memory.md").write_text("# Memory\nnote", encoding="utf-8")
    output_path = create_workspace_backup(workspace)

    report = inspect_backup(output_path)

    assert report["dry_run"] is True
    assert report["file_count"] > 0
    assert report["contains_original_sources"] is False
