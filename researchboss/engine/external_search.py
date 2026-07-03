from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.ai import load_dotenv_values


SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
QUOTE_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


@dataclass(frozen=True)
class ScopusCredentials:
    api_key: str
    inst_token: str | None = None


class ExternalSearchError(RuntimeError):
    pass


def require_external_search_flag(enabled: bool) -> None:
    if not enabled:
        raise ExternalSearchError("Pass --external-search to explicitly allow this external academic search action.")


def scopus_credentials(workspace: Path | None = None) -> ScopusCredentials:
    env_values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        env_values = {**env_values, **load_dotenv_values(workspace / ".env")}
    api_key = os.environ.get("SCOPUS_API_KEY") or env_values.get("SCOPUS_API_KEY") or ""
    inst_token = os.environ.get("INST_TOKEN") or env_values.get("INST_TOKEN") or None
    if not api_key:
        raise ExternalSearchError("Missing SCOPUS_API_KEY")
    return ScopusCredentials(api_key=api_key, inst_token=inst_token)


def normalize_query_line(line: str) -> str:
    line = line.translate(QUOTE_TRANSLATION).strip()
    if line.startswith("(") and line.endswith(")"):
        line = line[1:-1].strip()
    return re.sub(r"\s+", " ", line)


def query_history_key(query: str) -> str:
    return normalize_query_line(query).lower()


def _quote(term: str) -> str:
    return f'"{term}"'


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        normalized = normalize_query_line(item)
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            out.append(normalized)
    return out


def _context_text(workspace: Path) -> str:
    context = read_yaml(workspace / "research-context.yaml")
    project = context.get("project", {}) if isinstance(context.get("project"), dict) else {}
    parts = [str(project.get("topic") or ""), str(project.get("type") or "")]
    for path in (workspace / "research-questions.yaml", workspace / "research-question-candidates.yaml"):
        data = read_yaml(path)
        for key in ("research_questions", "candidates"):
            for item in data.get(key, []):
                if isinstance(item, dict):
                    parts.append(str(item.get("question") or ""))
                    parts.extend(str(sub) for sub in item.get("subquestions", []) if sub)
    return " ".join(parts)


def _terms_from_context(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", text.lower())
    stop = {
        "research",
        "question",
        "questions",
        "within",
        "using",
        "does",
        "what",
        "which",
        "this",
        "that",
        "with",
        "from",
        "into",
        "quality",
        "effect",
        "affect",
    }
    counts: dict[str, int] = {}
    for word in words:
        if word not in stop:
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda word: (-counts[word], word))
    return ranked[:12] or ["evidence", "research", "workflow"]


def generate_search_query_plan(workspace: Path, *, max_queries: int = 20) -> dict[str, Any]:
    terms = _terms_from_context(_context_text(workspace))
    anchors = terms[:4]
    methods = terms[4:10] or terms[:4]
    queries = []
    for anchor in anchors:
        for method in methods:
            if anchor != method:
                queries.append(f"{_quote(anchor)} AND {_quote(method)}")
    queries = _dedupe(queries)[: max(1, max_queries)]
    plan = {
        "version": 1,
        "source": "research_context_and_research_questions",
        "external_search_performed": False,
        "queries": queries,
    }
    write_yaml(workspace / "outputs" / "recommendations" / "external-search-query-plan.yaml", plan)
    return plan


def query_history_path(workspace: Path) -> Path:
    return workspace / "outputs" / "recommendations" / "external-search-query-history.yaml"


def load_query_history(workspace: Path) -> dict[str, Any]:
    path = query_history_path(workspace)
    if not path.is_file():
        return {"version": 1, "queries": {}}
    data = read_yaml(path)
    if isinstance(data.get("queries"), dict):
        return data
    return {"version": 1, "queries": {}}


def record_queries_used(workspace: Path, queries: list[str], metrics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    history = load_query_history(workspace)
    records = history.setdefault("queries", {})
    metrics_by_query = {query_history_key(str(item.get("query") or "")): item for item in metrics or []}
    now = datetime.now(timezone.utc).isoformat()
    for query in _dedupe(queries):
        key = query_history_key(query)
        previous = records.get(key, {})
        records[key] = {
            "query": normalize_query_line(query),
            "first_used_at": previous.get("first_used_at") or now,
            "last_used_at": now,
            "runs": int(previous.get("runs", 0)) + 1,
            "last_metrics": metrics_by_query.get(key, {}),
        }
    write_yaml(query_history_path(workspace), history)
    return history


def filter_unused_queries(workspace: Path, queries: list[str]) -> list[str]:
    history = load_query_history(workspace)
    used = set(history.get("queries", {}).keys())
    return [query for query in _dedupe(queries) if query_history_key(query) not in used]


def scopus_get(
    credentials: ScopusCredentials,
    params: dict[str, Any],
    *,
    opener: Callable[[Request], Any] | None = None,
) -> Any:
    query_string = urlencode(params)
    request = Request(
        f"{SCOPUS_SEARCH_URL}?{query_string}",
        headers={
            "X-ELS-APIKey": credentials.api_key,
            "Accept": "application/json",
            **({"X-ELS-Insttoken": credentials.inst_token} if credentials.inst_token else {}),
        },
        method="GET",
    )
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ExternalSearchError(f"Scopus request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise ExternalSearchError(f"Scopus request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ExternalSearchError("Scopus returned invalid JSON") from exc


def scopus_readiness(credentials: ScopusCredentials, *, opener: Callable[[Request], Any] | None = None) -> dict[str, Any]:
    data = scopus_get(credentials, {"query": "TITLE-ABS-KEY(research)", "count": 1, "view": "STANDARD"}, opener=opener)
    results = data.get("search-results") if isinstance(data, dict) else {}
    return {
        "version": 1,
        "provider": "scopus",
        "key_loaded": bool(credentials.api_key),
        "inst_token_loaded": bool(credentials.inst_token),
        "key_exposed": False,
        "api_reachable": True,
        "opensearch_total_results": results.get("opensearch:totalResults"),
    }


def scopus_search(
    workspace: Path,
    credentials: ScopusCredentials,
    *,
    query: str,
    count: int = 25,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    normalized_query = normalize_query_line(query)
    data = scopus_get(
        credentials,
        {"query": normalized_query, "count": max(1, min(count, 200)), "view": "STANDARD"},
        opener=opener,
    )
    output_dir = workspace / "outputs" / "external-search"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / f"scopus-response-{abs(hash(normalized_query))}.json"
    snapshot_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    results = data.get("search-results") if isinstance(data, dict) else {}
    entries = results.get("entry") if isinstance(results, dict) else []
    metrics = {
        "query": normalized_query,
        "processed": len(entries) if isinstance(entries, list) else 0,
        "saved": 0,
        "no_results": not entries,
        "snapshot_path": str(snapshot_path),
    }
    if metrics["no_results"]:
        no_results_path = output_dir / "scopus-no-results.yaml"
        current = read_yaml(no_results_path) if no_results_path.exists() else {"version": 1, "queries": []}
        current.setdefault("queries", []).append(normalized_query)
        write_yaml(no_results_path, current)
    record_queries_used(workspace, [normalized_query], [metrics])
    return {"version": 1, "provider": "scopus", "metrics": metrics, "snapshot_path": str(snapshot_path)}
