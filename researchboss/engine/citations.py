from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.doc_validation import validate_document
from researchboss.engine.document_targets import resolve_document_target


@dataclass(frozen=True)
class CitationPlanRun:
    plan: dict[str, Any]
    yaml_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class CitationApplyRun:
    applied: int
    skipped: int
    output_path: Path
    report_path: Path


def create_citation_plan(
    workspace: Path,
    target: str,
    *,
    source_paths: list[Path] | None = None,
    guideline_ids: list[str] | None = None,
    use_default_guidelines: bool = True,
    allow_candidate_citations: bool = False,
    cwd: Path | None = None,
) -> CitationPlanRun:
    validation = validate_document(
        workspace,
        target,
        source_paths=source_paths,
        guideline_ids=guideline_ids,
        use_default_guidelines=use_default_guidelines,
        cwd=cwd,
    )
    report = validation.report
    source_map = {str(source.get("source_id")): source for source in report.get("sources", [])}
    confidence_map = {
        str(item.get("source_id")): item.get("confidence_score", {})
        for item in report.get("evidence_confidence", [])
    }
    insertions = []
    blocked_candidate_citations = []
    for item in report.get("missing_citations", []):
        source_id = item.get("best_source_id")
        source = source_map.get(str(source_id))
        if not source:
            continue
        if source.get("status") != "accepted" and not allow_candidate_citations:
            blocked_candidate_citations.append(
                {
                    "sentence_index": item.get("sentence_index"),
                    "target_sentence": item.get("text"),
                    "source_id": source_id,
                    "source_status": source.get("status"),
                    "reason": "candidate_citations_require_explicit_allow_flag",
                }
            )
            continue
        insertions.append(
            {
                "sentence_index": item.get("sentence_index"),
                "target_sentence": item.get("text"),
                "source_id": source_id,
                "suggested_inline_citation": _inline_citation(source),
                "citation_position": "end_of_sentence_before_final_punctuation",
                "support_status": item.get("support_status"),
                "confidence_score": confidence_map.get(str(source_id), {}).get("score"),
                "review_status": "needs_human_review",
            }
        )

    plan = {
        "version": 1,
        "target": report["target"],
        "validation_report": str(validation.yaml_path),
        "ai_used": False,
        "original_document_modified": False,
        "plan_status": "review_required",
        "allow_candidate_citations": allow_candidate_citations,
        "insertions": insertions,
        "blocked_candidate_citations": blocked_candidate_citations,
        "references": report.get("references", {}),
        "guidelines": report.get("guidelines", []),
        "limitations": [
            "This is a deterministic citation insertion plan only.",
            "It does not edit the original document.",
            "Human review is required before applying any citation.",
        ],
    }
    yaml_path = _plan_path(workspace, Path(str(report["target"]["path"])), ".yaml")
    markdown_path = _plan_path(workspace, Path(str(report["target"]["path"])), ".md")
    write_yaml(yaml_path, plan)
    markdown_path.write_text(_markdown_plan(plan), encoding="utf-8")
    return CitationPlanRun(plan=plan, yaml_path=yaml_path, markdown_path=markdown_path)


def apply_citation_plan(
    workspace: Path,
    target: str,
    *,
    plan_path: Path | None = None,
    cwd: Path | None = None,
) -> CitationApplyRun:
    resolved_target = resolve_document_target(workspace, target, cwd=cwd)
    if resolved_target.path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Deterministic citation plan application currently supports Markdown and TXT targets.")

    plan_yaml = plan_path or _plan_path(workspace, resolved_target.path, ".yaml")
    if not plan_yaml.exists():
        raise ValueError(f"Citation plan does not exist: {plan_yaml}")
    plan = read_yaml(plan_yaml)
    text = resolved_target.path.read_text(encoding="utf-8", errors="replace")
    insertions = [item for item in plan.get("insertions", []) if isinstance(item, dict)]
    approved = [
        item
        for item in insertions
        if str(item.get("review_status") or "").lower() in {"accepted", "approved"}
    ]

    revised = text
    applied = 0
    for insertion in approved:
        sentence = str(insertion.get("target_sentence") or "").strip()
        citation = str(insertion.get("suggested_inline_citation") or "").strip()
        if not sentence or not citation or citation in sentence:
            continue
        revised_sentence = _insert_citation(sentence, citation)
        if sentence in revised:
            revised = revised.replace(sentence, revised_sentence, 1)
            applied += 1

    revised = _append_references(revised, plan.get("references") or {})
    output_path = _applied_path(workspace, resolved_target.path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(revised, encoding="utf-8")

    report = {
        "version": 1,
        "target": str(resolved_target.path),
        "plan_path": str(plan_yaml),
        "output_path": str(output_path),
        "original_document_modified": False,
        "applied_insertions": applied,
        "skipped_insertions": len(insertions) - applied,
    }
    report_path = _applied_report_path(workspace, resolved_target.path)
    write_yaml(report_path, report)
    return CitationApplyRun(applied=applied, skipped=len(insertions) - applied, output_path=output_path, report_path=report_path)


def _inline_citation(source: dict[str, Any]) -> str:
    author = _first_author(source.get("authors"))
    year = source.get("year") if source.get("year") not in (None, "", "Unknown") else "n.d."
    return f"({author}, {year})"


def _insert_citation(sentence: str, citation: str) -> str:
    stripped = sentence.rstrip()
    if stripped.endswith((".", "!", "?")):
        return f"{stripped[:-1]} {citation}{stripped[-1]}"
    return f"{stripped} {citation}"


def _append_references(text: str, references: dict[str, Any]) -> str:
    accepted = references.get("accepted_workspace_evidence") if isinstance(references, dict) else []
    if not accepted:
        return text
    lines = [str(item.get("reference")) for item in accepted if isinstance(item, dict) and item.get("reference")]
    if not lines:
        return text
    base = text.rstrip()
    return base + "\n\n## References\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def _first_author(value: Any) -> str:
    if value in (None, "", [], "Unknown"):
        return "Unknown author"
    if isinstance(value, list):
        value = value[0] if value else "Unknown author"
    text = str(value)
    if "," in text:
        return text.split(",", 1)[0].strip() or "Unknown author"
    parts = re.split(r"\s+", text.strip())
    return parts[-1] if parts else "Unknown author"


def _plan_path(workspace: Path, target_path: Path, suffix: str) -> Path:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in target_path.stem).strip("-") or "target"
    return workspace / "outputs" / "citation-plans" / f"citation-plan-{stem}{suffix}"


def _applied_path(workspace: Path, target_path: Path) -> Path:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in target_path.stem).strip("-") or "target"
    suffix = target_path.suffix.lower() or ".md"
    return workspace / "outputs" / "citation-plans" / f"citation-applied-{stem}{suffix}"


def _applied_report_path(workspace: Path, target_path: Path) -> Path:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in target_path.stem).strip("-") or "target"
    return workspace / "outputs" / "citation-plans" / f"citation-apply-{stem}.yaml"


def _markdown_plan(plan: dict[str, Any]) -> str:
    lines = [
        f"# Citation Plan: {Path(str(plan['target']['path'])).name}",
        "",
        "- AI used: No",
        "- Original document modified: No",
        "- Plan status: review required",
        "",
        "## Proposed Insertions",
        "",
        "| Sentence | Source ID | Suggested citation | Confidence | Review status |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not plan["insertions"]:
        lines.append("| None | None | None | None | None |")
    for insertion in plan["insertions"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(insertion.get("sentence_index") or "Unknown"),
                    str(insertion.get("source_id") or "Unknown"),
                    str(insertion.get("suggested_inline_citation") or "Unknown"),
                    str(insertion.get("confidence_score") or "Unknown"),
                    str(insertion.get("review_status") or "Unknown"),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Limitations", ""])
    for limitation in plan["limitations"]:
        lines.append(f"- {limitation}")
    return "\n".join(lines) + "\n"
