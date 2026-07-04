from pathlib import Path

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.citations import apply_citation_plan, create_citation_plan
from researchboss.engine.workspace import init_workspace


def test_create_citation_plan_writes_reviewable_plan_without_editing_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    target = workspace / "artefacts" / "papers" / "draft.md"
    original_text = "Container terminal automation uses berth planning evidence."
    target.write_text(original_text, encoding="utf-8")
    source_text = workspace / "sources_text" / "source-001.txt"
    source_text.write_text("Berth planning evidence supports container terminal automation.", encoding="utf-8")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "source-001",
                    "status": "accepted",
                    "provider": "local_folder",
                    "file_name": "paper.pdf",
                    "conversion": {"status": "converted", "output_path": str(source_text)},
                    "citation_metadata": {
                        "title": "Accepted Source",
                        "authors": ["Smith, A."],
                        "year": 2024,
                    },
                }
            ],
        },
    )

    result = create_citation_plan(workspace, str(target))

    assert result.yaml_path.is_file()
    assert result.markdown_path.is_file()
    assert target.read_text(encoding="utf-8") == original_text
    plan = read_yaml(result.yaml_path)
    assert plan["original_document_modified"] is False
    assert plan["insertions"][0]["source_id"] == "source-001"
    assert plan["insertions"][0]["suggested_inline_citation"] == "(Smith, 2024)"
    assert plan["insertions"][0]["review_status"] == "needs_human_review"


def test_apply_citation_plan_creates_revised_copy_for_accepted_insertions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    target = workspace / "artefacts" / "papers" / "draft.md"
    original_text = "Container terminal automation uses berth planning evidence."
    target.write_text(original_text, encoding="utf-8")
    source_text = workspace / "sources_text" / "source-001.txt"
    source_text.write_text("Berth planning evidence supports container terminal automation.", encoding="utf-8")
    write_yaml(
        workspace / "source-register.yaml",
        {
            "version": 1,
            "sources": [
                {
                    "source_id": "source-001",
                    "status": "accepted",
                    "provider": "local_folder",
                    "file_name": "paper.pdf",
                    "conversion": {"status": "converted", "output_path": str(source_text)},
                    "citation_metadata": {
                        "title": "Accepted Source",
                        "authors": ["Smith, A."],
                        "year": 2024,
                    },
                }
            ],
        },
    )
    plan = create_citation_plan(workspace, str(target))
    plan_data = read_yaml(plan.yaml_path)
    plan_data["insertions"][0]["review_status"] = "accepted"
    write_yaml(plan.yaml_path, plan_data)

    result = apply_citation_plan(workspace, str(target))

    revised = result.output_path.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == original_text
    assert "evidence (Smith, 2024)." in revised
    assert "## References" in revised
    assert result.applied == 1
    assert read_yaml(result.report_path)["original_document_modified"] is False
