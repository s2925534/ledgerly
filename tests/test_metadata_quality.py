from pathlib import Path

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.metadata_quality import (
    build_keyword_index,
    citation_consistency_report,
    duplicate_metadata_report,
    filename_suggestion_report,
    normalize_doi,
)
from ledgerly.engine.workspace import init_workspace


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    return workspace


def test_normalize_doi_accepts_values_and_doi_urls() -> None:
    assert normalize_doi("DOI: 10.1234/ABC.def") == "10.1234/abc.def"
    assert normalize_doi("https://doi.org/10.1234/ABC.def") == "10.1234/abc.def"
    assert normalize_doi("not a doi") is None


def test_citation_consistency_report_flags_doi_url_mismatch(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "source-001",
                    "file_name": "paper.pdf",
                    "citation_metadata": {
                        "title": "Paper",
                        "year": "2024",
                        "creators": ["A. Author"],
                        "doi": "10.1234/right",
                        "url": "https://doi.org/10.9999/wrong",
                    },
                }
            ],
        },
    )

    report = citation_consistency_report(workspace)

    assert report["sources"][0]["status"] == "needs_review"
    assert report["sources"][0]["doi_validation"]["issues"] == ["doi_url_mismatch"]
    assert (workspace / "outputs" / "validation" / "citation-consistency.yaml").is_file()


def test_duplicate_metadata_report_uses_filename_title_and_doi(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {"source_id": "s1", "file_name": "a.pdf", "citation_metadata": {"title": "Same", "doi": "10.1234/a"}},
                {"source_id": "s2", "file_name": "b.pdf", "citation_metadata": {"title": "Same", "doi": "10.1234/a"}},
            ],
        },
    )

    report = duplicate_metadata_report(workspace)

    kinds = {group["match_type"] for group in report["duplicate_groups"]}
    assert {"title", "doi"} <= kinds


def test_build_keyword_index_reads_converted_text(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    text_path = workspace / "sources_text" / "source-001.txt"
    text_path.write_text("Evidence evidence synthesis", encoding="utf-8")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [{"source_id": "source-001", "conversion": {"status": "converted", "output_path": str(text_path)}}],
        },
    )

    index = build_keyword_index(workspace)

    assert index["entries"][0]["terms"]["evidence"] == 2
    assert read_yaml(workspace / "sources_metadata" / "keyword-index.yaml")["entry_count"] == 1


def test_filename_suggestion_report_does_not_rename_originals(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    original = workspace / "sources_original" / "manual" / "bad name.pdf"
    original.write_text("original", encoding="utf-8")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "source-001",
                    "file_name": original.name,
                    "file_ext": "pdf",
                    "file_path": str(original),
                    "citation_metadata": {
                        "title": "Container Port Evidence",
                        "authors": ["Smith, A."],
                        "year": 2024,
                    },
                }
            ],
        },
    )

    report = filename_suggestion_report(workspace)

    suggestion = report["suggestions"][0]
    assert suggestion["suggested_file_name"] == "smith_2024_container-port-evidence_source-001.pdf"
    assert suggestion["rename_performed"] is False
    assert report["original_files_renamed"] is False
    assert original.is_file()
