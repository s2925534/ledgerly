from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ledgerly.core.yamlio import read_yaml
from ledgerly.engine.artefacts import register_artefact
from ledgerly.engine.claims import list_claims
from ledgerly.engine.research_questions import list_research_questions


SUPPORTED_ARTEFACT_TYPES = {
    "source-summary-report": "artefacts/reports/source-summary-report.md",
    "literature-review-matrix": "artefacts/tables/literature-review-matrix.md",
    "claim-evidence-table": "artefacts/tables/claim-evidence-table.md",
    "research-question-brief": "artefacts/reports/research-question-brief.md",
    "data-profile-summary": "artefacts/reports/data-profile-summary.md",
    "paper-draft": "artefacts/papers/paper-draft-{rq_id}.md",
}


@dataclass(frozen=True)
class ArtefactCreationResult:
    record: dict[str, Any]
    path: Path


def create_deterministic_artefact(
    workspace: Path,
    artefact_type: str,
    *,
    title: str | None = None,
    include_maybe: bool = False,
    rq_id: str | None = None,
    overwrite: bool = False,
) -> ArtefactCreationResult:
    """Create a deterministic, non-AI artefact from existing workspace state."""
    if artefact_type not in SUPPORTED_ARTEFACT_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_ARTEFACT_TYPES))
        raise ValueError(f"Unsupported artefact type: {artefact_type!r}. Expected one of: {allowed}")
    if artefact_type == "paper-draft" and not rq_id:
        raise ValueError("paper-draft requires rq_id: a paper draft is always scoped to one research question.")

    path_template = SUPPORTED_ARTEFACT_TYPES[artefact_type]
    relative_path = path_template.format(rq_id=rq_id) if "{rq_id}" in path_template else path_template
    output_path = _safe_workspace_path(workspace, relative_path)
    if output_path.exists() and not overwrite:
        raise ValueError(f"Artefact already exists: {output_path}. Use overwrite=True to replace it.")

    sources = _selected_sources(workspace, include_maybe=include_maybe)
    claims = list_claims(workspace)
    research_questions = list_research_questions(workspace)
    data_profiles = _data_profiles(workspace)
    resolved_title = title or (f"Paper Draft: {rq_id}" if artefact_type == "paper-draft" else _default_title(artefact_type))

    if artefact_type == "source-summary-report":
        content = _source_summary_report(resolved_title, sources, include_maybe=include_maybe)
        linked_sources = _source_ids(sources)
        linked_rqs: list[str] = []
    elif artefact_type == "literature-review-matrix":
        content = _literature_review_matrix(resolved_title, sources, rq_id=rq_id)
        linked_sources = _source_ids(sources)
        linked_rqs = [rq_id] if rq_id else []
    elif artefact_type == "claim-evidence-table":
        content = _claim_evidence_table(resolved_title, claims)
        linked_sources = sorted({source_id for claim in claims for source_id in claim.get("linked_sources", [])})
        linked_rqs = sorted({rq for claim in claims for rq in claim.get("linked_research_questions", [])})
    elif artefact_type == "research-question-brief":
        content = _research_question_brief(resolved_title, research_questions, rq_id=rq_id)
        linked_sources = []
        linked_rqs = _research_question_ids(research_questions, rq_id=rq_id)
    elif artefact_type == "paper-draft":
        rq = _find_research_question(research_questions, rq_id)
        if rq is None:
            raise ValueError(f"Unknown research question: {rq_id}")
        rq_claims = [claim for claim in claims if rq_id in (claim.get("linked_research_questions") or [])]
        content = _paper_draft(resolved_title, rq, sources, rq_claims)
        linked_sources = _source_ids(sources)
        linked_rqs = [rq_id]
    else:
        content = _data_profile_summary(resolved_title, data_profiles)
        linked_sources = sorted({str(profile.get("source_id")) for profile in data_profiles if profile.get("source_id")})
        linked_rqs = []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    record = register_artefact(
        workspace,
        title=resolved_title,
        artefact_type=artefact_type,
        path=output_path,
        linked_sources=linked_sources,
        linked_research_questions=linked_rqs,
        requires_user_review=True,
    )
    return ArtefactCreationResult(record=record, path=output_path)


def _safe_workspace_path(workspace: Path, relative_path: str) -> Path:
    path = workspace / relative_path
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError(f"Artefact output path must stay inside the workspace: {relative_path}") from exc
    return path


def _selected_sources(workspace: Path, *, include_maybe: bool) -> list[dict[str, Any]]:
    allowed = {"accepted"}
    if include_maybe:
        allowed.add("maybe")
    register = read_yaml(workspace / "source-register.yaml")
    return [
        source
        for source in register.get("sources", [])
        if isinstance(source, dict) and source.get("status") in allowed
    ]


def _data_profiles(workspace: Path) -> list[dict[str, Any]]:
    profile_dir = workspace / "outputs" / "data-profiles"
    if not profile_dir.exists():
        return []
    profiles = []
    for path in sorted(profile_dir.glob("*.yaml")):
        item = read_yaml(path)
        if isinstance(item, dict):
            item["_path"] = str(path)
            profiles.append(item)
    return profiles


def _default_title(artefact_type: str) -> str:
    return artefact_type.replace("-", " ").title()


def _source_ids(sources: list[dict[str, Any]]) -> list[str]:
    return [str(source.get("source_id")) for source in sources if source.get("source_id")]


def _find_research_question(research_questions: dict[str, list[dict[str, Any]]], rq_id: str) -> dict[str, Any] | None:
    for items in research_questions.values():
        for item in items:
            if item.get("id") == rq_id:
                return item
    return None


def _research_question_ids(research_questions: dict[str, list[dict[str, Any]]], *, rq_id: str | None) -> list[str]:
    ids = [
        str(item.get("id"))
        for section in research_questions.values()
        for item in section
        if item.get("id") and (rq_id is None or item.get("id") == rq_id)
    ]
    return ids


def _unknown(value: Any) -> str:
    if value in (None, "", []):
        return "Unknown"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "Unknown"
    return str(value)


def _metadata(source: dict[str, Any]) -> dict[str, Any]:
    citation = source.get("citation_metadata")
    if isinstance(citation, dict):
        return citation
    return {}


def _source_title(source: dict[str, Any]) -> str:
    metadata = _metadata(source)
    return _unknown(source.get("zotero_title") or metadata.get("title") or source.get("file_name"))


def _source_authors(source: dict[str, Any]) -> str:
    metadata = _metadata(source)
    return _unknown(source.get("zotero_creators") or metadata.get("authors"))


def _source_year(source: dict[str, Any]) -> str:
    metadata = _metadata(source)
    return _unknown(source.get("zotero_year") or metadata.get("year"))


def _source_doi(source: dict[str, Any]) -> str:
    metadata = _metadata(source)
    return _unknown(source.get("zotero_doi") or metadata.get("doi"))


def _header(title: str, artefact_type: str) -> list[str]:
    return [
        f"# {title}",
        "",
        f"- Artefact type: {artefact_type}",
        "- Generation method: Deterministic workspace extraction",
        "- AI used: No",
        "- No interpretation performed.",
        "- User review required.",
        "",
    ]


def _source_summary_report(title: str, sources: list[dict[str, Any]], *, include_maybe: bool) -> str:
    lines = _header(title, "source-summary-report")
    lines.extend(
        [
            "## Scope",
            "",
            f"- Included statuses: {'accepted, maybe' if include_maybe else 'accepted'}",
            "- Ignored sources are excluded.",
            "",
            "## Sources",
            "",
            "| Source ID | Status | Title | Authors | Year | DOI | File | Conversion |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if not sources:
        lines.append("| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown |")
    for source in sources:
        conversion = source.get("conversion")
        conversion_status = conversion.get("status") if isinstance(conversion, dict) else "Unknown"
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(source.get("source_id")),
                    _unknown(source.get("status")),
                    _source_title(source),
                    _source_authors(source),
                    _source_year(source),
                    _source_doi(source),
                    _unknown(source.get("file_name")),
                    _unknown(conversion_status),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _literature_review_matrix(title: str, sources: list[dict[str, Any]], *, rq_id: str | None) -> str:
    lines = _header(title, "literature-review-matrix")
    lines.extend(
        [
            "## Matrix",
            "",
            f"- Research question filter: {_unknown(rq_id)}",
            "",
            "| Source ID | Title | Authors | Year | DOI | Linked research question | User notes required |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if not sources:
        lines.append("| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Yes |")
    for source in sources:
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(source.get("source_id")),
                    _source_title(source),
                    _source_authors(source),
                    _source_year(source),
                    _source_doi(source),
                    _unknown(rq_id),
                    "Yes",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _claim_evidence_table(title: str, claims: list[dict[str, Any]]) -> str:
    lines = _header(title, "claim-evidence-table")
    lines.extend(
        [
            "## Claims",
            "",
            "| Claim ID | Claim | Linked sources | Linked research questions | Evidence status |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if not claims:
        lines.append("| Unknown | No claim recorded | Not linked | Not linked | No claim recorded |")
    for claim in claims:
        linked_sources = claim.get("linked_sources") or []
        evidence_status = "Linked evidence" if linked_sources else "No linked evidence"
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(claim.get("id")),
                    _unknown(claim.get("text")),
                    _unknown(linked_sources) if linked_sources else "Not linked",
                    _unknown(claim.get("linked_research_questions")) if claim.get("linked_research_questions") else "Not linked",
                    evidence_status,
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _research_question_brief(
    title: str,
    research_questions: dict[str, list[dict[str, Any]]],
    *,
    rq_id: str | None,
) -> str:
    lines = _header(title, "research-question-brief")
    for section_name, label in (
        ("approved", "Approved research questions"),
        ("candidates", "Candidate research questions"),
        ("rejected", "Rejected or archived research questions"),
    ):
        lines.extend([f"## {label}", "", "| RQ ID | Question | Status | Subquestions |", "| --- | --- | --- | --- |"])
        items = [
            item
            for item in research_questions.get(section_name, [])
            if isinstance(item, dict) and (rq_id is None or item.get("id") == rq_id)
        ]
        if not items:
            lines.append("| Unknown | Unknown | Unknown | Unknown |")
        for item in items:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _unknown(item.get("id")),
                        _unknown(item.get("question")),
                        _unknown(item.get("status") or section_name),
                        _unknown(item.get("subquestions")),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _paper_draft(
    title: str,
    rq: dict[str, Any],
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> str:
    """A deterministic, AI-free paper skeleton: hypothesis statement,
    background/literature review from accepted sources, evidence assembled
    from the real claim ledger, and an explicitly unfinished conclusion.

    This tool never auto-classifies a claim as supporting or refuting a
    hypothesis — that's a judgment call, not a deterministic fact extraction,
    so it stays a placeholder for the researcher (or a future explicit,
    reviewable AI-assisted pass) rather than a guess presented as done.
    """
    lines = _header(title, "paper-draft")
    lines.extend(
        [
            "## Research Question",
            "",
            f"- ID: {_unknown(rq.get('id'))}",
            f"- Question: {_unknown(rq.get('question'))}",
            f"- Hypothesis: {_unknown(rq.get('hypothesis'))}",
            f"- Question type: {_unknown(rq.get('question_type'))}",
            f"- Evidence that would SUPPORT the hypothesis: {_unknown(rq.get('proof_criteria'))}",
            f"- Evidence that would REFUTE the hypothesis: {_unknown(rq.get('disproof_criteria'))}",
            "",
            "## Background / Literature Review",
            "",
            "| Source ID | Title | Authors | Year | DOI |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if not sources:
        lines.append("| Unknown | No accepted sources yet | Unknown | Unknown | Unknown |")
    for source in sources:
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(source.get("source_id")),
                    _source_title(source),
                    _source_authors(source),
                    _source_year(source),
                    _source_doi(source),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            "Claims from the local claim ledger linked to this research question "
            f"(`ledgerly claims add \"...\" --rq {_unknown(rq.get('id'))}` to link more). Sorting these into "
            "evidence for vs. against the hypothesis, and drafting supporting prose, is not done automatically "
            "— review each claim below and write your own analysis, or use an AI-assisted drafting pass once "
            "available (gated behind explicit review; see AGENTS.md's Core Rule: No Hallucinations).",
            "",
            "| Claim ID | Claim | Status | Linked sources |",
            "| --- | --- | --- | --- |",
        ]
    )
    if not claims:
        lines.append("| Unknown | No claims linked to this research question yet | Unknown | Unknown |")
    for claim in claims:
        linked_sources = claim.get("linked_sources") or []
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(claim.get("id")),
                    _unknown(claim.get("text")),
                    _unknown(claim.get("status")),
                    _unknown(linked_sources) if linked_sources else "Not linked",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "**Status: DRAFT — no conclusion has been written.**",
            "",
            "This tool never generates a prove-or-disprove conclusion without evidence grounding. Write your own "
            "conclusion here once the evidence above has been reviewed, or use an AI-assisted drafting pass once "
            "available. This document requires human review before it can be considered final.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _data_profile_summary(title: str, data_profiles: list[dict[str, Any]]) -> str:
    lines = _header(title, "data-profile-summary")
    lines.extend(
        [
            "## Data profiles",
            "",
            "- Full datasets are not copied into this artefact.",
            "",
            "| Source ID | Data type | Rows/items | Columns/tables | Profile path |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if not data_profiles:
        lines.append("| Unknown | Unknown | Unknown | Unknown | Unknown |")
    for item in data_profiles:
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        rows = profile.get("row_count") or profile.get("item_count") or "Unknown"
        columns = profile.get("column_count") or profile.get("table_count") or profile.get("key_count") or "Unknown"
        lines.append(
            "| "
            + " | ".join(
                [
                    _unknown(item.get("source_id")),
                    _unknown(profile.get("type")),
                    _unknown(rows),
                    _unknown(columns),
                    _unknown(item.get("_path")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
