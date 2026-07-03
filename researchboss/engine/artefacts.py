from __future__ import annotations

from pathlib import Path
from typing import Any

from researchboss.core.yamlio import read_yaml, write_yaml


def list_artefacts(workspace: Path) -> list[dict[str, Any]]:
    registry = read_yaml(workspace / "artefact-registry.yaml")
    return [item for item in registry.get("artefacts", []) if isinstance(item, dict)]


def register_artefact(
    workspace: Path,
    *,
    title: str,
    artefact_type: str,
    path: Path,
    linked_sources: list[str] | None = None,
    linked_research_questions: list[str] | None = None,
    requires_user_review: bool = True,
) -> dict[str, Any]:
    registry_path = workspace / "artefact-registry.yaml"
    registry = read_yaml(registry_path)
    artefacts = [item for item in registry.get("artefacts", []) if isinstance(item, dict)]
    artefact_id = f"artefact-{len(artefacts) + 1:03d}"
    record = {
        "id": artefact_id,
        "title": title,
        "type": artefact_type,
        "path": str(path),
        "linked_sources": linked_sources or [],
        "linked_research_questions": linked_research_questions or [],
        "ai_generated": False,
        "requires_user_review": requires_user_review,
        "review_status": "pending_review" if requires_user_review else "not_required",
    }
    artefacts.append(record)
    registry["artefacts"] = artefacts
    write_yaml(registry_path, registry)
    return record
