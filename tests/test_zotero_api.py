import json
from pathlib import Path
from urllib.request import Request

import pytest

from corroborly.engine.zotero_api import (
    ZoteroApiCredentials,
    ZoteroApiError,
    clear_zotero_api_credentials,
    load_dotenv_values,
    save_zotero_api_credentials,
    write_dotenv_values,
    zotero_api_collections,
    zotero_api_credentials,
    zotero_api_readiness,
)


class FakeResponse:
    def __init__(self, data: object):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.data


def test_load_dotenv_values_reads_zotero_credentials(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("ZOTERO_API_KEY=abc\nZOTERO_USER_ID=123\n", encoding="utf-8")

    values = load_dotenv_values(env_path)

    assert values["ZOTERO_API_KEY"] == "abc"
    assert values["ZOTERO_USER_ID"] == "123"


def test_write_dotenv_values_preserves_other_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nOPENAI_API_KEY=keep-me\nZOTERO_API_KEY=old\n", encoding="utf-8")

    write_dotenv_values(env_path, {"ZOTERO_API_KEY": "new-key", "ZOTERO_USER_ID": "42"})

    values = load_dotenv_values(env_path)
    assert values["OPENAI_API_KEY"] == "keep-me"
    assert values["ZOTERO_API_KEY"] == "new-key"
    assert values["ZOTERO_USER_ID"] == "42"
    assert "# comment" in env_path.read_text(encoding="utf-8")


def test_write_dotenv_values_creates_missing_file(tmp_path: Path) -> None:
    env_path = tmp_path / "nested" / ".env"

    write_dotenv_values(env_path, {"ZOTERO_API_KEY": "abc"})

    assert load_dotenv_values(env_path)["ZOTERO_API_KEY"] == "abc"


def test_save_and_clear_zotero_api_credentials_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # zotero_api_credentials() also merges in Path.cwd()/.env; isolate from
    # the real repo-root .env (a developer's actual Zotero credentials) so
    # this test's "cleared -> raises" assertion can't pass or fail based on
    # whatever happens to be configured on the machine running it.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)

    save_zotero_api_credentials(tmp_path, "  my-key  ", " 999 ")

    credentials = zotero_api_credentials(tmp_path)
    assert credentials.api_key == "my-key"
    assert credentials.user_id == "999"

    clear_zotero_api_credentials(tmp_path)
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ZOTERO_API_KEY" not in env_text
    assert "ZOTERO_USER_ID" not in env_text
    with pytest.raises(ZoteroApiError):
        zotero_api_credentials(tmp_path)


def test_save_zotero_api_credentials_rejects_blank_values(tmp_path: Path) -> None:
    with pytest.raises(ZoteroApiError):
        save_zotero_api_credentials(tmp_path, "", "999")
    with pytest.raises(ZoteroApiError):
        save_zotero_api_credentials(tmp_path, "key", "  ")


def test_zotero_api_readiness_reports_write_access_without_exposing_key() -> None:
    def opener(request: Request):
        assert request.get_method() == "GET"
        assert request.headers["Zotero-api-key"] == "secret"
        return FakeResponse({"access": {"user": {"library": True, "notes": True, "write": False}}})

    report = zotero_api_readiness(ZoteroApiCredentials(api_key="secret", user_id="42"), opener=opener)

    assert report["key_loaded"] is True
    assert report["key_has_write_access"] is False
    assert "secret" not in str(report)


def test_zotero_api_collections_maps_response() -> None:
    def opener(_request: Request):
        return FakeResponse(
            [
                {"key": "ABC", "version": 1, "data": {"name": "Thesis", "parentCollection": False}},
                {"key": "DEF", "version": 2, "data": {"name": "Chapter", "parentCollection": "ABC"}},
            ]
        )

    rows = zotero_api_collections(ZoteroApiCredentials(api_key="secret", user_id="42"), opener=opener)

    assert rows == [
        {"key": "ABC", "name": "Thesis", "parent_key": False, "version": 1, "source": "zotero_web_api"},
        {"key": "DEF", "name": "Chapter", "parent_key": "ABC", "version": 2, "source": "zotero_web_api"},
    ]


def test_zotero_api_requires_json_response() -> None:
    class BadResponse(FakeResponse):
        def __init__(self):
            self.data = b"not-json"

    with pytest.raises(ZoteroApiError, match="invalid JSON"):
        zotero_api_readiness(ZoteroApiCredentials(api_key="secret", user_id="42"), opener=lambda _request: BadResponse())
