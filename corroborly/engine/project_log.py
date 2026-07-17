from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from corroborly.core.yamlio import read_yaml, write_yaml


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def add_decision(workspace: Path, text: str, *, reason: str = "") -> dict[str, str]:
    path = workspace / "decisions.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Decisions\n"
    decision_id = f"decision-{existing.count('## decision-') + 1:03d}"
    at = _utc_now()
    block = f"\n## {decision_id}\n\n- Decision: {text}\n- Reason: {reason or 'Not recorded'}\n- At: {at}\n"
    path.write_text(existing.rstrip() + block + "\n", encoding="utf-8")
    return {"id": decision_id, "decision": text, "reason": reason, "created_at": at}


def list_decisions(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "decisions.md"
    if not path.exists():
        return []
    decisions: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current is not None:
                decisions.append(current)
            current = {"id": line[3:].strip(), "decision": "", "reason": "", "created_at": ""}
        elif current is not None and line.strip().startswith("- Decision:"):
            current["decision"] = line.split(":", 1)[1].strip()
        elif current is not None and line.strip().startswith("- Reason:"):
            current["reason"] = line.split(":", 1)[1].strip()
        elif current is not None and line.strip().startswith("- At:"):
            current["created_at"] = line.split(":", 1)[1].strip()
    if current is not None:
        decisions.append(current)
    return decisions


def add_terminology(workspace: Path, term: str, definition: str) -> dict[str, str]:
    path = workspace / "terminology.yaml"
    doc = read_yaml(path)
    items = [item for item in doc.get("terms", []) if isinstance(item, dict)]
    existing = next((item for item in items if item.get("term") == term), None)
    record = {"term": term, "definition": definition, "created_at": existing.get("created_at") if existing else _utc_now()}
    items = [item for item in items if item.get("term") != term]
    items.append(record)
    doc["terms"] = items
    write_yaml(path, doc)
    return record


def list_terminology(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "terminology.yaml"
    if not path.exists():
        return []
    return [item for item in read_yaml(path).get("terms", []) if isinstance(item, dict)]


def add_feedback(workspace: Path, text: str, *, source: str = "") -> dict[str, str]:
    path = workspace / "supervisor-feedback.yaml"
    doc = read_yaml(path)
    items = [item for item in doc.get("items", []) if isinstance(item, dict)]
    record = {"id": f"feedback-{len(items) + 1:03d}", "source": source, "text": text, "status": "open", "created_at": _utc_now()}
    items.append(record)
    doc["items"] = items
    write_yaml(path, doc)
    return record


def list_feedback(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "supervisor-feedback.yaml"
    if not path.exists():
        return []
    return [item for item in read_yaml(path).get("items", []) if isinstance(item, dict)]


def add_context_change(workspace: Path, text: str) -> dict[str, str]:
    path = workspace / "context-changelog.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Context changelog\n"
    change_id = f"change-{existing.count('## change-') + 1:03d}"
    at = _utc_now()
    path.write_text(existing.rstrip() + f"\n\n## {change_id}\n\n- At: {at}\n\n{text}\n", encoding="utf-8")
    return {"id": change_id, "text": text, "created_at": at}


def list_context_changes(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "context-changelog.md"
    if not path.exists():
        return []
    changes: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current is not None:
                current["text"] = current["text"].strip()
                changes.append(current)
            current = {"id": line[3:].strip(), "text": "", "created_at": ""}
        elif current is not None and line.strip().startswith("- At:"):
            current["created_at"] = line.split(":", 1)[1].strip()
        elif current is not None:
            current["text"] += (line + "\n")
    if current is not None:
        current["text"] = current["text"].strip()
        changes.append(current)
    return changes


def timeline_report(workspace: Path) -> dict[str, Any]:
    """A unified, chronologically sorted view of workspace activity: run
    summaries, decisions, terminology changes, feedback, and context-changelog
    entries. Events from before per-record timestamps existed have no
    confirmed time and sort last (oldest) rather than being guessed at.
    """
    events: list[dict[str, Any]] = []
    for path in sorted((workspace / "outputs" / "logs" / "run-summaries").glob("*.yaml")):
        data = read_yaml(path)
        events.append(
            {
                "kind": "run_summary",
                "path": str(path),
                "command": data.get("command"),
                "status": data.get("status"),
                "at": data.get("started_at"),
            }
        )
    for decision in list_decisions(workspace):
        events.append({"kind": "decision", "id": decision["id"], "text": decision.get("decision"), "at": decision.get("created_at") or None})
    for term in list_terminology(workspace):
        events.append({"kind": "terminology", "id": term.get("term"), "text": term.get("definition"), "at": term.get("created_at") or None})
    for item in list_feedback(workspace):
        events.append({"kind": "feedback", "id": item.get("id"), "text": item.get("text"), "status": item.get("status"), "at": item.get("created_at") or None})
    for change in list_context_changes(workspace):
        events.append({"kind": "context_change", "id": change["id"], "text": change.get("text"), "at": change.get("created_at") or None})

    events.sort(key=lambda event: event["at"] or "")

    report = {"version": 1, "event_count": len(events), "events": events}
    write_yaml(workspace / "outputs" / "reports" / "timeline.yaml", report)
    return report
