from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.conversion import extract_text
from researchboss.engine.doc_validation import validate_document
from researchboss.engine.document_targets import resolve_document_target
from researchboss.engine.vault import create_document_version


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD = f"{{{WORD_NAMESPACE}}}"


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
    version_id: str
    source_snapshot_version_id: str


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
    target_suffix = resolved_target.path.suffix.lower()
    if target_suffix not in {".md", ".txt", ".docx", ".pdf"}:
        raise ValueError(
            "Deterministic citation plan application currently supports Markdown, TXT, DOCX, and PDF-to-Markdown targets."
        )

    plan_yaml = plan_path or _plan_path(workspace, resolved_target.path, ".yaml")
    if not plan_yaml.exists():
        raise ValueError(f"Citation plan does not exist: {plan_yaml}")
    plan = read_yaml(plan_yaml)
    insertions = [item for item in plan.get("insertions", []) if isinstance(item, dict)]
    approved = [
        item
        for item in insertions
        if str(item.get("review_status") or "").lower() in {"accepted", "approved"}
    ]

    if target_suffix == ".docx":
        output_path = _applied_path(workspace, resolved_target.path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        applied = _apply_to_docx(resolved_target.path, output_path, approved, plan.get("references") or {})
    else:
        if target_suffix == ".pdf":
            text = extract_text(resolved_target.path)
            output_path = _applied_path(workspace, resolved_target.path, suffix=".md")
        else:
            text = resolved_target.path.read_text(encoding="utf-8", errors="replace")
            output_path = _applied_path(workspace, resolved_target.path)
        revised, applied = _apply_to_text(text, approved)
        revised = _append_references(revised, plan.get("references") or {})
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(revised, encoding="utf-8")

    validation_report_ref = plan.get("validation_report")
    validation_report_id = Path(str(validation_report_ref)).stem if validation_report_ref else None
    citation_plan_id = plan_yaml.stem

    source_snapshot = create_document_version(
        workspace,
        str(resolved_target.path),
        creation_reason="pre_citation_apply_snapshot",
        source_command="cite apply",
        cwd=cwd,
    )
    applied_version = create_document_version(
        workspace,
        str(output_path),
        creation_reason="citation_apply",
        source_command="cite apply",
        parent_version_id=source_snapshot["version_id"],
        validation_report_id=validation_report_id,
        citation_plan_id=citation_plan_id,
        cwd=cwd,
    )

    report = {
        "version": 1,
        "target": str(resolved_target.path),
        "plan_path": str(plan_yaml),
        "output_path": str(output_path),
        "target_format": target_suffix.lstrip(".") or "unknown",
        "output_format": output_path.suffix.lower().lstrip(".") or "unknown",
        "original_document_modified": False,
        "applied_insertions": applied,
        "skipped_insertions": len(insertions) - applied,
        "document_version_id": applied_version["version_id"],
        "source_snapshot_version_id": source_snapshot["version_id"],
    }
    report_path = _applied_report_path(workspace, resolved_target.path)
    write_yaml(report_path, report)
    return CitationApplyRun(
        applied=applied,
        skipped=len(insertions) - applied,
        output_path=output_path,
        report_path=report_path,
        version_id=applied_version["version_id"],
        source_snapshot_version_id=source_snapshot["version_id"],
    )


def _apply_to_text(text: str, insertions: list[dict[str, Any]]) -> tuple[str, int]:
    revised = text
    applied = 0
    for insertion in insertions:
        sentence = str(insertion.get("target_sentence") or "").strip()
        citation = str(insertion.get("suggested_inline_citation") or "").strip()
        if not sentence or not citation or citation in sentence:
            continue
        revised_sentence = _insert_citation(sentence, citation)
        if sentence in revised:
            revised = revised.replace(sentence, revised_sentence, 1)
            applied += 1
            continue
        pattern = _whitespace_flexible_pattern(sentence)
        match = pattern.search(revised)
        if match and citation not in match.group(0):
            revised = revised[: match.start()] + _insert_citation(match.group(0), citation) + revised[match.end() :]
            applied += 1
    return revised, applied


def _whitespace_flexible_pattern(text: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in text.split()]
    return re.compile(r"\s+".join(parts))


def _apply_to_docx(
    source_path: Path,
    output_path: Path,
    insertions: list[dict[str, Any]],
    references: dict[str, Any],
) -> int:
    with zipfile.ZipFile(source_path) as source_docx:
        document_xml = source_docx.read("word/document.xml")
        root = ElementTree.fromstring(document_xml)
        applied = _apply_insertions_to_docx_root(root, insertions)
        _append_docx_references(root, references)
        updated_xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as revised_docx:
            for item in source_docx.infolist():
                if item.filename == "word/document.xml":
                    revised_docx.writestr(item, updated_xml)
                else:
                    revised_docx.writestr(item, source_docx.read(item.filename))
    return applied


def _apply_insertions_to_docx_root(root: ElementTree.Element, insertions: list[dict[str, Any]]) -> int:
    applied = 0
    paragraphs = root.findall(f".//{WORD}p")
    for insertion in insertions:
        sentence = str(insertion.get("target_sentence") or "").strip()
        citation = str(insertion.get("suggested_inline_citation") or "").strip()
        if not sentence or not citation:
            continue
        for paragraph in paragraphs:
            paragraph_text = _docx_paragraph_text(paragraph)
            if sentence in paragraph_text and citation not in paragraph_text:
                _replace_docx_paragraph_text(paragraph, paragraph_text.replace(sentence, _insert_citation(sentence, citation), 1))
                applied += 1
                break
    return applied


def _append_docx_references(root: ElementTree.Element, references: dict[str, Any]) -> None:
    accepted = references.get("accepted_workspace_evidence") if isinstance(references, dict) else []
    lines = [str(item.get("reference")) for item in accepted if isinstance(item, dict) and item.get("reference")]
    if not lines:
        return
    body = root.find(f".//{WORD}body")
    if body is None:
        return
    body.append(_docx_paragraph("References"))
    for line in lines:
        body.append(_docx_paragraph(line))


def _docx_paragraph(text: str) -> ElementTree.Element:
    paragraph = ElementTree.Element(f"{WORD}p")
    run = ElementTree.SubElement(paragraph, f"{WORD}r")
    text_node = ElementTree.SubElement(run, f"{WORD}t")
    text_node.text = text
    return paragraph


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(text_node.text or "" for text_node in paragraph.findall(f".//{WORD}t"))


def _replace_docx_paragraph_text(paragraph: ElementTree.Element, text: str) -> None:
    text_nodes = paragraph.findall(f".//{WORD}t")
    if not text_nodes:
        run = ElementTree.SubElement(paragraph, f"{WORD}r")
        text_node = ElementTree.SubElement(run, f"{WORD}t")
        text_node.text = text
        return
    text_nodes[0].text = text
    for text_node in text_nodes[1:]:
        text_node.text = ""


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


def _applied_path(workspace: Path, target_path: Path, *, suffix: str | None = None) -> Path:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in target_path.stem).strip("-") or "target"
    output_suffix = suffix or target_path.suffix.lower() or ".md"
    return workspace / "outputs" / "citation-plans" / f"citation-applied-{stem}{output_suffix}"


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
