from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corroborly.core.yamlio import read_yaml, write_yaml

PROGRESS_LOG_FILE = "research-progress-log.yaml"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_progress_event(workspace: Path, *, kind: str, entity_id: str, detail: str = "") -> dict[str, Any]:
    """Append one entry to the append-only research-progress log. Called by the
    research-question and artefact lifecycle functions so "activity over time"
    is an honest record of things that actually happened, not a count derived
    after the fact from data that was never timestamped.
    """
    path = workspace / PROGRESS_LOG_FILE
    doc = read_yaml(path) if path.exists() else {}
    events = list(doc.get("events", []))
    event = {"at": _utc_now(), "kind": kind, "entity_id": entity_id, "detail": detail}
    events.append(event)
    doc["events"] = events
    write_yaml(path, doc)
    return event


def list_progress_events(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / PROGRESS_LOG_FILE
    if not path.exists():
        return []
    return [event for event in read_yaml(path).get("events", []) if isinstance(event, dict)]


def research_progress_report(workspace: Path) -> dict[str, Any]:
    """A lightweight, honest local record of research question / artefact
    activity over time — not a gamified streak feature, just what happened
    and when, for anyone writing a progress report to a supervisor.
    """
    events = list_progress_events(workspace)
    report = {"version": 1, "event_count": len(events), "events": events}
    write_yaml(workspace / "outputs" / "reports" / "research-progress.yaml", report)
    return report
