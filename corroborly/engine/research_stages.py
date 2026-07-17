from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from corroborly.core.constants import WORKSPACE_FILES
from corroborly.core.yamlio import read_yaml, write_yaml

STAGE_STATUSES = {"not_started", "in_progress", "blocked", "done"}


def list_stages(workspace: Path) -> list[dict[str, Any]]:
    doc = read_yaml(workspace / WORKSPACE_FILES.research_stages)
    return [stage for stage in doc.get("stages", []) if isinstance(stage, dict)]


def _stages_path(workspace: Path) -> Path:
    return workspace / WORKSPACE_FILES.research_stages


def _find_stage(stages: list[dict[str, Any]], stage_id: str) -> dict[str, Any]:
    for stage in stages:
        if stage.get("id") == stage_id:
            return stage
    raise ValueError(f"Unknown stage_id: {stage_id}")


def set_stage_status(workspace: Path, stage_id: str, status: str) -> dict[str, Any]:
    if status not in STAGE_STATUSES:
        allowed = ", ".join(sorted(STAGE_STATUSES))
        raise ValueError(f"Invalid stage status: {status!r}. Expected one of: {allowed}")
    path = _stages_path(workspace)
    doc = read_yaml(path)
    stages = [stage for stage in doc.get("stages", []) if isinstance(stage, dict)]
    stage = _find_stage(stages, stage_id)
    stage["status"] = status
    doc["stages"] = stages
    write_yaml(path, doc)
    return stage


def set_stage_target_date(workspace: Path, stage_id: str, target_date: str | None) -> dict[str, Any]:
    """Set (or clear, with `target_date=None`) a stage's optional target
    completion date, an ISO `YYYY-MM-DD` string -- no time-of-day, since a
    research-stage deadline is a day, not a moment. Deterministic parsing
    only; an invalid date string is rejected rather than guessed at.
    """
    if target_date is not None:
        try:
            date.fromisoformat(target_date)
        except ValueError as exc:
            raise ValueError(f"Invalid target_date: {target_date!r}. Expected an ISO date, e.g. 2026-09-30.") from exc
    path = _stages_path(workspace)
    doc = read_yaml(path)
    stages = [stage for stage in doc.get("stages", []) if isinstance(stage, dict)]
    stage = _find_stage(stages, stage_id)
    if target_date is None:
        stage.pop("target_date", None)
    else:
        stage["target_date"] = target_date
    doc["stages"] = stages
    write_yaml(path, doc)
    return stage


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def stages_ics(workspace: Path) -> str:
    """A deterministic `.ics` calendar (RFC 5545) with one all-day VEVENT per
    stage that has a `target_date` set, so a user's existing calendar app
    can subscribe to or import research milestone due dates -- no new
    external service, just a standard local file format. Stages without a
    target date are omitted, not guessed at with an invented one.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace_slug = workspace.name or "workspace"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Corroborly//Research Stages//EN", "CALSCALE:GREGORIAN"]
    for stage in list_stages(workspace):
        target_date = stage.get("target_date")
        if not target_date:
            continue
        stage_id = str(stage.get("id", ""))
        name = str(stage.get("name", stage_id))
        status = str(stage.get("status", "not_started"))
        dtstart = target_date.replace("-", "")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{workspace_slug}-{stage_id}@corroborly.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"SUMMARY:{_ics_escape(name)}",
                f"DESCRIPTION:{_ics_escape(f'Corroborly research stage {stage_id} ({status})')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_stages_ics(workspace: Path) -> Path:
    output_path = workspace / "outputs" / "reports" / "research-stages.ics"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(stages_ics(workspace), encoding="utf-8")
    return output_path
