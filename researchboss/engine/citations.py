from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchboss.core.yamlio import write_yaml
from researchboss.engine.doc_validation import validate_document


@dataclass(frozen=True)
class CitationPlanRun:
    plan: dict[str, Any]
    yaml_path: Path
    markdown_path: Path


def create_citation_plan(
    workspace: Path,
    target: str,
    *,
    source_paths: list[Path] | None = None,
    guideline_ids: list[str] | None = None,
    use_default_guidelines: bool = True,
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
    for item in report.get("missing_citations", []):
        source_id = item.get("best_source_id")
        source = source_map.get(str(source_id))
        if not source:
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
        "insertions": insertions,
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


def _inline_citation(source: dict[str, Any]) -> str:
    author = _first_author(source.get("authors"))
    year = source.get("year") if source.get("year") not in (None, "", "Unknown") else "n.d."
    return f"({author}, {year})"


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
