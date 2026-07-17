from __future__ import annotations

import csv
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corroborly.core.yamlio import read_yaml, write_yaml


@dataclass(frozen=True)
class PdfMergeResult:
    manifest_path: Path
    csv_path: Path
    output_path: Path | None
    included: int
    skipped: int
    failed: int
    dry_run: bool


def pdf_merge_report(workspace: Path, *, dry_run: bool = True, output: Path | None = None) -> PdfMergeResult:
    output_dir = workspace / "outputs" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "pdf-merge-manifest.yaml"
    csv_path = output_dir / "pdf-merge-manifest.csv"
    output_path = output or output_dir / "accepted-source-pdfs.pdf"

    rows = _merge_rows(workspace)
    included_rows = [row for row in rows if row["status"] == "included"]
    failed_rows = []
    written_output: Path | None = None
    if not dry_run and included_rows:
        try:
            _write_pdf_merge(output_path, [Path(str(row["file_path"])) for row in included_rows])
            written_output = output_path
        except Exception as exc:
            failed_rows.append({"status": "failed", "reason": str(exc), "file_path": str(output_path)})

    manifest = {
        "version": 1,
        "dry_run": dry_run,
        "output_path": str(written_output or output_path),
        "original_files_modified": False,
        "included_count": len(included_rows),
        "skipped_count": len([row for row in rows if row["status"] == "skipped"]),
        "failed_count": len(failed_rows),
        "rows": rows + failed_rows,
        "notes": "PDF merge reports never rename, move, or modify original files.",
    }
    write_yaml(manifest_path, manifest)
    _write_csv(csv_path, manifest["rows"])
    return PdfMergeResult(
        manifest_path=manifest_path,
        csv_path=csv_path,
        output_path=written_output,
        included=manifest["included_count"],
        skipped=manifest["skipped_count"],
        failed=manifest["failed_count"],
        dry_run=dry_run,
    )


def _merge_rows(workspace: Path) -> list[dict[str, Any]]:
    accepted = set(read_yaml(workspace / "accepted-sources.yaml").get("source_ids", []))
    register = read_yaml(workspace / "source-register.yaml")
    rows = []
    for source in register.get("sources", []):
        if not isinstance(source, dict) or source.get("source_id") not in accepted:
            continue
        path = Path(str(source.get("file_path") or ""))
        if path.suffix.lower() != ".pdf":
            rows.append(_row(source, path, status="skipped", reason="not_pdf"))
        elif not path.is_file():
            rows.append(_row(source, path, status="skipped", reason="file_missing"))
        else:
            rows.append(_row(source, path, status="included", reason=None))
    return rows


def _row(source: dict[str, Any], path: Path, *, status: str, reason: str | None) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "file_name": source.get("file_name"),
        "file_path": str(path),
        "status": status,
        "reason": reason,
    }


def _write_pdf_merge(output_path: Path, paths: list[Path]) -> None:
    try:
        pypdf = importlib.import_module("pypdf")
    except ModuleNotFoundError:
        pypdf = importlib.import_module("PyPDF2")
    writer = pypdf.PdfWriter()
    for path in paths:
        reader = pypdf.PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source_id", "file_name", "file_path", "status", "reason"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
