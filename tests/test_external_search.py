import json
from pathlib import Path
from urllib.request import Request

import pytest

from researchboss.core.yamlio import read_yaml
from researchboss.engine.external_search import (
    ExternalSearchError,
    ScopusCredentials,
    filter_unused_queries,
    generate_search_query_plan,
    query_history_key,
    record_queries_used,
    require_external_search_flag,
    scopus_readiness,
    scopus_search,
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


def test_require_external_search_flag_blocks_live_search_without_opt_in() -> None:
    with pytest.raises(ExternalSearchError, match="--external-search"):
        require_external_search_flag(False)


def test_generate_search_query_plan_uses_workspace_context_without_external_call(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test",
        project_type="PhD",
        topic="container port evidence tracking",
        research_questions=[{"question": "How does container tracking affect port review quality?", "status": "approved"}],
    )

    plan = generate_search_query_plan(workspace, max_queries=5)

    assert plan["external_search_performed"] is False
    assert 1 <= len(plan["queries"]) <= 5
    assert (workspace / "outputs" / "recommendations" / "external-search-query-plan.yaml").is_file()


def test_query_history_records_and_filters_used_queries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    query = '"container" AND "port"'

    history = record_queries_used(workspace, [query], [{"query": query, "processed": 3}])

    assert query_history_key(query) in history["queries"]
    assert filter_unused_queries(workspace, [query, '"new" AND "query"']) == ['"new" AND "query"']


def test_scopus_readiness_does_not_expose_credentials() -> None:
    def opener(request: Request):
        assert request.get_method() == "GET"
        assert request.headers["X-els-apikey"] == "scopus-secret"
        assert request.headers["X-els-insttoken"] == "inst-secret"
        return FakeResponse({"search-results": {"opensearch:totalResults": "10", "entry": []}})

    report = scopus_readiness(
        ScopusCredentials(api_key="scopus-secret", inst_token="inst-secret"),
        opener=opener,
    )

    assert report["key_loaded"] is True
    assert report["inst_token_loaded"] is True
    assert report["key_exposed"] is False
    assert "scopus-secret" not in str(report)
    assert "inst-secret" not in str(report)


def test_scopus_search_writes_snapshot_and_history(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    def opener(request: Request):
        assert "container" in request.full_url
        return FakeResponse({"search-results": {"entry": [{"dc:title": "Paper"}]}})

    report = scopus_search(
        workspace,
        ScopusCredentials(api_key="scopus-secret"),
        query='"container"',
        count=1,
        opener=opener,
    )

    assert report["metrics"]["processed"] == 1
    assert Path(report["snapshot_path"]).is_file()
    assert read_yaml(workspace / "outputs" / "recommendations" / "external-search-query-history.yaml")["queries"]
