from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from corroborly.core.yamlio import read_yaml, write_yaml
from corroborly.engine.conversion import CONVERTIBLE_EXTENSIONS, extract_text


GUIDELINE_TEXT_EXTENSIONS = CONVERTIBLE_EXTENSIONS | {".html", ".htm"}
GUIDELINE_SCOPES = {
    "validation",
    "citation",
    "structure",
    "style",
    "journal_submission",
    "thesis",
    "supervisor",
    "rubric",
    "all_purpose",
}
STYLE_PATTERNS = {
    "apa7": [r"\bapa\s*7\b", r"american psychological association 7"],
    "apa6": [r"\bapa\s*6\b", r"american psychological association 6"],
    "vancouver": [r"\bvancouver\b"],
    "ieee": [r"\bieee\b"],
    "mla9": [r"\bmla\s*9\b", r"modern language association 9"],
}


@dataclass(frozen=True)
class GuidelineRegistration:
    record: dict[str, Any]
    snapshot_path: Path
    text_path: Path


def register_guideline(
    workspace: Path,
    source: str,
    *,
    title: str | None = None,
    scopes: list[str] | None = None,
) -> GuidelineRegistration:
    source = source.strip()
    if not source:
        raise ValueError("Guideline source is required.")

    registry_path = workspace / "guidelines" / "guidelines.yaml"
    registry = read_yaml(registry_path) if registry_path.exists() else {"version": 1, "guidelines": []}
    guidelines = [item for item in registry.get("guidelines", []) if isinstance(item, dict)]
    guideline_id = f"guideline-{len(guidelines) + 1:03d}"
    resolved_scopes = _validate_scopes(scopes or ["all_purpose"])

    if _is_url(source):
        snapshot_path = _snapshot_remote(workspace, guideline_id, source)
        source_kind = "remote_url"
        original_location = source
    else:
        original_path = Path(source).expanduser()
        if not original_path.exists() or not original_path.is_file():
            raise ValueError(f"Guideline file does not exist: {source}")
        snapshot_path = _snapshot_local(workspace, guideline_id, original_path)
        source_kind = "local_file"
        original_location = str(original_path.resolve())

    text = _guideline_text(snapshot_path)
    text_path = workspace / "guidelines" / "text" / f"{guideline_id}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")

    record = {
        "id": guideline_id,
        "title": title or _default_title(source, snapshot_path),
        "source_kind": source_kind,
        "original_location": original_location,
        "snapshot_path": str(snapshot_path),
        "text_path": str(text_path),
        "file_ext": snapshot_path.suffix.lower().lstrip("."),
        "scopes": resolved_scopes,
        "ai_used": False,
    }
    guidelines.append(record)
    registry["guidelines"] = guidelines
    write_yaml(registry_path, registry)
    return GuidelineRegistration(record=record, snapshot_path=snapshot_path, text_path=text_path)


def list_guidelines(workspace: Path) -> list[dict[str, Any]]:
    registry_path = workspace / "guidelines" / "guidelines.yaml"
    if not registry_path.exists():
        return []
    registry = read_yaml(registry_path)
    return [item for item in registry.get("guidelines", []) if isinstance(item, dict)]


def set_default_guidelines(workspace: Path, guideline_ids: list[str]) -> dict[str, Any]:
    resolved_ids = _validate_guideline_ids(workspace, guideline_ids)
    context_path = workspace / "research-context.yaml"
    context = read_yaml(context_path)
    guideline_config = context.get("guidelines") if isinstance(context.get("guidelines"), dict) else {}
    guideline_config["default_guideline_ids"] = resolved_ids
    guideline_config["priority"] = resolved_ids
    context["guidelines"] = guideline_config
    write_yaml(context_path, context)
    return guideline_config


def default_guideline_ids(workspace: Path) -> list[str]:
    context = read_yaml(workspace / "research-context.yaml")
    guideline_config = context.get("guidelines") if isinstance(context.get("guidelines"), dict) else {}
    defaults = guideline_config.get("default_guideline_ids") or []
    return [str(item) for item in defaults if item]


def resolve_guidelines(
    workspace: Path,
    *,
    explicit_ids: list[str] | None = None,
    use_defaults: bool = True,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    explicit_ids = _dedupe(explicit_ids or [])
    selected_ids = explicit_ids or (default_guideline_ids(workspace) if use_defaults else [])
    if not selected_ids:
        return []

    records = {str(item.get("id")): item for item in list_guidelines(workspace) if item.get("id")}
    missing = [guideline_id for guideline_id in selected_ids if guideline_id not in records]
    if missing:
        raise ValueError(f"Unknown guideline id(s): {', '.join(missing)}")

    normalized_scope = _normalize_scope(scope) if scope else None
    resolved = []
    for index, guideline_id in enumerate(selected_ids, start=1):
        record = dict(records[guideline_id])
        scopes = record.get("scopes") or []
        if normalized_scope and "all_purpose" not in scopes and normalized_scope not in scopes:
            continue
        record["precedence"] = index
        record["selection_source"] = "explicit" if explicit_ids else "default"
        resolved.append(record)
    return resolved


def guideline_conflict_report(workspace: Path) -> dict[str, Any]:
    guidelines = list_guidelines(workspace)
    context = read_yaml(workspace / "research-context.yaml")
    citation = context.get("citation") if isinstance(context.get("citation"), dict) else {}
    configured_style = str(citation.get("custom_style") or citation.get("style") or "Unknown")
    configured_markers = _style_markers(configured_style)

    guideline_rows = []
    conflicts = []
    for guideline in guidelines:
        text = _read_guideline_text(guideline)
        markers = _style_markers(text)
        row = {
            "id": guideline.get("id"),
            "title": guideline.get("title"),
            "scopes": guideline.get("scopes") or [],
            "detected_style_markers": sorted(markers),
        }
        guideline_rows.append(row)
        conflicting_markers = sorted(markers - configured_markers)
        if configured_markers and conflicting_markers:
            conflicts.append(
                {
                    "kind": "citation_style_conflict",
                    "guideline_id": guideline.get("id"),
                    "configured_style": configured_style,
                    "configured_markers": sorted(configured_markers),
                    "guideline_markers": sorted(markers),
                    "conflicting_markers": conflicting_markers,
                    "status": "human_review_required",
                }
            )

    conflicts.extend(_scope_priority_conflicts(guidelines))
    report = {
        "version": 1,
        "configured_citation_style": configured_style,
        "configured_style_markers": sorted(configured_markers),
        "guidelines_checked": guideline_rows,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "limitations": [
            "This report only flags explicit deterministic style markers and priority tensions.",
            "It does not interpret prose or decide which guideline should win.",
        ],
    }
    output_path = workspace / "outputs" / "validation" / "guideline-conflicts.yaml"
    write_yaml(output_path, report)
    return report


def build_ai_guideline_context(
    workspace: Path,
    *,
    full_guidelines: bool = False,
    max_excerpt_chars: int = 1200,
) -> dict[str, Any]:
    rows = []
    for guideline in list_guidelines(workspace):
        text = _read_guideline_text(guideline)
        included_text = text if full_guidelines else text[: max(0, max_excerpt_chars)]
        rows.append(
            {
                "id": guideline.get("id"),
                "title": guideline.get("title"),
                "scopes": guideline.get("scopes") or [],
                "selection_policy": "full_text_explicit_opt_in" if full_guidelines else "excerpt_default",
                "text": included_text,
                "text_truncated": not full_guidelines and len(text) > max_excerpt_chars,
                "full_guideline_included": full_guidelines,
            }
        )
    context = {
        "version": 1,
        "ai_used": False,
        "full_guidelines_included": full_guidelines,
        "requires_explicit_full_guidelines_opt_in": True,
        "guideline_count": len(rows),
        "guidelines": rows,
    }
    output_path = workspace / "outputs" / "validation" / "ai-guideline-context.yaml"
    write_yaml(output_path, context)
    return context


def _snapshot_local(workspace: Path, guideline_id: str, source_path: Path) -> Path:
    snapshot_path = workspace / "guidelines" / "snapshots" / f"{guideline_id}{source_path.suffix.lower()}"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, snapshot_path)
    return snapshot_path


def _read_guideline_text(guideline: dict[str, Any]) -> str:
    text_path = guideline.get("text_path")
    if not text_path:
        return ""
    path = Path(str(text_path))
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _style_markers(text: str) -> set[str]:
    normalized = text.lower()
    markers = set()
    for marker, patterns in STYLE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            markers.add(marker)
    return markers


def _scope_priority_conflicts(guidelines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoped = [
        guideline
        for guideline in guidelines
        if any(scope in (guideline.get("scopes") or []) for scope in {"journal_submission", "thesis", "supervisor", "rubric"})
    ]
    if len(scoped) <= 1:
        return []
    return [
        {
            "kind": "guideline_priority_review",
            "guideline_ids": [guideline.get("id") for guideline in scoped],
            "scopes": {str(guideline.get("id")): guideline.get("scopes") or [] for guideline in scoped},
            "status": "human_review_required",
            "message": "Multiple high-authority guideline scopes are registered; confirm precedence before applying edits.",
        }
    ]


def _snapshot_remote(workspace: Path, guideline_id: str, source: str) -> Path:
    suffix = Path(urlparse(source).path).suffix.lower() or ".html"
    snapshot_path = workspace / "guidelines" / "snapshots" / f"{guideline_id}{suffix}"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(source, timeout=30) as response:
        snapshot_path.write_bytes(response.read())
    return snapshot_path


def _guideline_text(snapshot_path: Path) -> str:
    suffix = snapshot_path.suffix.lower()
    if suffix in {".html", ".htm"}:
        html = snapshot_path.read_text(encoding="utf-8", errors="replace")
        return _html_to_text(html)
    if suffix in GUIDELINE_TEXT_EXTENSIONS:
        return extract_text(snapshot_path)
    raise ValueError(f"Unsupported guideline file extension: {suffix}")


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip() + "\n"


def _default_title(source: str, snapshot_path: Path) -> str:
    if _is_url(source):
        parsed = urlparse(source)
        return Path(parsed.path).name or parsed.netloc or "Remote guideline"
    return snapshot_path.stem.replace("-", " ").replace("_", " ").title()


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _validate_scopes(scopes: list[str]) -> list[str]:
    normalized = []
    for scope in scopes:
        item = _normalize_scope(scope)
        if item not in GUIDELINE_SCOPES:
            allowed = ", ".join(sorted(GUIDELINE_SCOPES))
            raise ValueError(f"Invalid guideline scope: {scope!r}. Expected one of: {allowed}")
        if item not in normalized:
            normalized.append(item)
    return normalized


def _validate_guideline_ids(workspace: Path, guideline_ids: list[str]) -> list[str]:
    resolved_ids = _dedupe(guideline_ids)
    known_ids = {str(item.get("id")) for item in list_guidelines(workspace)}
    missing = [guideline_id for guideline_id in resolved_ids if guideline_id not in known_ids]
    if missing:
        raise ValueError(f"Unknown guideline id(s): {', '.join(missing)}")
    return resolved_ids


def _normalize_scope(scope: str) -> str:
    return scope.strip().lower().replace("-", "_").replace(" ", "_")


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    for item in items:
        value = str(item).strip()
        if value and value not in deduped:
            deduped.append(value)
    return deduped
