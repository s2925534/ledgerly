import json
from pathlib import Path
from urllib.request import Request

import pytest

from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.ai import OpenAiCredentials
from ledgerly.engine.ai_edit_sessions import apply_ai_edit_session, set_ai_edit_review_status
from ledgerly.engine.artefact_creation import create_ai_paper_draft, create_deterministic_artefact
from ledgerly.engine.artefacts import (
    artefact_dependency_report,
    clear_paper_review_gate,
    list_artefacts,
    promote_ai_paper_draft,
    register_artefact,
    set_artefact_review_status,
)
from ledgerly.engine.claims import add_claim
from ledgerly.engine.doc_validation import validate_document
from ledgerly.engine.vault import list_document_versions
from ledgerly.engine.workspace import init_workspace


class FakeResponse:
    def __init__(self, data: object):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.data


def _paper_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {"question": "Does automation improve throughput?", "status": "draft", "subquestions": []}
        ],
    )
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "source-001",
                    "status": "accepted",
                    "file_name": "automation.pdf",
                    "file_ext": "pdf",
                    "citation_metadata": {"title": "Automation Study", "authors": ["A. Smith"], "year": 2020},
                }
            ],
        },
    )
    add_claim(
        workspace,
        text="Automated handling reduced dwell time by 20%.",
        linked_sources=["source-001"],
        linked_research_questions=["rq-001"],
    )
    return workspace


def test_register_artefact_records_links_and_review_flags(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    artefact_path = workspace / "artefacts" / "reports" / "summary.md"
    artefact_path.write_text("# Summary", encoding="utf-8")

    record = register_artefact(
        workspace,
        title="Summary",
        artefact_type="report",
        path=artefact_path,
        linked_sources=["source-001"],
        linked_research_questions=["rq-001"],
        requires_user_review=True,
    )

    assert record["id"] == "artefact-001"
    assert record["linked_sources"] == ["source-001"]
    assert record["linked_research_questions"] == ["rq-001"]
    assert record["ai_generated"] is False
    assert record["requires_user_review"] is True
    assert record["review_status"] == "pending_review"
    assert list_artefacts(workspace) == [record]


def test_create_source_summary_uses_accepted_sources_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "accepted-001",
                    "status": "accepted",
                    "file_name": "accepted.pdf",
                    "file_ext": "pdf",
                    "citation_metadata": {"title": "Accepted Paper", "authors": ["A. Author"], "year": 2024},
                },
                {"source_id": "ignored-001", "status": "ignored", "file_name": "ignored.pdf", "file_ext": "pdf"},
                {"source_id": "maybe-001", "status": "maybe", "file_name": "maybe.pdf", "file_ext": "pdf"},
            ],
        },
    )

    result = create_deterministic_artefact(workspace, "source-summary-report")

    content = result.path.read_text(encoding="utf-8")
    assert "Accepted Paper" in content
    assert "ignored-001" not in content
    assert "maybe-001" not in content
    assert "No interpretation performed." in content
    assert "User review required." in content
    assert result.record["ai_generated"] is False
    assert result.record["requires_user_review"] is True
    assert result.record["linked_sources"] == ["accepted-001"]


def test_create_source_summary_can_include_maybe_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {"source_id": "accepted-001", "status": "accepted", "file_name": "accepted.pdf", "file_ext": "pdf"},
                {"source_id": "maybe-001", "status": "maybe", "file_name": "maybe.pdf", "file_ext": "pdf"},
            ],
        },
    )

    result = create_deterministic_artefact(workspace, "source-summary-report", include_maybe=True)

    content = result.path.read_text(encoding="utf-8")
    assert "accepted-001" in content
    assert "maybe-001" in content
    assert result.record["linked_sources"] == ["accepted-001", "maybe-001"]


def test_create_claim_evidence_table_does_not_infer_support(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    add_claim(workspace, text="Supported claim", linked_sources=["source-001"], linked_research_questions=["rq-001"])
    add_claim(workspace, text="Unsupported claim")

    result = create_deterministic_artefact(workspace, "claim-evidence-table")

    content = result.path.read_text(encoding="utf-8")
    assert "Supported claim" in content
    assert "Linked evidence" in content
    assert "Unsupported claim" in content
    assert "No linked evidence" in content
    assert result.record["linked_sources"] == ["source-001"]
    assert result.record["linked_research_questions"] == ["rq-001"]


def test_create_research_question_brief_links_questions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {"question": "How does X work?", "status": "approved", "subquestions": ["What is X?"]},
            {"question": "Should Y be studied?", "status": "draft", "subquestions": []},
        ],
    )

    result = create_deterministic_artefact(workspace, "research-question-brief")

    content = result.path.read_text(encoding="utf-8")
    assert "How does X work?" in content
    assert "Should Y be studied?" in content
    assert result.record["linked_research_questions"] == ["rq-001", "rq-002"]


def test_create_data_profile_summary_uses_profile_metadata_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    write_yaml(
        workspace / "outputs" / "data-profiles" / "source-001.yaml",
        {
            "version": 1,
            "source_id": "source-001",
            "profile": {"type": "csv", "row_count": 2, "column_count": 3},
        },
    )

    result = create_deterministic_artefact(workspace, "data-profile-summary")

    content = result.path.read_text(encoding="utf-8")
    assert "Full datasets are not copied into this artefact." in content
    assert "| source-001 | csv | 2 | 3 |" in content
    assert result.record["linked_sources"] == ["source-001"]


def test_create_paper_draft_assembles_deterministic_skeleton_from_real_data(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {
                "question": "To what extent does automation reduce turnaround time in Asian ports?",
                "status": "draft",
                "subquestions": [],
            }
        ],
    )
    # Wizard-style fields aren't part of init_workspace's shape; add them directly to the candidate.
    candidates_path = workspace / "research-question-candidates.yaml"
    candidates_doc = read_yaml(candidates_path)
    candidates_doc["candidates"][0].update(
        {
            "hypothesis": "Automation improves outcomes.",
            "question_type": "causal",
            "proof_criteria": "Statistically lower turnaround times.",
            "disproof_criteria": "No significant difference.",
        }
    )
    write_yaml(candidates_path, candidates_doc)
    add_claim(
        workspace,
        text="Automated terminals show 20% lower turnaround time in pilot studies.",
        linked_research_questions=["rq-001"],
    )
    add_claim(workspace, text="An unrelated claim about a different research question.")

    result = create_deterministic_artefact(workspace, "paper-draft", rq_id="rq-001")

    content = result.path.read_text(encoding="utf-8")
    assert result.path.name == "paper-draft-rq-001.md"
    assert "Hypothesis: Automation improves outcomes." in content
    assert "Question type: causal" in content
    assert "Statistically lower turnaround times." in content
    assert "20% lower turnaround time in pilot studies." in content
    assert "An unrelated claim about a different research question." not in content  # not linked to rq-001
    assert "Status: DRAFT — no conclusion has been written." in content
    assert result.record["linked_research_questions"] == ["rq-001"]
    assert result.record["requires_user_review"] is True


def test_create_paper_draft_requires_rq_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="PhD", topic="")

    with pytest.raises(ValueError, match="requires rq_id"):
        create_deterministic_artefact(workspace, "paper-draft")


def test_create_paper_draft_rejects_unknown_rq_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="PhD", topic="")

    with pytest.raises(ValueError, match="Unknown research question"):
        create_deterministic_artefact(workspace, "paper-draft", rq_id="rq-999")


def test_create_paper_draft_handles_no_sources_or_claims(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="M.Phil",
        topic="",
        research_questions=[{"question": "A bare question?", "status": "draft", "subquestions": []}],
    )

    result = create_deterministic_artefact(workspace, "paper-draft", rq_id="rq-001")

    content = result.path.read_text(encoding="utf-8")
    assert "No accepted sources yet" in content
    assert "No claims linked to this research question yet" in content


def test_create_artefact_requires_overwrite_for_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    create_deterministic_artefact(workspace, "source-summary-report")

    with pytest.raises(ValueError, match="already exists"):
        create_deterministic_artefact(workspace, "source-summary-report")

    result = create_deterministic_artefact(workspace, "source-summary-report", overwrite=True)
    assert result.path.is_file()


def test_artefact_review_status_and_dependency_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="M.Phil",
        topic="",
        research_questions=[{"question": "Approved?", "status": "approved", "subquestions": []}],
    )
    write_yaml(
        workspace / "source-register.yaml",
        {"version": 1, "sources": [{"source_id": "source-001", "status": "maybe"}]},
    )
    record = register_artefact(
        workspace,
        title="Report",
        artefact_type="report",
        path=workspace / "artefacts" / "reports" / "report.md",
        linked_sources=["source-001"],
        linked_research_questions=["rq-001"],
    )

    set_artefact_review_status(workspace, record["id"], "needs_revision")
    report = artefact_dependency_report(workspace)

    assert list_artefacts(workspace)[0]["review_status"] == "needs_revision"
    assert report["artefacts"][0]["status"] == "needs_review"
    assert report["artefacts"][0]["issues"][0]["kind"] == "source_not_accepted"


def test_create_deterministic_artefact_auto_versions_on_creation_and_regeneration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")

    result = create_deterministic_artefact(workspace, "source-summary-report")
    versions = list_document_versions(workspace, target=str(result.path))
    assert len(versions) == 1
    assert versions[0]["creation_reason"] == "artefact_created"

    create_deterministic_artefact(workspace, "source-summary-report", overwrite=True)
    versions = list_document_versions(workspace, target=str(result.path))
    assert len(versions) == 2
    assert versions[1]["creation_reason"] == "artefact_regenerated"
    assert versions[1]["parent_version_id"] == versions[0]["version_id"]


def test_create_ai_paper_draft_ensures_skeleton_exists_first(tmp_path: Path) -> None:
    workspace = _paper_workspace(tmp_path)
    skeleton = workspace / "artefacts" / "papers" / "paper-draft-rq-001.md"
    assert not skeleton.is_file()

    def opener(_req: Request):
        return FakeResponse({"id": "resp-1", "output": [{"content": [{"type": "output_text", "text": ""}]}]})

    create_ai_paper_draft(workspace, OpenAiCredentials(api_key="sk-fake"), "rq-001", opener=opener)
    assert skeleton.is_file()
    assert len(list_artefacts(workspace)) == 1


def test_create_ai_paper_draft_rejects_unknown_rq(tmp_path: Path) -> None:
    workspace = _paper_workspace(tmp_path)

    with pytest.raises(ValueError, match="Unknown research question"):
        create_ai_paper_draft(workspace, OpenAiCredentials(api_key="sk-fake"), "rq-999")


def test_ai_paper_draft_full_review_gate_lifecycle(tmp_path: Path) -> None:
    workspace = _paper_workspace(tmp_path)

    # First, create the deterministic skeleton to learn the real placeholder anchor.
    skeleton = create_deterministic_artefact(workspace, "paper-draft", rq_id="rq-001")
    from ledgerly.engine.derived_text import build_derived_text_snapshot
    from ledgerly.engine.vault import create_document_version

    version = create_document_version(workspace, str(skeleton.path), creation_reason="test_setup")
    derived = build_derived_text_snapshot(workspace, version["version_id"])
    target_sentence = None
    for paragraph in derived["paragraphs"]:
        for sentence in paragraph["sentences"]:
            if "DRAFT" in sentence["text"]:
                target_sentence = {"paragraph_id": paragraph["paragraph_id"], **sentence}
                break
        if target_sentence:
            break
    assert target_sentence is not None

    edit_block = (
        f"### EDIT paragraph_id={target_sentence['paragraph_id']} sentence_id={target_sentence['sentence_id']}\n"
        f"ORIGINAL: {target_sentence['text']}\n"
        "PROPOSED: The evidence supports the hypothesis. [[claim:claim-001]]\n"
        "RATIONALE: Grounded in the available claim.\n"
        "### END EDIT\n"
    )

    def opener(_req: Request):
        return FakeResponse({"id": "resp-1", "output": [{"content": [{"type": "output_text", "text": edit_block}]}]})

    session = create_ai_paper_draft(workspace, OpenAiCredentials(api_key="sk-fake"), "rq-001", opener=opener)
    assert session["edit_count"] == 1
    assert session["edits"][0]["anchor_verified"] is True

    set_ai_edit_review_status(workspace, session["session_id"], session["edits"][0]["edit_id"], "accepted")
    applied = apply_ai_edit_session(workspace, session["session_id"])

    artefact_id = next(
        a["id"] for a in list_artefacts(workspace)
        if a.get("type") == "paper-draft" and "rq-001" in (a.get("linked_research_questions") or [])
    )

    promoted = promote_ai_paper_draft(workspace, artefact_id, Path(applied["output_path"]))
    assert promoted["ai_generated"] is True
    assert promoted["paper_review_gate"] == "requires_validate"
    assert promoted["review_status"] == "pending_review"

    # The original target path's own version history must show the promotion, restorable independently
    # of the .ai-edited.md side file (TODO.md: "all is tracked for any documents produced").
    original_versions = list_document_versions(workspace, target=str(skeleton.path))
    assert [v["creation_reason"] for v in original_versions[-2:]] == [
        "pre_ai_paper_draft_promotion_snapshot",
        "ai_paper_draft_promoted",
    ]
    assert original_versions[-1]["parent_version_id"] == original_versions[-2]["version_id"]

    with pytest.raises(ValueError, match="cannot be marked reviewed/accepted"):
        set_artefact_review_status(workspace, artefact_id, "reviewed")

    with pytest.raises(ValueError, match="Run `ledgerly validate`"):
        clear_paper_review_gate(workspace, artefact_id)

    validate_document(workspace, str(skeleton.path))
    cleared = clear_paper_review_gate(workspace, artefact_id)
    assert cleared["paper_review_gate"] == "cleared"
    assert cleared["review_status"] == "reviewed"
    assert cleared["requires_user_review"] is False

    # Once cleared, no further open gate remains to clear.
    with pytest.raises(ValueError, match="no open review gate"):
        clear_paper_review_gate(workspace, artefact_id)


def test_promote_ai_paper_draft_rejects_missing_applied_file(tmp_path: Path) -> None:
    workspace = _paper_workspace(tmp_path)
    result = create_deterministic_artefact(workspace, "paper-draft", rq_id="rq-001")
    artefact_id = list_artefacts(workspace)[0]["id"]

    with pytest.raises(ValueError, match="does not exist"):
        promote_ai_paper_draft(workspace, artefact_id, result.path.with_suffix(".missing.md"))
