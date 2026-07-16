from ledgerly.engine.grounding import (
    AI_PROVENANCE_END,
    AI_PROVENANCE_START,
    citable_ids,
    citation_instruction,
    extract_citations,
    strip_ai_provenance_markers,
    uncited_paragraphs,
    validate_grounding,
    wrap_ai_generated_text,
)


def _context(*source_ids: str) -> dict:
    return {
        "sources": [{"metadata": {"source_id": source_id}} for source_id in source_ids],
    }


def test_citation_instruction_names_all_four_marker_types():
    instruction = citation_instruction()
    for marker in ("[[source:", "[[claim:", "[[artefact:", "[[note:"):
        assert marker in instruction


def test_extract_citations_finds_every_marker_in_order():
    text = "First fact [[source:src-001]]. Second fact [[claim:claim-002]]. Repeat [[source:src-001]]."
    citations = extract_citations(text)
    assert citations == [
        {"type": "source", "id": "src-001"},
        {"type": "claim", "id": "claim-002"},
        {"type": "source", "id": "src-001"},
    ]


def test_extract_citations_ignores_malformed_markers():
    text = "Not a marker [source:src-001] or [[source-src-001]] or [[unknown:src-001]]."
    assert extract_citations(text) == []


def test_citable_ids_from_context_claims_artefacts_notes_and_explicit_source_ids():
    ids = citable_ids(
        _context("src-001", "src-002"),
        claims=[{"id": "claim-001"}, {"not_a_dict": True}],
        artefacts=[{"id": "artefact-001"}],
        notes=[{"id": "note-001"}],
        source_ids=["src-003"],
    )
    assert ids["source"] == {"src-001", "src-002", "src-003"}
    assert ids["claim"] == {"claim-001"}
    assert ids["artefact"] == {"artefact-001"}
    assert ids["note"] == {"note-001"}


def test_validate_grounding_all_citations_grounded():
    text = "The finding holds [[source:src-001]] and is echoed [[claim:claim-001]]."
    report = validate_grounding(text, context=_context("src-001"), claims=[{"id": "claim-001"}])
    assert report["fully_grounded"] is True
    assert report["citations_found"] == 2
    assert report["ungrounded_citations"] == []
    assert {c["id"] for c in report["grounded_citations"]} == {"src-001", "claim-001"}


def test_validate_grounding_flags_hallucinated_id_as_ungrounded():
    text = "A fabricated fact [[source:src-999]]."
    report = validate_grounding(text, context=_context("src-001"))
    assert report["fully_grounded"] is False
    assert report["ungrounded_citations"] == [{"type": "source", "id": "src-999"}]


def test_validate_grounding_deduplicates_repeated_citations():
    text = "Stated twice [[source:src-001]]. Repeated again [[source:src-001]]."
    report = validate_grounding(text, context=_context("src-001"))
    assert report["citations_found"] == 1
    assert len(report["grounded_citations"]) == 1


def test_validate_grounding_source_ids_kwarg_used_without_context():
    text = "Direct fact [[source:src-plan-1]]."
    report = validate_grounding(text, source_ids=["src-plan-1"])
    assert report["fully_grounded"] is True


def test_uncited_paragraphs_flags_blocks_with_no_marker():
    text = (
        "## Scope\n\n"
        "This is cited [[source:src-001]].\n\n"
        "This paragraph has no citation marker at all and should be flagged."
    )
    flagged = uncited_paragraphs(text)
    assert len(flagged) == 1
    assert "no citation marker" in flagged[0]


def test_uncited_paragraphs_excludes_headings():
    text = "## Human Review Required\n\nThis fact is cited [[source:src-001]]."
    assert uncited_paragraphs(text) == []


def test_validate_grounding_reports_uncited_paragraph_count():
    text = "Uncited claim with no marker at all."
    report = validate_grounding(text, context=_context("src-001"))
    assert report["citations_found"] == 0
    assert report["uncited_paragraph_count"] == 1
    assert report["fully_grounded"] is True  # no ungrounded *citations*, just no citations at all


def test_wrap_ai_generated_text_is_reversible_and_labelled():
    wrapped = wrap_ai_generated_text("Line one\nLine two", kind="paper_draft", response_id="resp-123")
    assert wrapped.startswith(AI_PROVENANCE_START)
    assert wrapped.endswith(AI_PROVENANCE_END)
    assert "AI-generated (paper_draft)" in wrapped
    assert "resp-123" in wrapped
    assert "> Line one" in wrapped
    assert "> Line two" in wrapped
    stripped = strip_ai_provenance_markers(wrapped)
    assert AI_PROVENANCE_START not in stripped
    assert AI_PROVENANCE_END not in stripped
    assert "Line one" in stripped


def test_wrap_ai_generated_text_without_response_id():
    wrapped = wrap_ai_generated_text("Body text", kind="review")
    assert "Response ID" not in wrapped
