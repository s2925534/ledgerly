import json
import sys
import types
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from corroborly.engine.scholar_providers import (
    ScholarDataService,
    ScholarProviderError,
    _fetch_scholarapi_net,
    _fetch_scholarly,
    _fetch_semantic_scholar,
    _fetch_serpapi,
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


def _opener(data: object):
    def _open(_request: Request):
        return FakeResponse(data)

    return _open


def _raising_opener(exc: Exception):
    def _open(_request: Request):
        raise exc

    return _open


# --------------------------------------------------------------------------
# Option 1: SerpApi
# --------------------------------------------------------------------------


def test_serpapi_raises_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    with pytest.raises(ScholarProviderError, match="SERPAPI_API_KEY"):
        _fetch_serpapi("container logistics", 5, workspace=tmp_path, opener=_opener({}))


def test_serpapi_parses_organic_results(monkeypatch, tmp_path):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    data = {
        "organic_results": [
            {
                "title": "Container Terminal Efficiency",
                "link": "https://example.com/paper1",
                "snippet": "An abstract about terminals.",
                "publication_info": {
                    "summary": "A Author, B Author - 2021 - Journal of Ports",
                    "authors": [{"name": "A Author"}, {"name": "B Author"}],
                },
                "inline_links": {"cited_by": {"total": 42}},
            }
        ]
    }
    results = _fetch_serpapi("container logistics", 5, workspace=tmp_path, opener=_opener(data))
    assert len(results) == 1
    result = results[0]
    assert result.title == "Container Terminal Efficiency"
    assert result.authors == ["A Author", "B Author"]
    assert result.year == 2021
    assert result.citation_count == 42
    assert result.source_provider == "serpapi"


def test_serpapi_raises_on_api_error_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    with pytest.raises(ScholarProviderError, match="SerpApi error"):
        _fetch_serpapi("q", 5, workspace=tmp_path, opener=_opener({"error": "Invalid API key."}))


def test_serpapi_raises_on_http_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    exc = HTTPError("url", 429, "Too Many Requests", None, None)
    with pytest.raises(ScholarProviderError, match="HTTP 429"):
        _fetch_serpapi("q", 5, workspace=tmp_path, opener=_raising_opener(exc))


# --------------------------------------------------------------------------
# Option 2: Semantic Scholar
# --------------------------------------------------------------------------


def test_semantic_scholar_works_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    data = {
        "data": [
            {
                "title": "Evidence Tracking in Research Workflows",
                "authors": [{"name": "C Author"}],
                "year": 2022,
                "citationCount": 10,
                "abstract": "An abstract.",
                "venue": "Journal of Evidence",
                "url": "https://example.com/paper2",
            }
        ]
    }
    results = _fetch_semantic_scholar("evidence tracking", 5, workspace=tmp_path, opener=_opener(data))
    assert len(results) == 1
    result = results[0]
    assert result.title == "Evidence Tracking in Research Workflows"
    assert result.authors == ["C Author"]
    assert result.year == 2022
    assert result.citation_count == 10
    assert result.venue == "Journal of Evidence"
    assert result.source_provider == "semantic_scholar"


def test_semantic_scholar_raises_on_url_error(monkeypatch, tmp_path):
    from urllib.error import URLError

    exc = URLError("no network")
    with pytest.raises(ScholarProviderError, match="Semantic Scholar request failed"):
        _fetch_semantic_scholar("q", 5, workspace=tmp_path, opener=_raising_opener(exc))


# --------------------------------------------------------------------------
# Option 3: scholarly
# --------------------------------------------------------------------------


def test_scholarly_raises_when_package_missing(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "scholarly", None)
    with pytest.raises(ScholarProviderError, match="scholarly"):
        _fetch_scholarly("q", 5, workspace=tmp_path, opener=None)


def test_scholarly_parses_search_pubs_results(monkeypatch, tmp_path):
    fake_module = types.ModuleType("scholarly")

    class _FakeScholarly:
        @staticmethod
        def search_pubs(_query):
            yield {
                "bib": {
                    "title": "Smart Port Digital Twins",
                    "author": ["D Author", "E Author"],
                    "pub_year": "2020",
                    "venue": "Port Systems Review",
                },
                "num_citations": 5,
                "pub_url": "https://example.com/paper3",
            }

    fake_module.scholarly = _FakeScholarly()
    monkeypatch.setitem(sys.modules, "scholarly", fake_module)

    results = _fetch_scholarly("smart port", 5, workspace=tmp_path, opener=None)
    assert len(results) == 1
    result = results[0]
    assert result.title == "Smart Port Digital Twins"
    assert result.authors == ["D Author", "E Author"]
    assert result.year == 2020
    assert result.citation_count == 5
    assert result.source_provider == "scholarly"


def test_scholarly_wraps_unexpected_errors(monkeypatch, tmp_path):
    fake_module = types.ModuleType("scholarly")

    class _FakeScholarly:
        @staticmethod
        def search_pubs(_query):
            raise RuntimeError("blocked by Google")

    fake_module.scholarly = _FakeScholarly()
    monkeypatch.setitem(sys.modules, "scholarly", fake_module)

    with pytest.raises(ScholarProviderError, match="blocked by Google"):
        _fetch_scholarly("q", 5, workspace=tmp_path, opener=None)


# --------------------------------------------------------------------------
# Option 4: ScholarAPI (scholarapi.net) stub
# --------------------------------------------------------------------------


def test_scholarapi_net_is_a_stub_that_always_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("SCHOLARAPI_NET_API_KEY", raising=False)
    with pytest.raises(ScholarProviderError, match="SCHOLARAPI_NET_API_KEY"):
        _fetch_scholarapi_net("q", 5, workspace=tmp_path, opener=None)

    monkeypatch.setenv("SCHOLARAPI_NET_API_KEY", "some-key")
    with pytest.raises(ScholarProviderError, match="stub"):
        _fetch_scholarapi_net("q", 5, workspace=tmp_path, opener=None)


# --------------------------------------------------------------------------
# Unified pipeline (ScholarDataService)
# --------------------------------------------------------------------------


def test_service_falls_through_to_semantic_scholar_when_serpapi_key_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "scholarly", None)

    data = {
        "data": [
            {
                "title": "Fallback Result",
                "authors": [],
                "year": 2023,
                "citationCount": 1,
                "abstract": None,
                "venue": None,
                "url": "https://example.com/paper4",
            }
        ]
    }
    service = ScholarDataService(workspace=tmp_path, opener=_opener(data))
    response = service.search("container logistics", max_results=3)

    assert response.succeeded is True
    assert response.provider_used == "semantic_scholar"
    assert len(response.results) == 1
    assert response.results[0].title == "Fallback Result"

    statuses = {attempt.provider: attempt.status for attempt in response.attempts}
    assert statuses["serpapi"] == "error"
    assert statuses["semantic_scholar"] == "ok"


def test_service_stops_at_first_successful_provider_even_with_zero_results(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    service = ScholarDataService(workspace=tmp_path, opener=_opener({"data": []}))
    response = service.search("no results query")

    assert response.succeeded is True
    assert response.provider_used == "semantic_scholar"
    assert response.results == []


def test_service_reports_failure_when_every_option_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("SCHOLARAPI_NET_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "scholarly", None)

    from urllib.error import URLError

    service = ScholarDataService(workspace=tmp_path, opener=_raising_opener(URLError("offline")))
    response = service.search("container logistics")

    assert response.succeeded is False
    assert response.provider_used is None
    assert response.results == []
    assert len(response.attempts) == 4
    assert all(attempt.status == "error" for attempt in response.attempts)


def test_service_rejects_empty_query():
    service = ScholarDataService()
    with pytest.raises(ValueError):
        service.search("   ")
