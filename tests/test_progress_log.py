from pathlib import Path

from corroborly.engine.artefacts import register_artefact, set_artefact_review_status
from corroborly.engine.progress_log import list_progress_events, research_progress_report
from corroborly.engine.research_questions import approve_research_question, reject_research_question
from corroborly.engine.workspace import init_workspace


def test_research_question_and_artefact_lifecycle_recorded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
        research_questions=[
            {"question": "Draft question A?", "status": "draft", "subquestions": []},
            {"question": "Draft question B?", "status": "draft", "subquestions": []},
        ],
    )

    approve_research_question(workspace, "rq-001")
    reject_research_question(workspace, "rq-002", reason="Too broad")
    artefact = register_artefact(
        workspace, title="Literature review", artefact_type="literature-review-matrix", path=Path("artefacts/reports/lit.md")
    )
    set_artefact_review_status(workspace, artefact["id"], "accepted")

    events = list_progress_events(workspace)
    kinds = [event["kind"] for event in events]

    assert kinds == ["rq_approved", "rq_rejected", "artefact_registered", "artefact_review_status_changed"]
    assert events[0]["entity_id"] == "rq-001"
    assert events[1]["entity_id"] == "rq-002"
    assert events[1]["detail"] == "Too broad"
    assert events[2]["entity_id"] == artefact["id"]
    assert events[2]["detail"] == "Literature review"
    assert events[3]["detail"] == "accepted"
    assert all(event["at"] for event in events)

    report = research_progress_report(workspace)
    assert report["event_count"] == 4
    assert (workspace / "outputs" / "reports" / "research-progress.yaml").is_file()


def test_no_events_before_any_activity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")

    assert list_progress_events(workspace) == []
    report = research_progress_report(workspace)
    assert report["event_count"] == 0
