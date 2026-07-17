"""Deterministic grounding-check mechanism (AGENTS.md Core Rule; TODO.md Phase 27).

Every `engine.ai` function that produces free-text output is instructed
(`citation_instruction`) to mark each factual assertion with an inline
citation of the form ``[[source:<id>]]``, ``[[claim:<id>]]``,
``[[artefact:<id>]]``, or ``[[note:<id>]]``, using only IDs that were
actually present in the safe context sent to the model. `validate_grounding`
is the deterministic (non-AI) auditor: it extracts every citation marker
from a response, checks each one against the IDs that were genuinely
available, and flags any paragraph with no citation at all -- so a claim is
auditable against real workspace state, not just self-asserted by the model.
This never calls an AI provider itself; it is pure text/dict processing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

CITATION_TYPES = ("source", "claim", "artefact", "note")

CITATION_PATTERN = re.compile(r"\[\[(source|claim|artefact|note):([A-Za-z0-9_-]+)\]\]")

AI_PROVENANCE_START = "<!-- ledgerly:ai-generated:start -->"
AI_PROVENANCE_END = "<!-- ledgerly:ai-generated:end -->"


def citation_instruction() -> str:
    """Prompt fragment every grounded AI prompt appends verbatim, so model
    output uses one deterministically parseable citation marker per factual
    assertion instead of freeform prose citations that can't be machine
    checked.
    """
    return (
        "Citation format (required): whenever you state a fact drawn from the supplied "
        "context, immediately follow it with a citation marker in the exact form "
        "[[source:<source_id>]], [[claim:<claim_id>]], [[artefact:<artefact_id>]], or "
        "[[note:<note_id>]], using only IDs that appear in the supplied context. Never "
        "invent an ID. Any statement with no citation marker will be treated as unsupported "
        "by an automated check."
    )


def extract_citations(text: str) -> list[dict[str, str]]:
    """Every citation marker found in `text`, in order, including duplicates."""
    return [{"type": match.group(1), "id": match.group(2)} for match in CITATION_PATTERN.finditer(text or "")]


def citable_ids(
    context: dict[str, Any] | None = None,
    *,
    claims: list[dict[str, Any]] | None = None,
    artefacts: list[dict[str, Any]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    source_ids: Iterable[str] | None = None,
) -> dict[str, set[str]]:
    """The set of real, citable IDs per type that were actually available to
    the model for a given request -- the ground truth `validate_grounding`
    checks citation markers against. `context` is a `build_safe_context`
    envelope (its `sources` list); `source_ids` covers callers (e.g. citation
    plan review) that pass source IDs directly instead of a safe context.
    """
    ids: dict[str, set[str]] = {citation_type: set() for citation_type in CITATION_TYPES}
    if context:
        for entry in context.get("sources", []) or []:
            metadata = entry.get("metadata") if isinstance(entry, dict) else None
            source_id = metadata.get("source_id") if isinstance(metadata, dict) else None
            if source_id:
                ids["source"].add(str(source_id))
    for source_id in source_ids or []:
        if source_id:
            ids["source"].add(str(source_id))
    for claim in claims or []:
        if isinstance(claim, dict) and claim.get("id"):
            ids["claim"].add(str(claim["id"]))
    for artefact in artefacts or []:
        if isinstance(artefact, dict) and artefact.get("id"):
            ids["artefact"].add(str(artefact["id"]))
    for note in notes or []:
        if isinstance(note, dict) and note.get("id"):
            ids["note"].add(str(note["id"]))
    return ids


def uncited_paragraphs(text: str) -> list[str]:
    """Blank-line-separated blocks of `text` containing no citation marker at
    all, excluding markdown headings -- a coverage signal, not a hard
    correctness check: a paragraph can legitimately be scope-setting prose
    rather than a factual assertion. Kept simple and heuristic on purpose;
    `validate_grounding`'s `fully_grounded`/`ungrounded_citations` fields are
    the hard check.
    """
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
    flagged = []
    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0]
        if first_line.lstrip().startswith("#"):
            continue
        if CITATION_PATTERN.search(paragraph):
            continue
        flagged.append(paragraph)
    return flagged


def validate_grounding(
    text: str,
    *,
    context: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
    artefacts: list[dict[str, Any]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    source_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The deterministic grounding-check report for one AI response `text`.

    `fully_grounded` is False whenever any citation marker references an ID
    that was not actually available to the model -- the concrete, auditable
    signal for AGENTS.md Core Rule item 2 ("the AI must never fabricate").
    `uncited_paragraph_count` is a softer coverage signal: content with no
    citation marker at all is not necessarily wrong, but it is unverifiable
    against real workspace state and should be flagged for human review.
    """
    available = citable_ids(context, claims=claims, artefacts=artefacts, notes=notes, source_ids=source_ids)
    grounded: list[dict[str, str]] = []
    ungrounded: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for citation in extract_citations(text):
        key = (citation["type"], citation["id"])
        if key in seen:
            continue
        seen.add(key)
        if citation["id"] in available.get(citation["type"], set()):
            grounded.append(citation)
        else:
            ungrounded.append(citation)
    flagged_paragraphs = uncited_paragraphs(text)
    return {
        "version": 1,
        "citations_found": len(seen),
        "grounded_citations": grounded,
        "ungrounded_citations": ungrounded,
        "fully_grounded": not ungrounded,
        "uncited_paragraph_count": len(flagged_paragraphs),
        "uncited_paragraphs": flagged_paragraphs,
    }


def wrap_ai_generated_text(text: str, *, kind: str, response_id: str | None = None) -> str:
    """Wrap AI-produced markdown so it stays visually and structurally
    distinguishable from user-authored text and verbatim source quotes
    wherever it is later inserted into a shared document (AGENTS.md Core
    Rule item 4). No feature writes AI text into a mixed user/AI document
    yet -- Phase 8's AI edit sessions, Phase 28's `paper draft --ai`, and
    Phase 31's diff view are all still pending -- this is the shared
    primitive they should reuse rather than each inventing their own marker
    convention.
    """
    header = f"> **AI-generated ({kind})** -- requires human review before use."
    if response_id:
        header += f" Response ID: `{response_id}`."
    body = "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
    return f"{AI_PROVENANCE_START}\n{header}\n>\n{body}\n{AI_PROVENANCE_END}"


def strip_ai_provenance_markers(text: str) -> str:
    """Inverse of `wrap_ai_generated_text`'s HTML-comment boundary markers,
    for callers that need the raw wrapped content back without them (e.g.
    re-running `validate_grounding` on already-stored text).
    """
    return text.replace(f"{AI_PROVENANCE_START}\n", "").replace(f"\n{AI_PROVENANCE_END}", "").replace(
        AI_PROVENANCE_END, ""
    )


AI_EDIT_SPAN_START = "[[AI-EDIT-START]]"
AI_EDIT_SPAN_END = "[[AI-EDIT-END]]"


def wrap_ai_edit_span(text: str) -> str:
    """The inline sibling of `wrap_ai_generated_text`: a plain-text marker
    for AI-proposed text spliced *inside* otherwise human-authored flowing
    prose (e.g. `engine.ai_edit_sessions.apply_ai_edit_session` replacing one
    sentence within a paragraph), where a multi-line blockquote block would
    break the surrounding paragraph's structure. Visible directly in the raw
    file in any plain-text viewer -- not just a UI-only affordance -- per
    AGENTS.md Core Rule item 4.
    """
    return f"{AI_EDIT_SPAN_START}{text}{AI_EDIT_SPAN_END}"


def strip_ai_edit_span_markers(text: str) -> str:
    """Inverse of `wrap_ai_edit_span`, for callers that need the plain
    replacement text back (e.g. diffing or re-validating grounding)."""
    return text.replace(AI_EDIT_SPAN_START, "").replace(AI_EDIT_SPAN_END, "")
