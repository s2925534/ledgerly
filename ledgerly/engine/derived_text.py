from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.claims import list_claims
from ledgerly.engine.conversion import CONVERTIBLE_EXTENSIONS, extract_text
from ledgerly.engine.text_analysis import has_inline_citation, split_sentences
from ledgerly.engine.vault import ensure_vault_dirs, list_document_versions


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def build_derived_text_snapshot(workspace: Path, version_id: str) -> dict[str, Any]:
    """Build a derived text snapshot with stable paragraph/sentence anchors for a document version.

    Anchors (`paragraph_id`, `sentence_id`) are derived fresh from this
    version's own content, not correlated across versions: if the document
    changes, the next version's anchors are assigned from scratch rather
    than trying to track "the same" paragraph across an edit. A paragraph ID
    that silently pointed at the wrong paragraph after an edit would be
    worse than one that simply doesn't exist in the new version. Anchors
    ARE stable across repeated calls for the same version, since extraction
    and segmentation are both deterministic.

    Each sentence gets a `citation_insertion_anchor` describing where a
    citation would land (matching `citations._insert_citation`'s actual
    "before final punctuation" behavior) and, when this version has a
    linked validation report, `claim_ids` (claims whose text appears in the
    sentence) and `reference_ids` (source IDs the validation run associated
    with that exact sentence).

    Section detection only works for `.md` targets: `extract_text()` (the
    same extraction every other deterministic feature uses, so paragraph
    content here stays consistent with validation/citation output) strips
    markdown heading syntax entirely via `_markdown_to_text`, so headings
    are recovered by scanning the *raw* `.md` source for `#`-prefixed lines
    and matching each heading's surviving text against the extracted
    paragraphs in order. `.txt`/`.docx`/`.pdf` targets get no section
    detection (`section_id` stays `None` throughout) rather than a fake
    section map guessed from paragraph length or position — DOCX heading
    styles are not preserved by `_extract_docx_text`, and plain text/PDF
    text has no structural marker to detect at all.
    """
    version = _get_version(workspace, version_id)
    stored_path = Path(str(version["stored_path"]))
    if not stored_path.is_file():
        raise ValueError(f"Stored version file is missing: {stored_path}")
    if stored_path.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        raise ValueError(
            f"Unsupported document extension for derived text extraction: {stored_path.suffix.lower()}"
        )

    text = extract_text(stored_path)
    claims = list_claims(workspace)
    reference_lookup = _reference_lookup(workspace, version)
    heading_queue = _markdown_headings(stored_path) if stored_path.suffix.lower() == ".md" else []
    sections, paragraphs = _segment(text, claims, reference_lookup, heading_queue)

    snapshot = {
        "version": 1,
        "version_id": version_id,
        "target_path": version.get("target_path"),
        "stored_path": str(stored_path),
        "content_hash": version.get("content_hash"),
        "section_count": len(sections),
        "paragraph_count": len(paragraphs),
        "sections": sections,
        "paragraphs": paragraphs,
        "notes": (
            "Anchors are derived fresh from this version's content. They are stable across "
            "repeated calls for the same version, but are not correlated with anchors from "
            "any other version of the same target."
        ),
    }
    layout = ensure_vault_dirs(workspace)
    snapshot_path = layout["derived_text"] / f"{version_id}.yaml"
    write_yaml(snapshot_path, snapshot)
    snapshot["derived_text_path"] = str(snapshot_path)
    return snapshot


def _get_version(workspace: Path, version_id: str) -> dict[str, Any]:
    for record in list_document_versions(workspace):
        if record.get("version_id") == version_id:
            return record
    raise ValueError(f"Unknown document version_id: {version_id}")


def _reference_lookup(workspace: Path, version: dict[str, Any]) -> dict[str, list[str]]:
    report_id = version.get("validation_report_id")
    if not report_id:
        return {}
    report_path = workspace / "outputs" / "validation" / f"{report_id}.yaml"
    if not report_path.is_file():
        return {}
    report = read_yaml(report_path)
    if not isinstance(report, dict):
        return {}

    lookup: dict[str, list[str]] = {}
    for check in report.get("sentence_checks", []):
        if not isinstance(check, dict):
            continue
        source_id = check.get("best_source_id")
        if not source_id:
            continue
        key = _normalize(str(check.get("text") or ""))
        if not key:
            continue
        ids = lookup.setdefault(key, [])
        if source_id not in ids:
            ids.append(source_id)
    return lookup


def _markdown_headings(source_path: Path) -> list[tuple[int, str]]:
    raw = source_path.read_text(encoding="utf-8", errors="replace")
    headings = []
    for line in raw.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            headings.append((len(match.group(1)), match.group(2).strip()))
    return headings


def _segment(
    text: str,
    claims: list[dict[str, Any]],
    reference_lookup: dict[str, list[str]],
    heading_queue: list[tuple[int, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sections: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    current_section_id: Optional[str] = None
    search_from = 0
    paragraph_index = 0
    section_index = 0
    heading_queue = list(heading_queue)

    for block in re.split(r"\n\s*\n", text):
        block_text = block.strip()
        if not block_text:
            continue
        block_start = text.index(block_text, search_from)
        search_from = block_start + len(block_text)

        # A block is treated as a heading only if it exactly matches the next
        # unconsumed heading recovered from the raw source (see
        # `_markdown_headings`) — not by re-detecting `#` syntax, which
        # `extract_text()` has already stripped from `text` by this point.
        if heading_queue and heading_queue[0][1] == block_text:
            level, heading_text = heading_queue.pop(0)
            section_index += 1
            section_id = f"section-{section_index:03d}"
            sections.append(
                {
                    "section_id": section_id,
                    "heading": heading_text,
                    "level": level,
                    "char_start": block_start,
                }
            )
            current_section_id = section_id
            continue

        paragraph_index += 1
        paragraph_id = f"para-{paragraph_index:03d}"
        paragraphs.append(
            {
                "paragraph_id": paragraph_id,
                "section_id": current_section_id,
                "text": block_text,
                "char_start": block_start,
                "char_end": block_start + len(block_text),
                "sentences": _sentence_anchors(paragraph_id, block_text, claims, reference_lookup),
            }
        )

    return sections, paragraphs


def _sentence_anchors(
    paragraph_id: str, paragraph_text: str, claims: list[dict[str, Any]], reference_lookup: dict[str, list[str]]
) -> list[dict[str, Any]]:
    anchors = []
    for sentence_index, sentence_text in enumerate(split_sentences(paragraph_text), start=1):
        normalized_sentence = _normalize(sentence_text)
        matched_claim_ids = [
            claim.get("id")
            for claim in claims
            if claim.get("text") and _normalize(str(claim["text"])) in normalized_sentence
        ]
        anchors.append(
            {
                "sentence_id": f"{paragraph_id}-sent-{sentence_index:02d}",
                "text": sentence_text,
                "has_inline_citation": has_inline_citation(sentence_text),
                "citation_insertion_anchor": "end_of_sentence_before_final_punctuation",
                "claim_ids": matched_claim_ids,
                "reference_ids": reference_lookup.get(normalized_sentence, []),
            }
        )
    return anchors


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())
