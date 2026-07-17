from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from corroborly.core.yamlio import read_yaml, write_yaml


SIDECAR_EXTENSIONS = {".json", ".bib", ".ris"}


@dataclass(frozen=True)
class SidecarImportResult:
    processed: int
    updated: int
    skipped: int
    report_path: Path


def import_sidecar_metadata(workspace: Path) -> SidecarImportResult:
    register_path = workspace / "source-register.yaml"
    register = read_yaml(register_path)
    sources = [source for source in register.get("sources", []) if isinstance(source, dict)]
    rows = []
    updated = skipped = 0
    for source in sources:
        sidecar = _find_sidecar(source)
        if not sidecar:
            skipped += 1
            rows.append({"source_id": source.get("source_id"), "status": "skipped", "reason": "sidecar_not_found"})
            continue
        metadata = parse_sidecar_metadata(sidecar)
        if not metadata:
            skipped += 1
            rows.append({"source_id": source.get("source_id"), "status": "skipped", "reason": "metadata_not_found", "sidecar": str(sidecar)})
            continue
        existing = source.get("citation_metadata") if isinstance(source.get("citation_metadata"), dict) else {}
        source["citation_metadata"] = _merge_known_metadata(existing, metadata)
        source["sidecar_metadata"] = {
            "path": str(sidecar),
            "format": sidecar.suffix.lower().lstrip("."),
            "fields": sorted(metadata),
        }
        updated += 1
        rows.append({"source_id": source.get("source_id"), "status": "updated", "sidecar": str(sidecar), "fields": sorted(metadata)})

    register["sources"] = sources
    write_yaml(register_path, register)
    report = {
        "version": 1,
        "processed": len(sources),
        "updated": updated,
        "skipped": skipped,
        "rows": rows,
        "notes": "Sidecar metadata is parsed deterministically. Missing fields remain missing.",
    }
    report_path = workspace / "sources_metadata" / "sidecar-metadata.yaml"
    write_yaml(report_path, report)
    return SidecarImportResult(processed=len(sources), updated=updated, skipped=skipped, report_path=report_path)


def parse_sidecar_metadata(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_csl_json(path)
    if suffix == ".bib":
        return _parse_bibtex(path)
    if suffix == ".ris":
        return _parse_ris(path)
    return {}


def _find_sidecar(source: dict[str, Any]) -> Path | None:
    source_path = Path(str(source.get("file_path") or ""))
    if not source_path.name:
        return None
    candidates = [source_path.with_suffix(extension) for extension in SIDECAR_EXTENSIONS]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _merge_known_metadata(existing: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in metadata.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _parse_csl_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    item = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(item, dict):
        return {}
    issued = item.get("issued") if isinstance(item.get("issued"), dict) else {}
    date_parts = issued.get("date-parts") if isinstance(issued.get("date-parts"), list) else []
    year = date_parts[0][0] if date_parts and isinstance(date_parts[0], list) and date_parts[0] else item.get("year")
    keywords = item.get("keyword")
    if isinstance(keywords, str):
        keywords = [part.strip() for part in re.split(r"[;,]", keywords) if part.strip()]
    return _clean_metadata(
        {
            "title": item.get("title"),
            "authors": [_csl_author_name(author) for author in item.get("author", []) if isinstance(author, dict)],
            "year": year,
            "doi": item.get("DOI") or item.get("doi"),
            "publication_title": item.get("container-title"),
            "abstract": item.get("abstract"),
            "keywords": keywords,
            "item_type": item.get("type"),
        }
    )


def _csl_author_name(author: dict[str, Any]) -> str:
    family = str(author.get("family") or "").strip()
    given = str(author.get("given") or "").strip()
    literal = str(author.get("literal") or "").strip()
    if family and given:
        return f"{family}, {given}"
    return family or given or literal


def _parse_bibtex(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    entry_type_match = re.search(r"@\s*([A-Za-z]+)\s*\{", text)
    fields = {
        key.lower(): value.strip()
        for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*[\{\"]([^}\"]+)[}\"]", text)
    }
    authors = [part.strip() for part in re.split(r"\s+and\s+", fields.get("author", "")) if part.strip()]
    keywords = [part.strip() for part in re.split(r"[;,]", fields.get("keywords", "")) if part.strip()]
    return _clean_metadata(
        {
            "title": fields.get("title"),
            "authors": authors,
            "year": fields.get("year"),
            "doi": fields.get("doi"),
            "publication_title": fields.get("journal") or fields.get("booktitle"),
            "abstract": fields.get("abstract"),
            "keywords": keywords,
            "item_type": entry_type_match.group(1).lower() if entry_type_match else None,
        }
    )


def _parse_ris(path: Path) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([A-Z0-9]{2})\s+-\s+(.*)$", line.strip())
        if match:
            fields.setdefault(match.group(1), []).append(match.group(2).strip())
    year = (fields.get("PY") or fields.get("Y1") or [None])[0]
    if year:
        year = str(year)[:4]
    return _clean_metadata(
        {
            "title": (fields.get("TI") or fields.get("T1") or [None])[0],
            "authors": fields.get("AU") or [],
            "year": year,
            "doi": (fields.get("DO") or [None])[0],
            "publication_title": (fields.get("JO") or fields.get("T2") or [None])[0],
            "abstract": (fields.get("AB") or [None])[0],
            "keywords": fields.get("KW") or [],
            "item_type": (fields.get("TY") or [None])[0],
        }
    )


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value not in (None, "", [])}
