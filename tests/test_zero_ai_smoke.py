"""Phase 27: proves "the tool fully works with zero AI configured" (AGENTS.md
Core Rule item 1) is an enforced guarantee, not just an assumption.

Explicitly unsets every AI/paid-external-API env var this codebase reads
(`OPENAI_API_KEY`, `SCOPUS_API_KEY`) and runs a smoke pass over the core,
non-AI CLI surface against a real workspace. If any deterministic command
started silently depending on an AI provider being configured, this fails.
"""

from pathlib import Path

from typer.testing import CliRunner

from corroborly.cli import app


runner = CliRunner()

AI_ENV_VARS = ["OPENAI_API_KEY", "SCOPUS_API_KEY"]


def _run(*args: str) -> object:
    return runner.invoke(app, [*args, "--quiet"])


def test_core_cli_surface_works_with_zero_ai_env_vars(tmp_path: Path, monkeypatch) -> None:
    for var in AI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # keep any home-relative dotenv lookups inside tmp_path
    workspace = tmp_path / "workspace"

    doctor_result = runner.invoke(app, ["doctor"])
    assert doctor_result.exit_code == 0, doctor_result.output

    version_result = runner.invoke(app, ["version"])
    assert version_result.exit_code == 0, version_result.output

    from corroborly.engine.workspace import init_workspace

    init_workspace(workspace, project_name="Zero AI Smoke Test", project_type="M.Phil", topic="")

    assert _run("status", "--workspace", str(workspace)).exit_code == 0
    assert _run("sources", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("claims", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("rqs", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("artefacts", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("guidelines", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("decisions", "list", "--workspace", str(workspace)).exit_code == 0
    assert _run("timeline", "--workspace", str(workspace)).exit_code == 0
    assert _run("research-progress", "--workspace", str(workspace)).exit_code == 0
    assert _run("citation-relationships", "--workspace", str(workspace)).exit_code == 0
