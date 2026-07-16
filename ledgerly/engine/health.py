from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgerly.core.constants import WORKSPACE_DIRS, WORKSPACE_FILES
from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.claims import citation_gap_claims
from ledgerly.engine.research_questions import check_research_question_readiness
from ledgerly.engine.sources import ALLOWED_EXTENSIONS, source_counts


def workspace_health_report(workspace: Path) -> dict[str, Any]:
    required_files = [
        WORKSPACE_FILES.research_context,
        WORKSPACE_FILES.source_register,
        WORKSPACE_FILES.accepted_sources,
        WORKSPACE_FILES.ignored_sources,
        WORKSPACE_FILES.maybe_sources,
        WORKSPACE_FILES.artefact_registry,
        WORKSPACE_FILES.claims_ledger,
    ]
    missing_files = [relative for relative in required_files if not (workspace / relative).exists()]
    missing_dirs = [relative for relative in WORKSPACE_DIRS if not (workspace / relative).is_dir()]
    register = read_yaml(workspace / "source-register.yaml") if (workspace / "source-register.yaml").exists() else {}
    sources = [source for source in register.get("sources", []) if isinstance(source, dict)]
    failed_conversions = [
        source.get("source_id")
        for source in sources
        if isinstance(source.get("conversion"), dict) and source["conversion"].get("status") == "failed"
    ]
    unsupported_files = []
    original_root = workspace / "sources_original"
    if original_root.is_dir():
        unsupported_files = [
            str(path.relative_to(workspace))
            for path in original_root.rglob("*")
            if path.is_file() and path.suffix.lower() not in ALLOWED_EXTENSIONS
        ]
    rq_report = check_research_question_readiness(workspace)
    report = {
        "version": 1,
        "status": "ok" if not missing_files and not missing_dirs and not failed_conversions else "needs_review",
        "missing_files": missing_files,
        "missing_dirs": missing_dirs,
        "source_counts": source_counts(workspace) if (workspace / "source-register.yaml").exists() else {},
        "failed_conversions": failed_conversions,
        "unsupported_files": unsupported_files,
        "citation_gap_count": len(citation_gap_claims(workspace)) if (workspace / "claims-ledger.yaml").exists() else 0,
        "rq_readiness_checked": rq_report["checked_count"],
    }
    write_yaml(workspace / "outputs" / "validation" / "workspace-health.yaml", report)
    return report
