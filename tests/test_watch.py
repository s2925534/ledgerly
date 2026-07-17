from pathlib import Path

from corroborly.core.yamlio import read_yaml
from corroborly.engine.sources import scan_sources
from corroborly.engine.watch import find_unregistered_sources, write_watch_report
from corroborly.engine.workspace import init_workspace


def test_watch_detects_unregistered_source_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "known.txt").write_text("known", encoding="utf-8")
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="M.Phil",
        topic="",
        source_root=str(source_root),
        source_mode="local_folder",
    )
    scan_sources(workspace, source_root)
    (source_root / "new.txt").write_text("new", encoding="utf-8")

    candidates = find_unregistered_sources(workspace)
    output_path = write_watch_report(workspace)

    assert [candidate["file_name"] for candidate in candidates] == ["new.txt"]
    report = read_yaml(output_path)
    assert report["candidate_count"] == 1
    assert report["candidates"][0]["file_name"] == "new.txt"
