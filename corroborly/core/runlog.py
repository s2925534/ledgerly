from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .yamlio import write_yaml


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunSummary:
    command: str
    workspace: str
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None

    files_processed: int = 0
    files_succeeded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    warnings: int = 0
    errors: int = 0

    output_files_created: list[str] = field(default_factory=list)
    next_recommended_action: Optional[str] = None

    def start_clock(self) -> None:
        self._t0 = time.time()  # type: ignore[attr-defined]

    def complete(self, *, next_action: Optional[str] = None) -> None:
        self.completed_at = utc_now_iso()
        self.duration_seconds = max(0.0, time.time() - self._t0)
        self.next_recommended_action = next_action


class JsonlLogger:
    def __init__(self, log_path: Path, *, command: str, workspace: Path, level: str = "info"):
        self.log_path = log_path
        self.command = command
        self.workspace = str(workspace)
        self.level = level

    def log(self, level: str, message: str, **fields: Any) -> None:
        payload = {
            "timestamp": utc_now_iso(),
            "level": level,
            "command": self.command,
            "workspace": self.workspace,
            "message": message,
            **fields,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def info(self, message: str, **fields: Any) -> None:
        self.log("info", message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self.log("warning", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self.log("error", message, **fields)

    def debug(self, message: str, **fields: Any) -> None:
        self.log("debug", message, **fields)


def make_run_paths(workspace: Path, command_slug: str) -> tuple[Path, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = workspace / "outputs" / "logs" / f"{ts}__{command_slug}.jsonl"
    summary_path = workspace / "outputs" / "logs" / "run-summaries" / f"{ts}__{command_slug}.yaml"
    return log_path, summary_path


def write_run_summary(path: Path, summary: RunSummary) -> None:
    data = {
        "command": summary.command,
        "started_at": summary.started_at,
        "completed_at": summary.completed_at,
        "duration_seconds": summary.duration_seconds,
        "workspace": summary.workspace,
        "files_processed": summary.files_processed,
        "files_succeeded": summary.files_succeeded,
        "files_skipped": summary.files_skipped,
        "files_failed": summary.files_failed,
        "warnings": summary.warnings,
        "errors": summary.errors,
        "output_files_created": summary.output_files_created,
        "next_recommended_action": summary.next_recommended_action,
    }
    write_yaml(path, data)