"""Adversarial regression suite for AGENTS.md's "No Hallucinations" Core Rule
(TODO.md Phase 27, item 437): every existing AI feature must either refuse
(insufficient_evidence, no AI call at all) or flag (the deterministic
grounding-check catching a fabricated/uncited claim) rather than silently
accepting an ungrounded answer.

Two adversarial shapes are covered for every `engine.ai` function, including
every one of `AI_WORKSPACE_REPORTS`'s 8 report kinds:

1. "Off-corpus, zero evidence": a freshly initialized workspace with no
   accepted sources, claims, artefacts, or candidates at all -- the
   structural pre-flight guard (`_insufficient_evidence_response`) must
   refuse without ever calling the AI provider.
2. "Fabricated citation": a workspace *with* real evidence, but the mocked
   AI response cites an ID that was never actually in the safe context sent
   to it (simulating a model that invents a source) -- `validate_grounding`
   must flag it as ungrounded rather than the response being accepted at
   face value.
"""

import json
from pathlib import Path
from urllib.request import Request

import pytest

from corroborly.core.yamlio import read_yaml, write_yaml
from corroborly.engine.ai import (
    AI_WORKSPACE_REPORTS,
    OpenAiCredentials,
    ai_assisted_review,
    ai_citation_plan_review,
    ai_novelty_assessment,
    ai_research_question_assessment,
    ai_workspace_report,
)
from corroborly.engine.workspace import init_workspace


class FakeResponse:
    def __init__(self, data: object):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


def _refuse_opener(request: Request):
    raise AssertionError("AI provider must not be called when there is no evidence to ground a response in")


# --- 1. off-corpus / zero-evidence refusal, for every AI kind -----------------


def test_ai_assisted_review_refuses_on_zero_evidence_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    report = ai_assisted_review(workspace, OpenAiCredentials(api_key="sk-secret"), opener=_refuse_opener)
    assert report["insufficient_evidence"] is True
    assert report["ai_used"] is False


def test_ai_novelty_assessment_refuses_on_zero_evidence_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    report = ai_novelty_assessment(workspace, OpenAiCredentials(api_key="sk-secret"), opener=_refuse_opener)
    assert report["insufficient_evidence"] is True
    assert report["ai_used"] is False


def test_ai_research_question_assessment_refuses_on_zero_evidence_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test",
        project_type="M.Phil",
        topic="Topic",
        research_questions=[{"question": "Does anything support this?", "status": "approved"}],
    )
    report = ai_research_question_assessment(
        workspace, OpenAiCredentials(api_key="sk-secret"), opener=_refuse_opener
    )
    assert report["insufficient_evidence"] is True
    assert report["ai_used"] is False


@pytest.mark.parametrize("kind", sorted(AI_WORKSPACE_REPORTS))
def test_ai_workspace_report_refuses_on_zero_evidence_workspace(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    report = ai_workspace_report(
        workspace, OpenAiCredentials(api_key="sk-secret"), kind=kind, opener=_refuse_opener
    )
    assert report["insufficient_evidence"] is True, f"kind={kind} should refuse with zero evidence"
    assert report["ai_used"] is False
    assert report["grounding"] is None


# --- 2. fabricated-citation flagging, for every AI kind ------------------------


def _init_with_one_accepted_source(tmp_path: Path, *, topic: str, text: str, research_questions=None):
    from corroborly.engine.conversion import convert_sources
    from corroborly.engine.sources import scan_sources, set_source_status

    workspace = tmp_path / "workspace"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "paper.txt").write_text(text, encoding="utf-8")
    init_workspace(
        workspace,
        project_name="Test",
        project_type="M.Phil",
        topic=topic,
        research_questions=research_questions or [],
    )
    scan_sources(workspace, source_root)
    source_id = read_yaml(workspace / "source-register.yaml")["sources"][0]["source_id"]
    set_source_status(workspace, source_id=source_id, new_status="accepted")
    convert_sources(workspace, status="accepted")
    return workspace, source_id


def _fabricating_opener(text: str):
    def opener(request: Request):
        return FakeResponse({"id": "resp_fabricated", "output_text": text})

    return opener


def test_ai_assisted_review_flags_fabricated_source_citation(tmp_path: Path) -> None:
    workspace, real_source_id = _init_with_one_accepted_source(
        tmp_path, topic="Local review quality", text="bounded evidence text"
    )
    report = ai_assisted_review(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        max_sources=1,
        max_excerpt_chars=100,
        opener=_fabricating_opener("Confident finding [[source:src-does-not-exist]]."),
    )
    assert report["ai_used"] is True
    assert report["grounding"]["fully_grounded"] is False
    assert report["grounding"]["ungrounded_citations"] == [{"type": "source", "id": "src-does-not-exist"}]
    assert real_source_id not in {c["id"] for c in report["grounding"]["ungrounded_citations"]}


def test_ai_novelty_assessment_flags_fabricated_source_citation(tmp_path: Path) -> None:
    workspace, _source_id = _init_with_one_accepted_source(
        tmp_path,
        topic="Local review quality",
        text="bounded novelty context",
        research_questions=[{"question": "Does local tracking help?", "status": "approved"}],
    )
    report = ai_novelty_assessment(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        max_sources=1,
        max_excerpt_chars=100,
        opener=_fabricating_opener("Novel overlap found [[source:src-invented]]."),
    )
    assert report["ai_used"] is True
    assert report["grounding"]["fully_grounded"] is False
    assert report["grounding"]["ungrounded_citations"] == [{"type": "source", "id": "src-invented"}]


def test_ai_research_question_assessment_flags_fabricated_source_citation(tmp_path: Path) -> None:
    workspace, _source_id = _init_with_one_accepted_source(
        tmp_path,
        topic="Local review quality",
        text="bounded RQ context",
        research_questions=[{"question": "Does local tracking help?", "status": "approved"}],
    )
    report = ai_research_question_assessment(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        max_sources=1,
        max_excerpt_chars=100,
        opener=_fabricating_opener("Strong fit claimed [[source:src-fake]]."),
    )
    assert report["ai_used"] is True
    assert report["grounding"]["fully_grounded"] is False
    assert report["grounding"]["ungrounded_citations"] == [{"type": "source", "id": "src-fake"}]


@pytest.mark.parametrize("kind", sorted(AI_WORKSPACE_REPORTS))
def test_ai_workspace_report_flags_fabricated_citation_for_every_kind(tmp_path: Path, kind: str) -> None:
    workspace, _source_id = _init_with_one_accepted_source(
        tmp_path, topic="Local review quality", text="bounded report context"
    )
    report = ai_workspace_report(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        kind=kind,
        max_sources=1,
        max_excerpt_chars=100,
        opener=_fabricating_opener("Claimed finding [[claim:claim-invented]]."),
    )
    assert report["ai_used"] is True, f"kind={kind} unexpectedly refused despite real evidence being present"
    assert report["grounding"]["fully_grounded"] is False
    assert report["grounding"]["ungrounded_citations"] == [{"type": "claim", "id": "claim-invented"}]


def test_ai_citation_plan_review_flags_fabricated_source_citation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    report = ai_citation_plan_review(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        target_text="Claim needing a citation.",
        citation_plan={"insertions": [{"source_id": "source-001"}]},
        opener=_fabricating_opener("Insert this instead [[source:source-999]]."),
    )
    assert report["ai_used"] is True
    assert report["grounding"]["fully_grounded"] is False
    assert report["grounding"]["ungrounded_citations"] == [{"type": "source", "id": "source-999"}]


# --- 3. uncited-paragraph coverage signal --------------------------------------


def test_ai_assisted_review_flags_response_with_no_citations_at_all(tmp_path: Path) -> None:
    workspace, _source_id = _init_with_one_accepted_source(
        tmp_path, topic="Local review quality", text="bounded evidence text"
    )
    report = ai_assisted_review(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        max_sources=1,
        max_excerpt_chars=100,
        opener=_fabricating_opener("This is a confident assertion with no citation marker whatsoever."),
    )
    # No ungrounded *markers* were found (there are none), but the coverage
    # signal must still flag the whole response as unverifiable prose.
    assert report["grounding"]["fully_grounded"] is True
    assert report["grounding"]["citations_found"] == 0
    assert report["grounding"]["uncited_paragraph_count"] == 1
