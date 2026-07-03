from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from researchboss.core.yamlio import read_yaml, write_yaml


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")


@dataclass(frozen=True)
class MetadataRunResult:
    processed: int
    updated: int


def detect_doi(text: str) -> Optional[str]:
    match = DOI_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;)")


def detect_year(text: str) -> Optional[str]:
    match = YEAR_RE.search(text)
    return match.group(1) if match else None


def _converted_text(source: dict[str, Any]) -> str:
    conversion = source.get("conversion") if isinstance(source.get("conversion"), dict) else {}
    output_path = conversion.get("output_path")
    if not output_path:
        return ""
    path = Path(str(output_path))
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _first_title_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--- Page "):
            continue
        return stripped[:300]
    return None


def extract_source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    file_name = str(source.get("file_name") or "")
    zotero_title = source.get("zotero_title")
    zotero_year = source.get("zotero_year")
    zotero_doi = source.get("zotero_doi")
    zotero_creators = source.get("zotero_creators") if isinstance(source.get("zotero_creators"), list) else []
    text = _converted_text(source)
    combined = "\n".join([file_name, str(zotero_doi or ""), text])

    return {
        "title": zotero_title or _first_title_line(text),
        "creators": zotero_creators,
        "year": zotero_year or detect_year(combined),
        "doi": zotero_doi or detect_doi(combined),
        "source": "deterministic_extraction",
        "invented": False,
    }


def extract_citation_metadata(workspace: Path, *, status: Optional[str] = None) -> MetadataRunResult:
    register_path = workspace / "source-register.yaml"
    register = read_yaml(register_path)
    sources = [source for source in register.get("sources", []) if isinstance(source, dict)]
    selected = [source for source in sources if status is None or source.get("status") == status]

    updated = 0
    for source in selected:
        metadata = extract_source_metadata(source)
        source["citation_metadata"] = metadata
        source_id = str(source.get("source_id"))
        write_yaml(workspace / "sources_metadata" / f"{source_id}.yaml", {"version": 1, "citation_metadata": metadata})
        updated += 1

    register["sources"] = sources
    write_yaml(register_path, register)
    return MetadataRunResult(processed=len(selected), updated=updated)
