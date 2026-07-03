from pathlib import Path
from zipfile import ZipFile

from researchboss.core.yamlio import write_yaml
from researchboss.engine.export import export_evidence_bundle
from researchboss.engine.workspace import init_workspace


def test_export_evidence_bundle_excludes_original_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "paper.txt").write_text("full text", encoding="utf-8")
    write_yaml(workspace / "accepted-sources.yaml", {"version": 1, "source_ids": ["source-001"]})
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {"source_id": "source-001", "status": "accepted", "file_name": "paper.txt"},
                {"source_id": "source-002", "status": "ignored", "file_name": "ignored.txt"},
            ],
        },
    )

    output_path = export_evidence_bundle(workspace)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())
        accepted = zf.read("accepted-source-records.yaml").decode("utf-8")
    assert "manifest.yaml" in names
    assert "sources_original/manual/paper.txt" not in names
    assert "source-001" in accepted
    assert "source-002" not in accepted
