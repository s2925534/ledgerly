"""Google Scholar data provider layer with a sequential fallback pipeline.

There is no official Google Scholar API. `ScholarDataService.search()` tries
a sequence of backends in order and returns the first one that completes
without raising:

  1. SerpApi's Google Scholar engine (structured JSON, needs SERPAPI_API_KEY)
  2. Semantic Scholar's official Graph API (free, works without a key)
  3. the open-source `scholarly` package (optional dependency, scrapes
     Google Scholar directly and can be IP-blocked/rate-limited)
  4. ScholarAPI (scholarapi.net) -- currently a stub, see
     `_fetch_scholarapi_net` for why

This module is intentionally self-contained: it does not import from, or
get imported by, `corroborly.engine.external_search` (the existing
Scopus-based provider) or any CLI/router code, so it cannot regress
existing behavior. Nothing outside this file references it yet.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from corroborly.engine.ai import load_dotenv_values

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = "title,authors,year,citationCount,abstract,venue,url"

Opener = Callable[[Request], Any]


class ScholarProviderError(RuntimeError):
    """Raised by a single provider when it cannot serve a request.

    `ScholarDataService.search()` catches this (and only this, plus a
    belt-and-braces catch-all for genuinely unexpected errors) and moves on
    to the next provider in the pipeline.
    """


@dataclass(frozen=True)
class ScholarResult:
    title: str
    authors: list[str]
    year: int | None
    citation_count: int | None
    url: str | None
    abstract: str | None
    venue: str | None
    source_provider: str


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    status: str  # "ok" | "error"
    detail: str


@dataclass(frozen=True)
class ScholarSearchResponse:
    query: str
    provider_used: str | None
    results: list[ScholarResult]
    attempts: list[ProviderAttempt]

    @property
    def succeeded(self) -> bool:
        return self.provider_used is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "succeeded": self.succeeded,
            "result_count": len(self.results),
        }


def _env_value(key: str, *, workspace: Path | None) -> str:
    env_values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        env_values = {**env_values, **load_dotenv_values(workspace / ".env")}
    return os.environ.get(key) or env_values.get(key) or ""


def _extract_year(text: Any) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", str(text or ""))
    return int(match.group(0)) if match else None


def _safe_int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _http_get_json(request: Request, *, opener: Opener | None, provider_label: str) -> Any:
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ScholarProviderError(f"{provider_label} request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise ScholarProviderError(f"{provider_label} request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ScholarProviderError(f"{provider_label} returned invalid JSON") from exc


# --------------------------------------------------------------------------
# Option 1: SerpApi (Google Scholar engine)
# --------------------------------------------------------------------------


def _fetch_serpapi(
    query: str,
    max_results: int,
    *,
    workspace: Path | None,
    opener: Opener | None,
) -> list[ScholarResult]:
    api_key = _env_value("SERPAPI_API_KEY", workspace=workspace)
    if not api_key:
        raise ScholarProviderError("Missing SERPAPI_API_KEY")

    params = {"engine": "google_scholar", "q": query, "api_key": api_key, "num": max_results}
    request = Request(f"{SERPAPI_URL}?{urlencode(params)}", headers={"Accept": "application/json"}, method="GET")
    data = _http_get_json(request, opener=opener, provider_label="SerpApi")

    if isinstance(data, dict) and data.get("error"):
        raise ScholarProviderError(f"SerpApi error: {data['error']}")

    organic = data.get("organic_results") if isinstance(data, dict) else None
    organic = organic if isinstance(organic, list) else []

    results = []
    for entry in organic[:max_results]:
        if not isinstance(entry, dict):
            continue
        publication_info = entry.get("publication_info") if isinstance(entry.get("publication_info"), dict) else {}
        authors_list = publication_info.get("authors") if isinstance(publication_info.get("authors"), list) else []
        inline_links = entry.get("inline_links") if isinstance(entry.get("inline_links"), dict) else {}
        cited_by = inline_links.get("cited_by") if isinstance(inline_links.get("cited_by"), dict) else {}
        results.append(
            ScholarResult(
                title=str(entry.get("title") or "Untitled"),
                authors=[str(author["name"]) for author in authors_list if isinstance(author, dict) and author.get("name")],
                year=_extract_year(publication_info.get("summary")),
                citation_count=_safe_int_or_none(cited_by.get("total")),
                url=entry.get("link"),
                abstract=entry.get("snippet"),
                venue=None,
                source_provider="serpapi",
            )
        )
    return results


# --------------------------------------------------------------------------
# Option 2: Semantic Scholar API (free, official, no key required)
# --------------------------------------------------------------------------


def _fetch_semantic_scholar(
    query: str,
    max_results: int,
    *,
    workspace: Path | None,
    opener: Opener | None,
) -> list[ScholarResult]:
    params = {"query": query, "limit": max_results, "fields": SEMANTIC_SCHOLAR_FIELDS}
    headers = {"Accept": "application/json"}
    api_key = _env_value("SEMANTIC_SCHOLAR_API_KEY", workspace=workspace)
    if api_key:
        headers["x-api-key"] = api_key

    request = Request(f"{SEMANTIC_SCHOLAR_SEARCH_URL}?{urlencode(params)}", headers=headers, method="GET")
    data = _http_get_json(request, opener=opener, provider_label="Semantic Scholar")

    papers = data.get("data") if isinstance(data, dict) else None
    papers = papers if isinstance(papers, list) else []

    results = []
    for entry in papers[:max_results]:
        if not isinstance(entry, dict):
            continue
        authors_list = entry.get("authors") if isinstance(entry.get("authors"), list) else []
        results.append(
            ScholarResult(
                title=str(entry.get("title") or "Untitled"),
                authors=[str(author["name"]) for author in authors_list if isinstance(author, dict) and author.get("name")],
                year=_safe_int_or_none(entry.get("year")),
                citation_count=_safe_int_or_none(entry.get("citationCount")),
                url=entry.get("url"),
                abstract=entry.get("abstract"),
                venue=entry.get("venue") or None,
                source_provider="semantic_scholar",
            )
        )
    return results


# --------------------------------------------------------------------------
# Option 3: `scholarly` library (open-source Google Scholar scraper)
# --------------------------------------------------------------------------


def _split_author_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r",| and ", value) if part.strip()]
    return []


def _fetch_scholarly(
    query: str,
    max_results: int,
    *,
    workspace: Path | None,
    opener: Opener | None,
) -> list[ScholarResult]:
    try:
        from scholarly import scholarly  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ScholarProviderError(
            "The optional 'scholarly' package is not installed. Install with: pip install 'corroborly[scholar]'"
        ) from exc

    try:
        search_iterator = scholarly.search_pubs(query)
        results = []
        for _ in range(max_results):
            try:
                entry = next(search_iterator)
            except StopIteration:
                break
            if not isinstance(entry, dict):
                continue
            bib = entry.get("bib") if isinstance(entry.get("bib"), dict) else {}
            results.append(
                ScholarResult(
                    title=str(bib.get("title") or "Untitled"),
                    authors=_split_author_field(bib.get("author")),
                    year=_safe_int_or_none(bib.get("pub_year")),
                    citation_count=_safe_int_or_none(entry.get("num_citations")),
                    url=entry.get("pub_url") or entry.get("eprint_url"),
                    abstract=bib.get("abstract"),
                    venue=bib.get("venue") or bib.get("journal"),
                    source_provider="scholarly",
                )
            )
        return results
    except ScholarProviderError:
        raise
    except Exception as exc:
        # scholarly raises a mix of its own exceptions and requests/urllib
        # errors for rate limits and IP blocks; normalize all of them so the
        # pipeline can fall through uniformly.
        raise ScholarProviderError(f"scholarly library search failed: {exc}") from exc


# --------------------------------------------------------------------------
# Option 4: ScholarAPI (scholarapi.net) -- STUB, not implemented
# --------------------------------------------------------------------------


def _fetch_scholarapi_net(
    query: str,
    max_results: int,
    *,
    workspace: Path | None,
    opener: Opener | None,
) -> list[ScholarResult]:
    """Placeholder for the ScholarAPI (scholarapi.net) gateway.

    Not implemented: I could not verify this service's endpoint URL,
    authentication scheme, or response schema against documentation I can
    confirm is accurate. Guessing at a request/response contract here would
    silently produce wrong data instead of an honest failure, so this stub
    always raises `ScholarProviderError` -- the pipeline logs it and falls
    through cleanly, same as a real outage would.

    To finish this option: confirm the real base URL and auth header from
    an actual account/API docs, then mirror `_fetch_serpapi` /
    `_fetch_semantic_scholar` above (build a `Request`, call
    `_http_get_json(..., opener=opener, ...)` so tests can inject a fake
    opener, and map the response into `ScholarResult`).
    """
    api_key = _env_value("SCHOLARAPI_NET_API_KEY", workspace=workspace)
    if not api_key:
        raise ScholarProviderError("Missing SCHOLARAPI_NET_API_KEY (also: this provider is a stub, see docstring)")
    raise ScholarProviderError("ScholarAPI (scholarapi.net) provider is a stub; endpoint/response contract not yet implemented")


# --------------------------------------------------------------------------
# Unified interface
# --------------------------------------------------------------------------

_ProviderFn = Callable[..., list[ScholarResult]]

_PROVIDER_PIPELINE: list[tuple[str, _ProviderFn]] = [
    ("serpapi", _fetch_serpapi),
    ("semantic_scholar", _fetch_semantic_scholar),
    ("scholarly", _fetch_scholarly),
    ("scholarapi_net", _fetch_scholarapi_net),
]


class ScholarDataService:
    """Single entry point the rest of the app should call for Scholar data.

    Tries each backend in `_PROVIDER_PIPELINE` order and returns the first
    one that completes without raising -- including a provider that
    legitimately returns zero results, which is treated as a valid answer,
    not a failure. Only exceptions (missing keys, HTTP errors, rate limits,
    blocks, an uninstalled optional package) trigger a fallback to the next
    option. Every attempt, successful or not, is recorded on the returned
    `ScholarSearchResponse.attempts` for observability.
    """

    def __init__(self, *, workspace: Path | None = None, opener: Opener | None = None) -> None:
        self._workspace = workspace
        self._opener = opener

    def search(self, query: str, *, max_results: int = 10) -> ScholarSearchResponse:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")

        attempts: list[ProviderAttempt] = []
        for name, provider_fn in _PROVIDER_PIPELINE:
            try:
                results = provider_fn(
                    normalized_query,
                    max_results,
                    workspace=self._workspace,
                    opener=self._opener,
                )
            except ScholarProviderError as exc:
                logger.warning("Scholar provider '%s' failed, falling back: %s", name, exc)
                attempts.append(ProviderAttempt(provider=name, status="error", detail=str(exc)))
                continue
            except Exception as exc:  # belt-and-braces: one backend must never crash the pipeline
                logger.exception("Scholar provider '%s' raised an unexpected error", name)
                attempts.append(ProviderAttempt(provider=name, status="error", detail=f"unexpected error: {exc}"))
                continue

            attempts.append(ProviderAttempt(provider=name, status="ok", detail=f"{len(results)} result(s)"))
            return ScholarSearchResponse(
                query=normalized_query,
                provider_used=name,
                results=results,
                attempts=attempts,
            )

        logger.error("All Scholar providers failed for query: %s", normalized_query)
        return ScholarSearchResponse(query=normalized_query, provider_used=None, results=[], attempts=attempts)
