from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ledgerly.core.constants import WORKSPACE_DIRS, WORKSPACE_FILES
from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.artefacts import list_artefacts
from ledgerly.engine.claims import citation_gap_claims, list_claims
from ledgerly.engine.research_questions import check_research_question_readiness, list_research_questions
from ledgerly.engine.sources import ALLOWED_EXTENSIONS, source_counts

# Files most likely to change when a workspace has activity, checked by
# mtime for the dashboard's "days since last activity" tile. Filesystem
# mtime rather than in-record timestamps so it reflects CLI *and* web/API
# writes alike without needing every record type to carry its own clock.
_ACTIVITY_FILES = [
    WORKSPACE_FILES.source_register,
    WORKSPACE_FILES.claims_ledger,
    WORKSPACE_FILES.artefact_registry,
    WORKSPACE_FILES.research_questions,
    WORKSPACE_FILES.research_question_candidates,
    WORKSPACE_FILES.decisions_md,
    WORKSPACE_FILES.context_changelog_md,
    WORKSPACE_FILES.personal_notes_ledger,
]


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


def corpus_dashboard_summary(workspace: Path) -> dict[str, Any]:
    """At-a-glance workspace stats for the web UI landing page: source counts by
    status, claim counts by status, artefact count, open research question
    count, and days since the workspace was last touched.
    """
    claim_counts: dict[str, int] = {}
    for claim in list_claims(workspace):
        status = claim.get("status", "unknown")
        claim_counts[status] = claim_counts.get(status, 0) + 1
    claim_counts["total"] = sum(claim_counts.values())

    rq_groups = list_research_questions(workspace)
    open_research_question_count = len(rq_groups.get("candidates", [])) + len(rq_groups.get("approved", []))

    last_activity: datetime | None = None
    for relative in _ACTIVITY_FILES:
        path = workspace / relative
        if not path.exists():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if last_activity is None or mtime > last_activity:
            last_activity = mtime
    days_since_last_activity = (datetime.now(timezone.utc) - last_activity).days if last_activity else None

    return {
        "source_counts": source_counts(workspace) if (workspace / "source-register.yaml").exists() else {},
        "claim_counts": claim_counts,
        "artefact_count": len(list_artefacts(workspace)),
        "open_research_question_count": open_research_question_count,
        "days_since_last_activity": days_since_last_activity,
    }
