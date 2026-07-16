from pathlib import Path

import pytest

from ledgerly.core.yamlio import write_yaml
from ledgerly.engine.claims import add_claim
from ledgerly.engine.derived_text import build_derived_text_snapshot
from ledgerly.engine.vault import create_document_version
from ledgerly.engine.workspace import init_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    return workspace


def test_build_derived_text_snapshot_detects_markdown_sections(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Introduction\n\nContainer terminals require automation. It reduces delays.\n\n"
        "## Background\n\nBerth planning is a well-studied problem.\n",
        encoding="utf-8",
    )
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    assert snapshot["section_count"] == 2
    assert [s["heading"] for s in snapshot["sections"]] == ["Introduction", "Background"]
    assert snapshot["sections"][0]["level"] == 1
    assert snapshot["sections"][1]["level"] == 2
    assert snapshot["paragraph_count"] == 2
    assert snapshot["paragraphs"][0]["section_id"] == snapshot["sections"][0]["section_id"]
    assert snapshot["paragraphs"][1]["section_id"] == snapshot["sections"][1]["section_id"]
    # the raw "#"/"##" markers must never leak into extracted paragraph text
    assert "#" not in snapshot["paragraphs"][0]["text"]


def test_build_derived_text_snapshot_splits_sentences_with_citation_anchors(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Container automation reduces delays. It also improves safety.\n", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    sentences = snapshot["paragraphs"][0]["sentences"]
    assert len(sentences) == 2
    assert sentences[0]["text"] == "Container automation reduces delays."
    assert sentences[1]["text"] == "It also improves safety."
    assert all(s["citation_insertion_anchor"] == "end_of_sentence_before_final_punctuation" for s in sentences)
    assert all(s["has_inline_citation"] is False for s in sentences)


def test_build_derived_text_snapshot_detects_inline_citations(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Berth planning improves throughput (Smith, 2024).\n", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    sentence = snapshot["paragraphs"][0]["sentences"][0]
    assert sentence["has_inline_citation"] is True


def test_build_derived_text_snapshot_links_claim_ids(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Berth planning improves container throughput significantly.\n", encoding="utf-8")
    claim = add_claim(workspace, text="Berth planning improves container throughput")
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    sentence = snapshot["paragraphs"][0]["sentences"][0]
    assert sentence["claim_ids"] == [claim["id"]]


def test_build_derived_text_snapshot_links_reference_ids_from_validation_report(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Container terminal automation improves efficiency.\n", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    write_yaml(
        workspace / "outputs" / "validation" / "document-validation-draft.yaml",
        {
            "sentence_checks": [
                {
                    "text": "Container terminal automation improves efficiency.",
                    "best_source_id": "source-001",
                }
            ]
        },
    )
    version_with_report = dict(version, validation_report_id="document-validation-draft")
    # Simulate a version that already carries a linked validation report, the
    # way citations.apply_citation_plan produces one -- write it back onto
    # the ledger directly since create_document_version doesn't take a
    # validation_report_id for a manual snapshot.
    from ledgerly.core.yamlio import read_yaml

    ledger_path = workspace / "document-vault.yaml"
    ledger = read_yaml(ledger_path)
    for record in ledger["versions"]:
        if record["version_id"] == version["version_id"]:
            record["validation_report_id"] = "document-validation-draft"
    write_yaml(ledger_path, ledger)

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    sentence = snapshot["paragraphs"][0]["sentences"][0]
    assert sentence["reference_ids"] == ["source-001"]


def test_build_derived_text_snapshot_skips_section_detection_for_non_markdown(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Introduction\n\nContainer terminals require automation.\n", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    assert snapshot["section_count"] == 0
    assert all(p["section_id"] is None for p in snapshot["paragraphs"])


def test_build_derived_text_snapshot_is_deterministic_across_repeated_calls(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Intro\n\nFirst paragraph. Second sentence.\n", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    first = build_derived_text_snapshot(workspace, version["version_id"])
    second = build_derived_text_snapshot(workspace, version["version_id"])

    assert first["paragraphs"] == second["paragraphs"]
    assert first["sections"] == second["sections"]


def test_build_derived_text_snapshot_writes_to_vault_and_never_touches_original(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_text = "# Intro\n\nSome content.\n"
    target.write_text(original_text, encoding="utf-8")
    version = create_document_version(workspace, str(target))

    snapshot = build_derived_text_snapshot(workspace, version["version_id"])

    snapshot_path = Path(snapshot["derived_text_path"])
    assert snapshot_path.is_file()
    assert snapshot_path.parent.name == "derived_text"
    assert target.read_text(encoding="utf-8") == original_text


def test_build_derived_text_snapshot_rejects_unknown_version(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ValueError, match="Unknown document version_id"):
        build_derived_text_snapshot(workspace, "docv-999")


def test_build_derived_text_snapshot_rejects_unsupported_extension(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "artefacts" / "papers" / "draft.xyz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content", encoding="utf-8")
    version = create_document_version(workspace, str(target))

    with pytest.raises(ValueError, match="Unsupported document extension"):
        build_derived_text_snapshot(workspace, version["version_id"])
