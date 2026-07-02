from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Optional

from researchboss.core.constants import WORKSPACE_FILES, ensure_workspace_dirs
from researchboss.core.yamlio import write_yaml


PROJECT_TYPES = ["M.Phil", "PhD", "Other academic research", "Industry research", "Custom"]
SOURCE_MODES = {"local_folder", "zotero_storage", "configure_later"}


def default_documents_dir(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / "Documents"


def zotero_storage_candidates(home: Optional[Path] = None, system: Optional[str] = None) -> list[Path]:
    user_home = home or Path.home()
    os_name = system or platform.system()

    if os_name == "Darwin":
        return [
            user_home / "Zotero" / "storage",
            *sorted((user_home / "Library" / "Application Support" / "Zotero" / "Profiles").glob("*/storage")),
        ]

    if os_name == "Windows":
        app_data = user_home / "AppData" / "Roaming" / "Zotero" / "Profiles"
        return [
            user_home / "Zotero" / "storage",
            user_home / "Documents" / "Zotero" / "storage",
            *sorted(app_data.glob("*/storage")),
        ]

    return []


def find_default_zotero_storage(home: Optional[Path] = None, system: Optional[str] = None) -> Optional[Path]:
    for candidate in zotero_storage_candidates(home=home, system=system):
        if candidate.is_dir():
            return candidate
    return None


def infer_source_mode(source_answer: str, zotero_storage: Optional[Path] = None) -> str:
    if source_answer in SOURCE_MODES:
        return source_answer

    source_path = Path(source_answer).expanduser()
    if zotero_storage and source_path == zotero_storage.expanduser():
        return "zotero_storage"

    if source_path.name == "storage" and source_path.parent.name == "Zotero":
        return "zotero_storage"

    return "local_folder"


def _default_app_settings() -> dict[str, Any]:
    return {
        "ai": {
            "enabled": False,
            "default_provider": "openai",
            "providers": {
                "openai": {
                    "enabled": True,
                    "api_key_env": "OPENAI_API_KEY",
                    "default_model": "gpt-4o-mini",
                    "reasoning_model": "gpt-4o",
                    "novelty_model": "gpt-4o",
                },
                "anthropic": {"enabled": False, "api_key_env": "ANTHROPIC_API_KEY", "future_flag": True},
                "local": {"enabled": False, "future_flag": True},
            },
            "feature_flags": {
                "ai_assisted_review": True,
                "novelty_assessment": True,
                "anthropic_provider": False,
                "local_llm_provider": False,
                "external_search": False,
            },
        }
    }


def init_workspace(
    workspace: Path,
    *,
    project_name: str,
    project_type: str,
    topic: str,
    strict_evidence_mode: bool = True,
    source_root: Optional[str] = None,
    source_mode: str = "configure_later",  # local_folder | zotero_storage | configure_later
    artefact_root: Optional[str] = None,
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    ensure_workspace_dirs(workspace)

    # Required YAML/MD files
    write_yaml(
        workspace / WORKSPACE_FILES.research_context,
        {
            "version": 1,
            "project": {
                "name": project_name,
                "type": project_type,
                "topic": topic,
                "strict_evidence_mode": strict_evidence_mode,
            },
            "sources": {"mode": source_mode, "root": source_root},
            "artefacts": {"root": artefact_root},
            "privacy": {
                "local_first": True,
                "do_not_upload_full_documents": True,
                "no_external_search_mvp": True,
            },
        },
    )

    write_yaml(workspace / WORKSPACE_FILES.research_state, {"version": 1, "current_stage": None, "last_scan_at": None})
    write_yaml(workspace / WORKSPACE_FILES.research_stages, {"version": 1, "stages": []})

    write_yaml(workspace / WORKSPACE_FILES.research_questions, {"version": 1, "research_questions": []})
    write_yaml(workspace / WORKSPACE_FILES.research_question_candidates, {"version": 1, "candidates": []})
    write_yaml(workspace / WORKSPACE_FILES.rejected_research_questions, {"version": 1, "rejected": []})

    write_yaml(workspace / WORKSPACE_FILES.source_register, {"version": 1, "sources": []})
    write_yaml(workspace / WORKSPACE_FILES.accepted_sources, {"version": 1, "source_ids": []})
    write_yaml(workspace / WORKSPACE_FILES.ignored_sources, {"version": 1, "ignored": []})  # keep reason per id
    write_yaml(workspace / WORKSPACE_FILES.maybe_sources, {"version": 1, "source_ids": []})

    write_yaml(workspace / WORKSPACE_FILES.claims_ledger, {"version": 1, "claims": []})
    write_yaml(workspace / WORKSPACE_FILES.novelty_ledger, {"version": 1, "assessments": []})
    write_yaml(workspace / WORKSPACE_FILES.terminology, {"version": 1, "terms": []})
    write_yaml(workspace / WORKSPACE_FILES.supervisor_feedback, {"version": 1, "items": []})
    write_yaml(workspace / WORKSPACE_FILES.artefact_registry, {"version": 1, "artefacts": []})

    (workspace / WORKSPACE_FILES.decisions_md).write_text("# Decisions\n", encoding="utf-8")
    (workspace / WORKSPACE_FILES.memory_md).write_text("# Memory\n", encoding="utf-8")
    (workspace / WORKSPACE_FILES.context_changelog_md).write_text("# Context changelog\n", encoding="utf-8")

    write_yaml(workspace / WORKSPACE_FILES.app_settings_local, _default_app_settings())

    (workspace / WORKSPACE_FILES.gitignore).write_text(
        "\n".join(
            [
                ".env",
                "__pycache__/",
                "*.pyc",
                ".pytest_cache/",
                ".mypy_cache/",
                ".ruff_cache/",
                "dist/",
                "build/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
