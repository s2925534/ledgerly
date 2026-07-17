from pathlib import Path

from corroborly.core.yamlio import read_yaml, write_yaml
from corroborly.engine.sidecars import import_sidecar_metadata, parse_sidecar_metadata
from corroborly.engine.workspace import init_workspace


def test_parse_sidecar_metadata_supports_csl_json_bibtex_and_ris(tmp_path: Path) -> None:
    csl = tmp_path / "paper.json"
    csl.write_text(
        """
[
  {
    "type": "article-journal",
    "title": "CSL Paper",
    "author": [{"family": "Smith", "given": "A."}],
    "issued": {"date-parts": [[2024]]},
    "DOI": "10.1000/csl",
    "container-title": "Journal",
    "abstract": "CSL abstract",
    "keyword": "ports; evidence"
  }
]
""",
        encoding="utf-8",
    )
    bib = tmp_path / "paper.bib"
    bib.write_text(
        """
@article{smith2024,
  title = {Bib Paper},
  author = {Smith, A. and Jones, B.},
  year = {2024},
  doi = {10.1000/bib},
  journal = {Journal},
  abstract = {Bib abstract},
  keywords = {ports; evidence}
}
""",
        encoding="utf-8",
    )
    ris = tmp_path / "paper.ris"
    ris.write_text(
        """
TY  - JOUR
TI  - RIS Paper
AU  - Smith, A.
PY  - 2024
DO  - 10.1000/ris
JO  - Journal
AB  - RIS abstract
KW  - ports
ER  -
""",
        encoding="utf-8",
    )

    assert parse_sidecar_metadata(csl)["abstract"] == "CSL abstract"
    assert parse_sidecar_metadata(bib)["authors"] == ["Smith, A.", "Jones, B."]
    assert parse_sidecar_metadata(ris)["keywords"] == ["ports"]


def test_import_sidecar_metadata_updates_registered_sources_without_inventing_missing_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "paper.pdf"
    sidecar = source_root / "paper.ris"
    source.write_text("pdf-ish", encoding="utf-8")
    sidecar.write_text("TY  - JOUR\nTI  - Sidecar Paper\nAU  - Smith, A.\nPY  - 2024\nAB  - Abstract text\nER  -\n", encoding="utf-8")
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "source-register.yaml",
        {"version": 1, "sources": [{"source_id": "source-001", "file_path": str(source), "file_name": source.name}]},
    )

    result = import_sidecar_metadata(workspace)

    register = read_yaml(workspace / "source-register.yaml")
    metadata = register["sources"][0]["citation_metadata"]
    assert result.updated == 1
    assert metadata["title"] == "Sidecar Paper"
    assert metadata["abstract"] == "Abstract text"
    assert "doi" not in metadata
    assert (workspace / "sources_metadata" / "sidecar-metadata.yaml").is_file()
