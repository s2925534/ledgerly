from pathlib import Path

from ledgerly.core.yamlio import read_yaml
from ledgerly.engine.conversion import convert_sources
from ledgerly.engine.metadata import detect_doi, extract_citation_metadata
from ledgerly.engine.sources import scan_sources
from ledgerly.engine.workspace import init_workspace


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    return workspace


def test_detect_doi_strips_trailing_punctuation() -> None:
    assert detect_doi("See https://doi.org/10.1234/ABC.DEF.") == "10.1234/ABC.DEF"


def test_extract_citation_metadata_from_converted_text_and_filename(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "paper.txt"
    source_file.write_text("Deterministic Research Title\nPublished in 2024.\nDOI: 10.1234/example", encoding="utf-8")
    scan_sources(workspace, source_root)
    convert_sources(workspace)

    result = extract_citation_metadata(workspace)

    assert result.updated == 1
    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    metadata = source["citation_metadata"]
    assert metadata["title"] == "Deterministic Research Title"
    assert metadata["year"] == "2024"
    assert metadata["doi"] == "10.1234/example"
    assert metadata["invented"] is False
    assert (workspace / "sources_metadata" / f"{source['source_id']}.yaml").is_file()
