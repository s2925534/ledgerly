from pathlib import Path

from researchboss.core.constants import WORKSPACE_DIRS, WORKSPACE_FILES
from researchboss.core.yamlio import read_yaml
from researchboss.engine.workspace import (
    default_documents_dir,
    find_default_zotero_storage,
    infer_source_mode,
    init_workspace,
    zotero_storage_candidates,
)


def test_init_workspace_creates_expected_files_and_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="M.Phil",
        topic="Evidence-first testing",
        strict_evidence_mode=True,
        source_root="/tmp/sources",
        source_mode="local_folder",
        artefact_root=None,
    )

    expected_files = [
        WORKSPACE_FILES.research_context,
        WORKSPACE_FILES.research_state,
        WORKSPACE_FILES.research_stages,
        WORKSPACE_FILES.research_questions,
        WORKSPACE_FILES.research_question_candidates,
        WORKSPACE_FILES.rejected_research_questions,
        WORKSPACE_FILES.source_register,
        WORKSPACE_FILES.accepted_sources,
        WORKSPACE_FILES.ignored_sources,
        WORKSPACE_FILES.maybe_sources,
        WORKSPACE_FILES.claims_ledger,
        WORKSPACE_FILES.novelty_ledger,
        WORKSPACE_FILES.terminology,
        WORKSPACE_FILES.supervisor_feedback,
        WORKSPACE_FILES.artefact_registry,
        WORKSPACE_FILES.decisions_md,
        WORKSPACE_FILES.memory_md,
        WORKSPACE_FILES.context_changelog_md,
        WORKSPACE_FILES.app_settings_local,
        WORKSPACE_FILES.gitignore,
    ]

    for rel_path in expected_files:
        assert (workspace / rel_path).is_file(), rel_path

    for rel_path in WORKSPACE_DIRS:
        assert (workspace / rel_path).is_dir(), rel_path

    context = read_yaml(workspace / WORKSPACE_FILES.research_context)
    assert context["project"]["name"] == "Test Project"
    assert context["project"]["type"] == "M.Phil"
    assert context["project"]["strict_evidence_mode"] is True
    assert context["sources"] == {"mode": "local_folder", "root": "/tmp/sources"}
    assert context["privacy"]["local_first"] is True
    assert context["privacy"]["no_external_search_mvp"] is True


def test_default_app_settings_keep_ai_optional(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test Project",
        project_type="PhD",
        topic="",
    )

    settings = read_yaml(workspace / WORKSPACE_FILES.app_settings_local)

    assert settings["ai"]["enabled"] is False
    assert settings["ai"]["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert settings["ai"]["providers"]["anthropic"]["enabled"] is False
    assert settings["ai"]["providers"]["local"]["enabled"] is False

    gitignore = (workspace / WORKSPACE_FILES.gitignore).read_text(encoding="utf-8")
    assert ".env" in gitignore.splitlines()


def test_default_documents_dir_uses_home_documents(tmp_path: Path) -> None:
    assert default_documents_dir(home=tmp_path) == tmp_path / "Documents"


def test_zotero_storage_candidates_cover_macos_and_windows_defaults(tmp_path: Path) -> None:
    mac_candidates = zotero_storage_candidates(home=tmp_path, system="Darwin")
    windows_candidates = zotero_storage_candidates(home=tmp_path, system="Windows")

    assert tmp_path / "Zotero" / "storage" in mac_candidates
    assert tmp_path / "Library" / "Application Support" / "Zotero" / "Profiles" not in mac_candidates
    assert tmp_path / "Zotero" / "storage" in windows_candidates
    assert tmp_path / "Documents" / "Zotero" / "storage" in windows_candidates


def test_find_default_zotero_storage_prefers_user_zotero_storage(tmp_path: Path) -> None:
    storage = tmp_path / "Zotero" / "storage"
    storage.mkdir(parents=True)

    assert find_default_zotero_storage(home=tmp_path, system="Darwin") == storage
    assert find_default_zotero_storage(home=tmp_path, system="Windows") == storage


def test_find_default_zotero_storage_falls_back_to_profile_storage(tmp_path: Path) -> None:
    profile_storage = tmp_path / "Library" / "Application Support" / "Zotero" / "Profiles" / "abc.default" / "storage"
    profile_storage.mkdir(parents=True)

    assert find_default_zotero_storage(home=tmp_path, system="Darwin") == profile_storage


def test_infer_source_mode_from_answer() -> None:
    zotero_storage = Path("/Users/pedro/Zotero/storage")

    assert infer_source_mode("configure_later", zotero_storage) == "configure_later"
    assert infer_source_mode("local_folder", zotero_storage) == "local_folder"
    assert infer_source_mode(str(zotero_storage), zotero_storage) == "zotero_storage"
    assert infer_source_mode("/Users/pedro/Documents/papers", zotero_storage) == "local_folder"
