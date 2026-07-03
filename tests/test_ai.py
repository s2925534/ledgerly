import json
from pathlib import Path
from urllib.request import Request

import pytest

from researchboss.engine.ai import (
    OpenAiCredentials,
    OpenAiError,
    load_dotenv_values,
    openai_credentials,
    openai_readiness,
    require_ai_flag,
)
from researchboss.engine.workspace import init_workspace


class FakeResponse:
    def __init__(self, data: object):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.data


def test_load_dotenv_values_reads_openai_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")

    values = load_dotenv_values(env_path)

    assert values["OPENAI_API_KEY"] == "sk-test"


def test_openai_credentials_read_workspace_env_without_exposing_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")

    credentials = openai_credentials(workspace)

    assert credentials.api_key == "sk-secret"


def test_openai_credentials_missing_key_raises_without_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OpenAiError, match="Missing OPENAI_API_KEY"):
        openai_credentials(tmp_path / "workspace")


def test_require_ai_flag_blocks_ai_actions_without_explicit_opt_in() -> None:
    with pytest.raises(OpenAiError, match="Pass --ai"):
        require_ai_flag(False)


def test_openai_readiness_local_check_does_not_call_network_or_expose_key(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    def opener(_request: Request):
        raise AssertionError("network should not be called")

    report = openai_readiness(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        live=False,
        opener=opener,
    )

    assert report["key_loaded"] is True
    assert report["live_request_performed"] is False
    assert report["workspace_ai_enabled"] is False
    assert "sk-secret" not in str(report)


def test_openai_readiness_live_check_uses_bearer_token_without_exposing_key(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    def opener(request: Request):
        assert request.get_method() == "GET"
        assert request.headers["Authorization"] == "Bearer sk-secret"
        return FakeResponse({"data": [{"id": "model-a"}, {"id": "model-b"}]})

    report = openai_readiness(
        workspace,
        OpenAiCredentials(api_key="sk-secret"),
        live=True,
        opener=opener,
    )

    assert report["live_request_performed"] is True
    assert report["api_reachable"] is True
    assert report["model_count"] == 2
    assert "sk-secret" not in str(report)
