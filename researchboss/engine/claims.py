from __future__ import annotations

from pathlib import Path
from typing import Any

from researchboss.core.yamlio import read_yaml, write_yaml


def list_claims(workspace: Path) -> list[dict[str, Any]]:
    ledger = read_yaml(workspace / "claims-ledger.yaml")
    return [claim for claim in ledger.get("claims", []) if isinstance(claim, dict)]


def add_claim(
    workspace: Path,
    *,
    text: str,
    linked_sources: list[str] | None = None,
    linked_research_questions: list[str] | None = None,
) -> dict[str, Any]:
    ledger_path = workspace / "claims-ledger.yaml"
    ledger = read_yaml(ledger_path)
    claims = list_claims(workspace)
    claim = {
        "id": f"claim-{len(claims) + 1:03d}",
        "text": text,
        "linked_sources": linked_sources or [],
        "linked_research_questions": linked_research_questions or [],
        "status": "active",
    }
    claims.append(claim)
    ledger["claims"] = claims
    write_yaml(ledger_path, ledger)
    return claim


def citation_gap_claims(workspace: Path) -> list[dict[str, Any]]:
    return [claim for claim in list_claims(workspace) if not claim.get("linked_sources")]


def write_citation_gap_report(workspace: Path) -> Path:
    gaps = citation_gap_claims(workspace)
    output_path = workspace / "outputs" / "validation" / "citation-gaps.yaml"
    write_yaml(output_path, {"version": 1, "gap_count": len(gaps), "claims": gaps})
    return output_path
