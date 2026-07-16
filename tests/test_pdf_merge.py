from pathlib import Path

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.pdf_merge import pdf_merge_report
from ledgerly.engine.workspace import init_workspace


def test_pdf_merge_report_writes_dry_run_manifest_and_csv(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    pdf = source_root / "paper.pdf"
    txt = source_root / "notes.txt"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    txt.write_text("notes", encoding="utf-8")
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    write_yaml(workspace / "accepted-sources.yaml", {"version": 1, "source_ids": ["pdf-001", "txt-001", "missing-001"]})
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {"source_id": "pdf-001", "file_name": pdf.name, "file_path": str(pdf)},
                {"source_id": "txt-001", "file_name": txt.name, "file_path": str(txt)},
                {"source_id": "missing-001", "file_name": "missing.pdf", "file_path": str(source_root / "missing.pdf")},
            ],
        },
    )

    result = pdf_merge_report(workspace)

    manifest = read_yaml(result.manifest_path)
    csv_text = result.csv_path.read_text(encoding="utf-8")
    assert result.dry_run is True
    assert result.output_path is None
    assert manifest["included_count"] == 1
    assert manifest["skipped_count"] == 2
    assert "not_pdf" in csv_text
    assert "file_missing" in csv_text
