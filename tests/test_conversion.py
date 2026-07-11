from pathlib import Path
import sys
import types
import zipfile

from researchboss.core.yamlio import read_yaml, write_yaml
import researchboss.engine.conversion as conversion
from researchboss.engine.conversion import convert_sources, extract_text, ocr_readiness_report, processing_issue_report
from researchboss.engine.sources import scan_sources, set_source_status
from researchboss.engine.workspace import init_workspace


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    return workspace


def test_convert_sources_converts_txt_to_sources_text(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "notes.txt"
    source_file.write_text("line one\r\nline two\r", encoding="utf-8")
    scan_sources(workspace, source_root)
    source_id = read_yaml(workspace / "source-register.yaml")["sources"][0]["source_id"]
    set_source_status(workspace, source_id=source_id, new_status="accepted")

    result = convert_sources(workspace, status="accepted")

    assert result.processed == 1
    assert result.converted == 1
    output_path = workspace / "sources_text" / f"{source_id}.txt"
    assert output_path.read_text(encoding="utf-8") == "line one\nline two\n"
    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    assert source["conversion"]["status"] == "converted"
    assert source["conversion"]["output_path"] == str(output_path)


def test_convert_sources_converts_md_to_plain_text(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "notes.md"
    source_file.write_text(
        "# Heading\n\n- **Important** [source](https://example.test)\n\n`code term`\n",
        encoding="utf-8",
    )
    scan_sources(workspace, source_root)

    result = convert_sources(workspace)

    assert result.converted == 1
    source_id = read_yaml(workspace / "source-register.yaml")["sources"][0]["source_id"]
    output = (workspace / "sources_text" / f"{source_id}.txt").read_text(encoding="utf-8")
    assert "Heading" in output
    assert "Important source" in output
    assert "code term" in output
    assert "**" not in output
    assert "https://example.test" not in output


def test_markdown_heading_blockquote_and_list_stripping_preserves_blank_line_separators(tmp_path: Path) -> None:
    # Regression test: the leading-whitespace class in these stripping
    # regexes must be [ \t] (same-line indentation), not \s. \s also
    # matches newlines, which let the match start at a preceding blank
    # line's own line-start position and reach forward across it into the
    # marker -- silently deleting the blank line and merging the marked
    # block into the previous paragraph.
    heading_file = tmp_path / "heading.md"
    heading_file.write_text("Paragraph one.\n\n## Heading Two\n\nParagraph two.\n", encoding="utf-8")
    assert extract_text(heading_file) == "Paragraph one.\n\nHeading Two\n\nParagraph two.\n"

    blockquote_file = tmp_path / "blockquote.md"
    blockquote_file.write_text("Paragraph one.\n\n> Quoted text\n", encoding="utf-8")
    assert extract_text(blockquote_file) == "Paragraph one.\n\nQuoted text\n"

    bullet_file = tmp_path / "bullet.md"
    bullet_file.write_text("Paragraph one.\n\n- item one\n- item two\n", encoding="utf-8")
    assert extract_text(bullet_file) == "Paragraph one.\n\nitem one\nitem two\n"

    numbered_file = tmp_path / "numbered.md"
    numbered_file.write_text("Paragraph one.\n\n1. item one\n2. item two\n", encoding="utf-8")
    assert extract_text(numbered_file) == "Paragraph one.\n\nitem one\nitem two\n"


def test_convert_sources_converts_docx_to_plain_text(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "paper.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
        <w:p><w:r><w:t>Second </w:t></w:r><w:r><w:t>paragraph.</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with zipfile.ZipFile(source_file, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    scan_sources(workspace, source_root)

    result = convert_sources(workspace)

    assert result.converted == 1
    source_id = read_yaml(workspace / "source-register.yaml")["sources"][0]["source_id"]
    output = (workspace / "sources_text" / f"{source_id}.txt").read_text(encoding="utf-8")
    assert output == "First paragraph.\nSecond paragraph.\n"


def test_convert_sources_converts_pdf_with_page_markers(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "paper.pdf"
    source_file.write_bytes(
        b"""%PDF-1.4
1 0 obj << /Type /Page /Contents 2 0 R >> endobj
2 0 obj << /Length 44 >> stream
BT /F1 12 Tf (First page text.) Tj ET
endstream endobj
3 0 obj << /Type /Page /Contents 4 0 R >> endobj
4 0 obj << /Length 45 >> stream
BT /F1 12 Tf (Second page text.) Tj ET
endstream endobj
%%EOF
"""
    )
    scan_sources(workspace, source_root)

    result = convert_sources(workspace)

    assert result.converted == 1
    source_id = read_yaml(workspace / "source-register.yaml")["sources"][0]["source_id"]
    output = (workspace / "sources_text" / f"{source_id}.txt").read_text(encoding="utf-8")
    assert "--- Page 1 ---" in output
    assert "First page text." in output
    assert "--- Page 2 ---" in output
    assert "Second page text." in output


def test_ocr_readiness_reports_local_tool_availability(monkeypatch) -> None:
    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"tesseract", "pdftoppm"} else None

    monkeypatch.setattr(conversion.shutil, "which", fake_which)

    report = ocr_readiness_report()

    assert report["ocr_supported_locally"] is True
    assert report["tools"]["tesseract"]["available"] is True
    assert report["tools"]["pdftoppm"]["available"] is True


def test_convert_sources_requires_explicit_ocr_for_scanned_pdf(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "scanned.pdf"
    source_file.write_bytes(b"%PDF-1.4\nstream\nBT\nET\nendstream\n%%EOF\n")
    scan_sources(workspace, source_root)

    result = convert_sources(workspace)

    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    assert result.failed == 1
    assert source["conversion"]["status"] == "failed"
    assert "--ocr" in source["conversion"]["error"]


def test_convert_sources_uses_explicit_ocr_fallback(tmp_path: Path, monkeypatch) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "scanned.pdf"
    source_file.write_bytes(b"%PDF-1.4\nstream\nBT\nET\nendstream\n%%EOF\n")
    scan_sources(workspace, source_root)
    monkeypatch.setattr(conversion, "_ocr_pdf_text", lambda _path: "--- Page 1 ---\nOCR text from scan.\n")

    result = convert_sources(workspace, allow_ocr=True)

    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    output = Path(source["conversion"]["output_path"]).read_text(encoding="utf-8")
    assert result.converted == 1
    assert "OCR text from scan." in output


def test_processing_issue_report_groups_failed_and_skipped_sources(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "ocr",
                    "file_name": "scan.pdf",
                    "file_path": str(tmp_path / "scan.pdf"),
                    "conversion": {"status": "failed", "error": "PDF appears to need OCR; rerun with --ocr"},
                },
                {
                    "source_id": "unsupported",
                    "file_name": "slides.pptx",
                    "file_path": str(tmp_path / "slides.pptx"),
                    "conversion": {"status": "not_supported"},
                },
                {
                    "source_id": "metadata",
                    "status": "accepted",
                    "file_name": "paper.pdf",
                    "file_path": str(tmp_path / "paper.pdf"),
                    "conversion": {"status": "converted"},
                },
            ],
        },
    )
    (tmp_path / "paper.pdf").write_text("pdf", encoding="utf-8")

    report = processing_issue_report(workspace)

    kinds = {row["issue_kind"] for row in report["issues"]}
    assert {"ocr_needed", "unsupported_format", "missing_metadata"} <= kinds
    assert report["original_files_modified"] is False


def test_extract_pdf_uses_optional_pymupdf_when_available(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "paper.pdf"
    source_file.write_bytes(b"%PDF-1.4 conservative fallback")

    class FakePage:
        def get_text(self, _mode):
            return "PyMuPDF page text"

    class FakeDoc(list):
        def close(self):
            self.closed = True

    fake_fitz = types.SimpleNamespace(open=lambda _path: FakeDoc([FakePage()]))
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    output = extract_text(source_file)

    assert "PyMuPDF page text" in output


def test_extract_pdf_falls_back_to_pypdf_when_pymupdf_missing(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "paper.pdf"
    source_file.write_bytes(b"%PDF-1.4 conservative fallback")

    class FakePage:
        def extract_text(self):
            return "PyPDF page text"

    class FakeReader:
        pages = [FakePage()]

        def __init__(self, _path):
            pass

    fake_pypdf = types.SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    monkeypatch.setitem(sys.modules, "fitz", None)

    output = extract_text(source_file)

    assert "PyPDF page text" in output


def test_convert_sources_skips_unchanged_cached_output(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "notes.txt"
    source_file.write_text("original", encoding="utf-8")
    scan_sources(workspace, source_root)

    first = convert_sources(workspace)
    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    output_path = Path(source["conversion"]["output_path"])
    output_path.write_text("manual marker", encoding="utf-8")
    second = convert_sources(workspace)

    assert first.converted == 1
    assert second.converted == 0
    assert second.skipped == 1
    assert second.results[0].status == "skipped_unchanged"
    assert output_path.read_text(encoding="utf-8") == "manual marker"


def test_convert_sources_records_failed_conversion(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_file = source_root / "broken.docx"
    source_file.write_text("not a zip file", encoding="utf-8")
    scan_sources(workspace, source_root)

    result = convert_sources(workspace)

    assert result.failed == 1
    source = read_yaml(workspace / "source-register.yaml")["sources"][0]
    assert source["conversion"]["status"] == "failed"
    failed_path = Path(source["conversion"]["failed_path"])
    assert failed_path.is_file()
    failure = read_yaml(failed_path)
    assert failure["source_id"] == source["source_id"]
    assert failure["error"]
