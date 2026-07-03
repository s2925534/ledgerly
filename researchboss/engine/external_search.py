from __future__ import annotations

import json
import os
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.ai import load_dotenv_values


SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
QUOTE_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
QUERY_STRATEGIES = {"broad", "balanced", "strict"}
DOMAIN_TERM_MAP = {
    "container": ["container logistics", "container terminal", "container operations", "container flow"],
    "port": ["port logistics", "maritime logistics", "terminal operations", "smart port"],
    "zotero": ["reference management", "research workflow", "citation management"],
    "evidence": ["evidence tracking", "claim validation", "source validation"],
    "interoperability": ["data interoperability", "semantic interoperability", "data harmonization"],
    "prediction": ["predictive analytics", "forecasting", "prediction model"],
    "scoring": ["scoring model", "performance evaluation", "KPI"],
    "routing": ["routing optimization", "resource allocation", "scheduling"],
    "traceability": ["traceability", "event tracking", "supply chain visibility"],
    "digital": ["digital twin", "IoT", "cyber physical system", "blockchain"],
    "ai": ["artificial intelligence", "machine learning", "deep learning"],
    "sustainability": ["sustainability", "carbon efficiency", "circular economy"],
}
FALLBACK_ANCHORS = ["research workflow", "evidence tracking", "source validation", "citation management"]
FALLBACK_METHODS = ["performance evaluation", "decision support", "quality assessment", "validation"]
FALLBACK_QUALIFIERS = ["systematic review", "case study", "framework", "methodology"]


@dataclass(frozen=True)
class ScopusCredentials:
    api_key: str
    inst_token: str | None = None


class ExternalSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchThresholds:
    min_citations: int = 0
    year_from: int | None = None
    year_to: int | None = None
    open_access_only: bool = False
    max_results_per_query: int = 25
    low_result_threshold: int = 3

    @classmethod
    def from_options(
        cls,
        *,
        min_citations: int = 0,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
        max_results_per_query: int = 25,
        low_result_threshold: int = 3,
    ) -> "SearchThresholds":
        return cls(
            min_citations=max(0, min_citations),
            year_from=year_from,
            year_to=year_to,
            open_access_only=open_access_only,
            max_results_per_query=max(1, min(max_results_per_query, 200)),
            low_result_threshold=max(0, low_result_threshold),
        )


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


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for record in records:
        query = normalize_query_line(str(record.get("query") or ""))
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        out.append({**record, "query": query})
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


def _research_question_records(workspace: Path) -> list[dict[str, Any]]:
    records = []
    for path, key in (
        (workspace / "research-questions.yaml", "research_questions"),
        (workspace / "research-question-candidates.yaml", "candidates"),
    ):
        data = read_yaml(path)
        for index, item in enumerate(data.get(key, []), start=1):
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "")
            rq_id = str(item.get("id") or item.get("rq_id") or f"{key}-{index}")
            records.append(
                {
                    "id": rq_id,
                    "question": question,
                    "status": item.get("status") or ("candidate" if key == "candidates" else "approved"),
                    "terms": set(re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", question.lower())),
                }
            )
    return records


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


def _expanded_terms_from_context(text: str) -> list[str]:
    text_lower = text.lower()
    terms = []
    for marker, values in DOMAIN_TERM_MAP.items():
        if marker in text_lower or any(value.lower() in text_lower for value in values):
            terms.extend(values)
    terms.extend(_terms_from_context(text))
    return _dedupe(terms)


def _linked_rqs_for_query(query: str, rq_records: list[dict[str, Any]]) -> list[str]:
    query_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", query.lower()))
    linked = []
    for rq in rq_records:
        overlap = query_terms.intersection(rq.get("terms") or set())
        if len(overlap) >= 1:
            linked.append(str(rq["id"]))
    return linked


def _query_group_from_heading(line: str) -> str | None:
    cleaned = normalize_query_line(line).strip(":- ")
    if not cleaned:
        return None
    if cleaned.lower().startswith("search parameters"):
        cleaned = re.sub(r"^search parameters\s*[-:–—]?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or None


def parse_legacy_params_file(path: Path) -> list[dict[str, Any]]:
    records = []
    current_group: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = normalize_query_line(raw)
        if not line:
            continue
        lower = line.lower()
        looks_like_query = '"' in line or " and " in lower or " or " in lower or "title-abs-key" in lower
        if lower.startswith("search parameters") or (line.endswith(":") and not looks_like_query):
            current_group = _query_group_from_heading(line)
            continue
        if looks_like_query:
            records.append(
                {
                    "query": line,
                    "source": "legacy_params_file",
                    "source_path": str(path),
                    "group_label": current_group,
                    "strategy": "imported",
                }
            )
    return _dedupe_records(records)


def _generated_query_records(
    workspace: Path,
    *,
    max_queries: int,
    strategy: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strategy = strategy.lower().strip()
    if strategy not in QUERY_STRATEGIES:
        raise ExternalSearchError(f"Unsupported query strategy: {strategy}")
    terms = _expanded_terms_from_context(_context_text(workspace))
    anchor_terms = [
        term
        for term in terms
        if any(marker in term for marker in ("port", "container", "research", "evidence", "source", "citation"))
    ] or terms[:4] or FALLBACK_ANCHORS
    method_terms = [term for term in terms if term not in anchor_terms] or FALLBACK_METHODS
    qualifier_terms = [term for term in method_terms if term not in FALLBACK_METHODS] or FALLBACK_QUALIFIERS

    queries = []
    if strategy == "broad":
        for anchor, method in product(anchor_terms[:8], method_terms[:10]):
            if anchor != method:
                queries.append(f"{_quote(anchor)} AND {_quote(method)}")
    elif strategy == "strict":
        for anchor, method, qualifier in product(anchor_terms[:5], method_terms[:8], qualifier_terms[:6]):
            if len({anchor, method, qualifier}) == 3:
                queries.append(f"{_quote(anchor)} AND {_quote(method)} AND {_quote(qualifier)}")
    else:
        for anchor, method in product(anchor_terms[:6], method_terms[:8]):
            if anchor != method:
                queries.append(f"{_quote(anchor)} AND {_quote(method)}")
        for anchor, method, qualifier in product(anchor_terms[:4], method_terms[:6], FALLBACK_QUALIFIERS[:3]):
            if len({anchor, method, qualifier}) == 3:
                queries.append(f"{_quote(anchor)} AND {_quote(method)} AND {_quote(qualifier)}")

    records = [
        {
            "query": query,
            "source": "research_context_and_research_questions",
            "group_label": f"generated:{strategy}",
            "strategy": strategy,
        }
        for query in _dedupe(queries)
    ][: max(1, max_queries)]
    return records, {
        "strategy": strategy,
        "anchors": anchor_terms[:8],
        "methods": method_terms[:10],
        "qualifiers": qualifier_terms[:8],
    }


def generate_search_query_plan(
    workspace: Path,
    *,
    max_queries: int = 20,
    strategy: str = "balanced",
    params_file: Path | None = None,
) -> dict[str, Any]:
    generated_records, term_metadata = _generated_query_records(workspace, max_queries=max_queries, strategy=strategy)
    imported_records = parse_legacy_params_file(params_file) if params_file else []
    rq_records = _research_question_records(workspace)
    query_records = _dedupe_records([*imported_records, *generated_records])[: max(1, max_queries)]
    query_records = [
        {
            **record,
            "linked_research_questions": _linked_rqs_for_query(str(record.get("query") or ""), rq_records),
            "external_search_performed": False,
        }
        for record in query_records
    ]
    queries = [record["query"] for record in query_records]
    plan = {
        "version": 2,
        "source": "legacy_params_file_and_research_context" if imported_records else "research_context_and_research_questions",
        "external_search_performed": False,
        "strategy": strategy,
        "term_metadata": term_metadata,
        "imported_query_count": len(imported_records),
        "generated_query_count": len(generated_records),
        "queries": queries,
        "query_records": query_records,
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


def external_candidate_register_path(workspace: Path) -> Path:
    return workspace / "outputs" / "recommendations" / "external-paper-candidates.yaml"


def query_validation_path(workspace: Path) -> Path:
    return workspace / "outputs" / "validation" / "external-search-query-validation.yaml"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _year_from_entry(entry: dict[str, Any]) -> int | None:
    cover_date = str(entry.get("prism:coverDate") or entry.get("coverDate") or "")
    match = re.search(r"\b(19|20)\d{2}\b", cover_date)
    return int(match.group(0)) if match else None


def _truthy_open_access(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "open", "openaccess"}


def _authors_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    authors = entry.get("author")
    if not isinstance(authors, list):
        return []
    out = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        preferred = author.get("preferred-name")
        preferred = preferred if isinstance(preferred, dict) else {}
        out.append(
            {
                "name": author.get("authname") or author.get("ce:indexed-name") or preferred.get("surname"),
                "authid": author.get("authid"),
                "affiliation_id": author.get("afid"),
            }
        )
    return out


def _links_from_entry(entry: dict[str, Any]) -> list[dict[str, str]]:
    links = entry.get("link")
    if not isinstance(links, list):
        return []
    out = []
    for link in links:
        if isinstance(link, dict) and link.get("@href"):
            out.append({"ref": str(link.get("@ref") or ""), "href": str(link["@href"])})
    return out


def full_text_availability(entry: dict[str, Any]) -> dict[str, Any]:
    links = _links_from_entry(entry)
    doi = entry.get("prism:doi") or entry.get("doi")
    open_access = _truthy_open_access(entry.get("openaccess") or entry.get("openaccessFlag"))
    has_full_text_link = any("scopus" not in link["href"].lower() for link in links)
    return {
        "open_access_flag": open_access,
        "doi_present": bool(doi),
        "link_count": len(links),
        "possible_full_text_link": has_full_text_link,
        "full_text_retrieved": False,
        "notes": "Availability is inferred from metadata only; ResearchBoss does not download or scrape full text here.",
    }


def score_scopus_entry(entry: dict[str, Any], *, current_year: int | None = None) -> dict[str, Any]:
    current_year = current_year or datetime.now(timezone.utc).year
    citation_count = _safe_int(entry.get("citedby-count"))
    year = _year_from_entry(entry)
    doi = entry.get("prism:doi") or entry.get("doi")
    eid = entry.get("eid")
    pii = entry.get("pii")
    title = entry.get("dc:title") or entry.get("title") or "Untitled"
    source_title = entry.get("prism:publicationName") or entry.get("source-title")
    document_type = entry.get("subtypeDescription") or entry.get("subtype")
    open_access = _truthy_open_access(entry.get("openaccess") or entry.get("openaccessFlag"))
    authors = _authors_from_entry(entry)
    author_ids = [author["authid"] for author in authors if author.get("authid")]

    citation_score = min(40, citation_count // 5)
    recency_score = 0
    if year:
        age = max(0, current_year - year)
        recency_score = max(0, 20 - min(age, 20))
    identifier_score = 5 * sum(1 for value in (doi, eid, pii) if value)
    source_score = 10 if source_title else 0
    author_score = min(10, len(author_ids) * 2)
    open_access_score = 5 if open_access else 0
    score = min(100, citation_score + recency_score + identifier_score + source_score + author_score + open_access_score)

    reasons = []
    if citation_count:
        reasons.append(f"{citation_count} citations")
    if year:
        reasons.append(f"published in {year}")
    if source_title:
        reasons.append("source title available")
    if author_ids:
        reasons.append("indexed author IDs available")
    if doi:
        reasons.append("DOI available")
    if open_access:
        reasons.append("open-access flag present")

    return {
        "candidate_id": external_candidate_id(entry),
        "title": str(title),
        "year": year,
        "citation_count": citation_count,
        "source_title": source_title,
        "document_type": document_type,
        "doi": doi,
        "eid": eid,
        "pii": pii,
        "open_access": open_access,
        "authors": authors,
        "quality_score": score,
        "quality_reasons": reasons,
        "full_text_availability": full_text_availability(entry),
        "metadata_only": True,
        "review_status": "external_candidate",
    }


def external_candidate_id(entry: dict[str, Any]) -> str:
    basis = "|".join(
        str(entry.get(key) or "")
        for key in ("eid", "prism:doi", "doi", "dc:title", "prism:coverDate")
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    return f"ext-scopus-{digest}"


def candidate_passes_thresholds(candidate: dict[str, Any], thresholds: SearchThresholds) -> bool:
    if int(candidate.get("citation_count") or 0) < thresholds.min_citations:
        return False
    year = candidate.get("year")
    if thresholds.year_from is not None and (not year or int(year) < thresholds.year_from):
        return False
    if thresholds.year_to is not None and (not year or int(year) > thresholds.year_to):
        return False
    if thresholds.open_access_only and not candidate.get("open_access"):
        return False
    return True


def score_scopus_entries(entries: list[dict[str, Any]], thresholds: SearchThresholds) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scored = [score_scopus_entry(entry) for entry in entries if isinstance(entry, dict)]
    accepted = [candidate for candidate in scored if candidate_passes_thresholds(candidate, thresholds)]
    accepted.sort(key=lambda item: (-int(item.get("quality_score") or 0), -int(item.get("citation_count") or 0), str(item.get("title") or "")))
    skipped = [candidate for candidate in scored if not candidate_passes_thresholds(candidate, thresholds)]
    return accepted, skipped


def _keyword_coverage(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", query)]
    title_text = " ".join(str(candidate.get("title") or "").lower() for candidate in candidates)
    covered = sorted({term for term in terms if term in title_text})
    missing = sorted({term for term in terms if term not in title_text})
    return {
        "terms": sorted(set(terms)),
        "covered_terms": covered,
        "missing_terms": missing,
        "coverage_ratio": round(len(covered) / len(set(terms)), 3) if terms else 0,
    }


def query_refinement_suggestions(query: str, candidates: list[dict[str, Any]], *, no_results: bool) -> list[str]:
    suggestions = []
    normalized = normalize_query_line(query)
    coverage = _keyword_coverage(normalized, candidates)
    if no_results:
        suggestions.append("Broaden the query by removing the least essential quoted term.")
        suggestions.append("Try synonyms from approved research questions or accepted-source keywords.")
    if coverage["missing_terms"]:
        suggestions.append(f"Review missing title terms: {', '.join(coverage['missing_terms'][:5])}.")
    if candidates and not any(candidate.get("open_access") for candidate in candidates):
        suggestions.append("Consider a separate open-access-focused search if full text is required.")
    return suggestions


def query_validation_report(
    *,
    query: str,
    entries: list[dict[str, Any]],
    accepted_candidates: list[dict[str, Any]],
    skipped_candidates: list[dict[str, Any]],
    thresholds: SearchThresholds,
) -> dict[str, Any]:
    processed = len(entries)
    accepted = len(accepted_candidates)
    duplicate_ids = processed - len({external_candidate_id(entry) for entry in entries if isinstance(entry, dict)})
    no_results = processed == 0
    low_results = processed <= thresholds.low_result_threshold
    return {
        "query": normalize_query_line(query),
        "processed": processed,
        "accepted_candidates": accepted,
        "skipped_candidates": len(skipped_candidates),
        "duplicate_rate": round(duplicate_ids / processed, 3) if processed else 0,
        "threshold_pass_rate": round(accepted / processed, 3) if processed else 0,
        "keyword_coverage": _keyword_coverage(query, accepted_candidates),
        "no_results": no_results,
        "low_results": low_results,
        "refinement_suggestions": query_refinement_suggestions(query, accepted_candidates, no_results=no_results),
        "thresholds": {
            "min_citations": thresholds.min_citations,
            "year_from": thresholds.year_from,
            "year_to": thresholds.year_to,
            "open_access_only": thresholds.open_access_only,
            "max_results_per_query": thresholds.max_results_per_query,
            "low_result_threshold": thresholds.low_result_threshold,
        },
    }


def update_external_candidate_register(
    workspace: Path,
    *,
    provider: str,
    query: str,
    candidates: list[dict[str, Any]],
    skipped_candidates: list[dict[str, Any]],
    validation: dict[str, Any],
    snapshot_path: str,
) -> dict[str, Any]:
    path = external_candidate_register_path(workspace)
    register = read_yaml(path) if path.exists() else {"version": 1, "candidates": [], "runs": []}
    existing = {
        str(candidate.get("candidate_id")): candidate
        for candidate in register.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }
    now = datetime.now(timezone.utc).isoformat()
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        previous = existing.get(candidate_id, {})
        existing[candidate_id] = {
            **previous,
            **candidate,
            "provider": provider,
            "first_seen_at": previous.get("first_seen_at") or now,
            "last_seen_at": now,
            "queries": _dedupe([*(previous.get("queries") or []), query]),
        }
    register["candidates"] = sorted(existing.values(), key=lambda item: (-int(item.get("quality_score") or 0), str(item.get("title") or "")))
    register.setdefault("runs", []).append(
        {
            "provider": provider,
            "query": normalize_query_line(query),
            "created_at": now,
            "snapshot_path": snapshot_path,
            "candidate_count": len(candidates),
            "skipped_count": len(skipped_candidates),
            "no_results": validation["no_results"],
            "low_results": validation["low_results"],
        }
    )
    write_yaml(path, register)
    return register


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
    thresholds: SearchThresholds | None = None,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    normalized_query = normalize_query_line(query)
    thresholds = thresholds or SearchThresholds.from_options(max_results_per_query=count)
    data = scopus_get(
        credentials,
        {"query": normalized_query, "count": thresholds.max_results_per_query, "view": "STANDARD"},
        opener=opener,
    )
    output_dir = workspace / "outputs" / "external-search"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_digest = hashlib.sha256(f"{normalized_query}|{datetime.now(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()[:16]
    snapshot_path = output_dir / f"scopus-response-{snapshot_digest}.json"
    snapshot_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    results = data.get("search-results") if isinstance(data, dict) else {}
    entries = results.get("entry") if isinstance(results, dict) else []
    entries = entries if isinstance(entries, list) else []
    accepted_candidates, skipped_candidates = score_scopus_entries(entries, thresholds)
    validation = query_validation_report(
        query=normalized_query,
        entries=entries,
        accepted_candidates=accepted_candidates,
        skipped_candidates=skipped_candidates,
        thresholds=thresholds,
    )
    write_yaml(query_validation_path(workspace), {"version": 1, "provider": "scopus", "validation": validation})
    register = update_external_candidate_register(
        workspace,
        provider="scopus",
        query=normalized_query,
        candidates=accepted_candidates,
        skipped_candidates=skipped_candidates,
        validation=validation,
        snapshot_path=str(snapshot_path),
    )
    metrics = {
        "query": normalized_query,
        "processed": len(entries),
        "candidate_count": len(accepted_candidates),
        "skipped_count": len(skipped_candidates),
        "no_results": validation["no_results"],
        "low_results": validation["low_results"],
        "snapshot_path": str(snapshot_path),
        "candidate_register_path": str(external_candidate_register_path(workspace)),
        "query_validation_path": str(query_validation_path(workspace)),
    }
    if metrics["no_results"]:
        no_results_path = output_dir / "scopus-no-results.yaml"
        current = read_yaml(no_results_path) if no_results_path.exists() else {"version": 1, "queries": []}
        current.setdefault("queries", []).append(
            {
                "query": normalized_query,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "refinement_suggestions": validation["refinement_suggestions"],
            }
        )
        write_yaml(no_results_path, current)
    if metrics["low_results"] and not metrics["no_results"]:
        low_results_path = output_dir / "scopus-low-results.yaml"
        current = read_yaml(low_results_path) if low_results_path.exists() else {"version": 1, "queries": []}
        current.setdefault("queries", []).append(
            {
                "query": normalized_query,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "processed": metrics["processed"],
                "refinement_suggestions": validation["refinement_suggestions"],
            }
        )
        write_yaml(low_results_path, current)
    record_queries_used(workspace, [normalized_query], [metrics])
    return {
        "version": 1,
        "provider": "scopus",
        "metrics": metrics,
        "snapshot_path": str(snapshot_path),
        "validation": validation,
        "candidate_count_total": len(register.get("candidates", [])),
    }
