from pathlib import Path

import pytest

from corroborly.core.yamlio import read_yaml
from corroborly.engine.research_stages import (
    list_stages,
    set_stage_status,
    set_stage_target_date,
    stages_ics,
    write_stages_ics,
)
from corroborly.engine.workspace import init_workspace


def test_list_stages_returns_mphil_template(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    stages = list_stages(workspace)

    assert len(stages) > 0
    assert all(stage["status"] == "not_started" for stage in stages)
    assert all("target_date" not in stage for stage in stages)


def test_set_stage_status_updates_and_persists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]

    updated = set_stage_status(workspace, stage_id, "in_progress")

    assert updated["status"] == "in_progress"
    assert list_stages(workspace)[0]["status"] == "in_progress"


def test_set_stage_status_rejects_unknown_status(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]

    with pytest.raises(ValueError, match="Invalid stage status"):
        set_stage_status(workspace, stage_id, "almost_done")


def test_set_stage_status_rejects_unknown_stage_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    with pytest.raises(ValueError, match="Unknown stage_id"):
        set_stage_status(workspace, "stage-99", "done")


def test_set_stage_target_date_sets_and_clears(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]

    updated = set_stage_target_date(workspace, stage_id, "2026-09-30")
    assert updated["target_date"] == "2026-09-30"
    assert list_stages(workspace)[0]["target_date"] == "2026-09-30"

    cleared = set_stage_target_date(workspace, stage_id, None)
    assert "target_date" not in cleared
    assert "target_date" not in list_stages(workspace)[0]


def test_set_stage_target_date_rejects_invalid_date(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]

    with pytest.raises(ValueError, match="Invalid target_date"):
        set_stage_target_date(workspace, stage_id, "30 September 2026")


def test_stages_ics_includes_only_stages_with_target_dates(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stages = list_stages(workspace)
    set_stage_target_date(workspace, stages[0]["id"], "2026-09-30")

    ics = stages_ics(workspace)

    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20260930" in ics
    assert f"SUMMARY:{stages[0]['name']}" in ics


def test_stages_ics_escapes_special_characters(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]
    set_stage_target_date(workspace, stage_id, "2026-09-30")
    doc = read_yaml(workspace / "research-stages.yaml")
    doc["stages"][0]["name"] = "Submit, Review; Revise\\Finalize"
    from corroborly.core.yamlio import write_yaml

    write_yaml(workspace / "research-stages.yaml", doc)

    ics = stages_ics(workspace)

    assert "Submit\\, Review\\; Revise\\\\Finalize" in ics


def test_write_stages_ics_writes_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")
    stage_id = list_stages(workspace)[0]["id"]
    set_stage_target_date(workspace, stage_id, "2026-09-30")

    output_path = write_stages_ics(workspace)

    assert output_path.name == "research-stages.ics"
    assert output_path.is_file()
    assert "BEGIN:VEVENT" in output_path.read_text(encoding="utf-8")


def test_stages_ics_empty_when_no_target_dates(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="")

    ics = stages_ics(workspace)

    assert "BEGIN:VEVENT" not in ics
    assert "BEGIN:VCALENDAR" in ics
