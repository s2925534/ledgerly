from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ledgerly.core.constants import WORKSPACE_FILES
from ledgerly.core.runlog import utc_now_iso
from ledgerly.core.yamlio import read_yaml, write_yaml
from ledgerly.engine.grounding import citation_instruction, validate_grounding


OPENAI_API_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class OpenAiCredentials:
    api_key: str


class OpenAiError(RuntimeError):
    pass


def load_dotenv_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def openai_credentials(workspace: Path | None = None) -> OpenAiCredentials:
    env_values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        env_values = {**env_values, **load_dotenv_values(workspace / ".env")}
    api_key = os.environ.get("OPENAI_API_KEY") or env_values.get("OPENAI_API_KEY") or ""
    if not api_key:
        raise OpenAiError("Missing OPENAI_API_KEY")
    return OpenAiCredentials(api_key=api_key)


def workspace_ai_settings(workspace: Path) -> dict[str, Any]:
    settings = read_yaml(workspace / "app-settings.local.yaml")
    ai_settings = settings.get("ai")
    return ai_settings if isinstance(ai_settings, dict) else {}


def require_ai_flag(ai: bool) -> None:
    if not ai:
        raise OpenAiError("Pass --ai to explicitly allow this OpenAI action.")


def require_full_file_ai_opt_in(*, ai: bool, full_file: bool) -> None:
    require_ai_flag(ai)
    if not full_file:
        raise OpenAiError("Pass --full-file-ai to explicitly allow sending a whole file to an AI provider.")


def require_directory_ai_opt_in(*, ai: bool, directory: bool) -> None:
    require_ai_flag(ai)
    if not directory:
        raise OpenAiError("Pass --directory-ai to explicitly allow folder-level AI context.")


def require_full_target_document_ai_opt_in(*, ai: bool, full_target_document: bool) -> None:
    require_ai_flag(ai)
    if not full_target_document:
        raise OpenAiError("Pass --full-target-document-ai to explicitly allow sending a whole target document to an AI provider.")


def require_full_source_document_ai_opt_in(*, ai: bool, full_source_document: bool) -> None:
    require_ai_flag(ai)
    if not full_source_document:
        raise OpenAiError("Pass --full-source-document-ai to explicitly allow sending whole backing/source documents to an AI provider.")


def openai_get(
    path: str,
    credentials: OpenAiCredentials,
    *,
    opener: Callable[[Request], Any] | None = None,
    base_url: str = OPENAI_API_BASE_URL,
) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {credentials.api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OpenAiError(f"OpenAI request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise OpenAiError(f"OpenAI request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAiError("OpenAI returned invalid JSON") from exc


def openai_post(
    path: str,
    credentials: OpenAiCredentials,
    body: dict[str, Any],
    *,
    opener: Callable[[Request], Any] | None = None,
    base_url: str = OPENAI_API_BASE_URL,
) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {credentials.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    fetch = opener or urlopen
    try:
        with fetch(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OpenAiError(f"OpenAI request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise OpenAiError(f"OpenAI request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAiError("OpenAI returned invalid JSON") from exc


def default_openai_model(workspace: Path) -> str:
    ai_settings = workspace_ai_settings(workspace)
    providers = ai_settings.get("providers") if isinstance(ai_settings.get("providers"), dict) else {}
    openai_settings = providers.get("openai") if isinstance(providers.get("openai"), dict) else {}
    return str(openai_settings.get("default_model") or "gpt-4o-mini")


def extract_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text

    parts: list[str] = []
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts)


def openai_readiness(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    live: bool = False,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    ai_settings = workspace_ai_settings(workspace)
    openai_settings = {}
    providers = ai_settings.get("providers") if isinstance(ai_settings.get("providers"), dict) else {}
    if isinstance(providers.get("openai"), dict):
        openai_settings = providers["openai"]

    report: dict[str, Any] = {
        "version": 1,
        "provider": "openai",
        "key_loaded": bool(credentials.api_key),
        "key_exposed": False,
        "workspace_ai_enabled": bool(ai_settings.get("enabled")),
        "openai_provider_enabled": bool(openai_settings.get("enabled")),
        "default_model": openai_settings.get("default_model"),
        "live_request_performed": False,
        "policy": "explicit_ai_flag_required",
    }

    if live:
        data = openai_get("models", credentials, opener=opener)
        models = data.get("data") if isinstance(data, dict) else []
        report["live_request_performed"] = True
        report["api_reachable"] = True
        report["model_count"] = len(models) if isinstance(models, list) else 0

    return report


def _safe_source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = [
        "source_id",
        "provider",
        "file_name",
        "file_ext",
        "status",
        "content_hash",
        "title",
        "creators",
        "year",
        "doi",
        "item_type",
        "publication_title",
        "tags",
        "notes",
        "zotero_item_key",
        "zotero_storage_key",
        "has_zotero_fulltext_cache",
    ]
    return {field: source.get(field) for field in allowed_fields if field in source}


def _read_excerpt(path: Path, max_chars: int) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _workspace_topic_query(workspace: Path) -> str | None:
    """The workspace's stated research topic, used as the relevance query for
    AI operations with no more specific query material of their own (e.g. a
    general corpus review, as opposed to a specific research-question
    assessment which has its own question text to use instead).
    """
    topic = read_yaml(workspace / "research-context.yaml").get("project", {}).get("topic")
    return topic.strip() if isinstance(topic, str) and topic.strip() else None


def _research_questions_query(research_questions: dict[str, Any]) -> str | None:
    """Joined question text (all groups) to use as the relevance query for
    novelty/RQ-assessment operations, which have research-question text
    available as strictly more specific query material than the workspace
    topic alone.
    """
    texts = [
        str(item.get("question"))
        for items in research_questions.values()
        for item in items
        if isinstance(item, dict) and item.get("question")
    ]
    return " ".join(texts).strip() or None


def _source_converted_relative_path(source: dict[str, Any], workspace: Path) -> str | None:
    conversion = source.get("conversion") if isinstance(source.get("conversion"), dict) else {}
    output_path = conversion.get("output_path")
    if conversion.get("status") not in {"converted", "skipped_unchanged"} or not output_path:
        return None
    converted_path = Path(str(output_path))
    if not converted_path.is_file() or not converted_path.resolve().is_relative_to(workspace.resolve()):
        return None
    return str(converted_path.relative_to(workspace))


def _rank_sources_by_relevance(
    workspace: Path, sources: list[dict[str, Any]], query: str, max_sources: int
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Order `sources` by FTS5 relevance to `query`, most relevant first, with
    sources that have no converted text or no FTS match falling back to their
    original order at the end. Returns the reordered list (capped to
    `max_sources`) and the `{relative_path: excerpt}` map for entries that
    matched, so the caller can reuse the already-computed relevant excerpt
    instead of re-deriving it.
    """
    from ledgerly.engine.database import relevant_source_excerpts

    relevance = relevant_source_excerpts(workspace, query, limit=max_sources)
    if not relevance:
        return sources[:max_sources], {}

    by_relative_path = {}
    for source in sources:
        relative = _source_converted_relative_path(source, workspace)
        if relative:
            by_relative_path.setdefault(relative, source)

    ranked: list[dict[str, Any]] = []
    seen_ids = set()
    for relative in relevance:
        source = by_relative_path.get(relative)
        if source is None or source.get("source_id") in seen_ids:
            continue
        ranked.append(source)
        seen_ids.add(source.get("source_id"))
        if len(ranked) >= max_sources:
            break
    if len(ranked) < max_sources:
        for source in sources:
            if source.get("source_id") in seen_ids:
                continue
            ranked.append(source)
            seen_ids.add(source.get("source_id"))
            if len(ranked) >= max_sources:
                break
    return ranked, relevance


def build_safe_context(
    workspace: Path,
    *,
    source_status: str = "accepted",
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    query: str | None = None,
) -> dict[str, Any]:
    """Build the excerpt-only, original-file-excluded context every AI route sends.

    When `query` is given, accepted sources are ranked and excerpted by FTS5
    relevance (Phase 7's `fts_index_search`, keyword-relevant retrieval) via
    `relevant_source_excerpts`, instead of an arbitrary from-the-start
    truncation of whichever sources happen to be first in the register — both
    an efficiency win (less irrelevant content sent per request) and a
    grounding-precision win (the included text is actually about what the
    request is asking, per AGENTS.md Core Rule item 6). Falls back to today's
    from-the-start behavior per source whenever no query is given, no SQLite
    index has been built yet (`db sync`), or a given source has no FTS match
    — this must keep working with zero SQLite configured, since SQLite stays
    an optional cache layer, never a hard requirement (AGENTS.md).
    """
    if max_sources < 1:
        raise OpenAiError("max_sources must be at least 1")
    if max_excerpt_chars < 0:
        raise OpenAiError("max_excerpt_chars cannot be negative")

    register = read_yaml(workspace / "source-register.yaml")
    sources = [source for source in register.get("sources", []) if isinstance(source, dict)]
    eligible = [source for source in sources if source.get("status") == source_status]

    relevant_excerpts: dict[str, str] = {}
    if query and query.strip():
        selected, relevant_excerpts = _rank_sources_by_relevance(workspace, eligible, query, max_sources)
    else:
        selected = eligible[:max_sources]

    entries = []
    for source in selected:
        entry: dict[str, Any] = {
            "metadata": _safe_source_metadata(source),
            "original_file_excluded": True,
            "full_document_excluded": True,
            "excerpt_source": None,
            "excerpt": None,
            "excerpt_truncated": False,
            "excerpt_selection": "none",
        }
        if max_excerpt_chars > 0:
            relative = _source_converted_relative_path(source, workspace)
            if relative and relative in relevant_excerpts:
                entry["excerpt_source"] = relative
                entry["excerpt"] = relevant_excerpts[relative]
                entry["excerpt_truncated"] = True
                entry["excerpt_selection"] = "query_relevant"
            elif relative:
                excerpt, truncated = _read_excerpt(workspace / relative, max_excerpt_chars)
                entry["excerpt_source"] = relative
                entry["excerpt"] = excerpt
                entry["excerpt_truncated"] = truncated
                entry["excerpt_selection"] = "from_start"
        entries.append(entry)

    return {
        "version": 1,
        "purpose": "safe_ai_context_preview",
        "policy": {
            "requires_explicit_ai_flag": True,
            "original_files_excluded": True,
            "full_documents_excluded": True,
            "whole_csv_excluded": True,
            "whole_sqlite_excluded": True,
            "zotero_directory_no_write_boundary": True,
        },
        "limits": {
            "source_status": source_status,
            "max_sources": max_sources,
            "max_excerpt_chars": max_excerpt_chars,
        },
        "query": query,
        "has_evidence": any(entry.get("excerpt") for entry in entries),
        "sources": entries,
    }


def _insufficient_evidence_response(kind: str, context: dict[str, Any]) -> dict[str, Any]:
    """The required, valid, successful response when the safe context has no
    usable excerpt to ground an answer in (AGENTS.md Core Rule item 3:
    "insufficient evidence" is a required output, never something to route
    around). Never calls the AI provider — there is deterministically
    nothing to send it that could produce a grounded answer, so skipping the
    call is both more honest and saves the API cost.
    """
    return {
        "version": 1,
        "kind": kind,
        "provider": "openai",
        "model": None,
        "ai_used": False,
        "requires_user_review": False,
        "insufficient_evidence": True,
        "insufficient_evidence_reason": (
            "No accepted source has a usable converted-text excerpt in the safe context — "
            "nothing to ground an AI response in. Accept and convert more sources, or check "
            "conversion status, before retrying."
        ),
        "safe_context_policy": context["policy"],
        "limits": context["limits"],
        "source_count": len(context["sources"]),
        "response_id": None,
        "grounding": None,
    }


def record_ai_usage(workspace: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Append one entry to the AI-usage audit ledger (TODO.md Phase 32) --
    a single place to answer "when was AI used on this workspace, and was
    it grounded", regardless of whether the individual feature happens to
    persist its own side-effect file (only novelty assessments do today).
    Records every invocation, including ones that refused via
    `insufficient_evidence`, since "AI was requested but correctly refused"
    is itself audit-worthy. Returns `report` unchanged, so call sites can
    write `return record_ai_usage(workspace, report)`.
    """
    ledger_path = workspace / WORKSPACE_FILES.ai_usage_ledger
    # Tolerant of a missing file (unlike other ledgers here) since this
    # function now runs on every AI call unconditionally, including for
    # workspaces created before this ledger existed -- a hard crash here
    # would break every AI feature after an upgrade, not just one command.
    ledger = read_yaml(ledger_path) if ledger_path.exists() else {}
    entries = list(ledger.get("entries", []))
    grounding = report.get("grounding")
    entries.append(
        {
            "id": f"ai-usage-{len(entries) + 1:03d}",
            "timestamp": utc_now_iso(),
            "kind": report.get("kind"),
            "ai_used": report.get("ai_used", False),
            "insufficient_evidence": report.get("insufficient_evidence", False),
            "model": report.get("model"),
            "response_id": report.get("response_id"),
            "requires_user_review": report.get("requires_user_review"),
            "grounding_fully_grounded": grounding.get("fully_grounded") if isinstance(grounding, dict) else None,
        }
    )
    ledger["version"] = ledger.get("version", 1)
    ledger["entries"] = entries
    write_yaml(ledger_path, ledger)
    return report


def list_ai_usage(workspace: Path) -> list[dict[str, Any]]:
    """The full AI-usage audit trail (`record_ai_usage`), oldest first --
    the single-place answer to "when was AI used on this workspace, and was
    it grounded" (TODO.md Phase 32). Read-only; never itself a place AI
    usage is recorded from.
    """
    ledger_path = workspace / WORKSPACE_FILES.ai_usage_ledger
    if not ledger_path.exists():
        return []
    return list(read_yaml(ledger_path).get("entries", []))


def _review_prompt(context: dict[str, Any]) -> str:
    return (
        "You are assisting with a local-first, evidence-first research workspace.\n"
        "Use only the provided safe context. Do not infer from unavailable full documents. "
        "Do not claim novelty or evidence strength certainty. Return concise markdown with sections: "
        "Scope, Useful Signals, Evidence Gaps, Source Follow-up, Human Review Required.\n\n"
        f"{citation_instruction()}\n\n"
        f"Safe context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def ai_assisted_review(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    context = build_safe_context(
        workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=_workspace_topic_query(workspace)
    )
    if not context["has_evidence"]:
        return record_ai_usage(workspace, _insufficient_evidence_response("ai_assisted_review", context))
    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {
            "model": model,
            "input": _review_prompt(context),
        },
        opener=opener,
    )
    review_text = extract_response_text(response)
    return record_ai_usage(
        workspace,
        {
            "version": 1,
            "kind": "ai_assisted_review",
            "provider": "openai",
            "model": model,
            "ai_used": True,
            "requires_user_review": True,
            "safe_context_policy": context["policy"],
            "limits": context["limits"],
            "source_count": len(context["sources"]),
            "response_id": response.get("id") if isinstance(response, dict) else None,
            "review": review_text,
            "grounding": validate_grounding(review_text, context=context),
        },
    )


def _novelty_prompt(context: dict[str, Any], research_questions: dict[str, Any]) -> str:
    return (
        "You are assisting with an AI-assisted novelty assessment for a local research workspace.\n"
        "Use only the safe context and research questions below. Do not claim that novelty is proven. "
        "Identify possible novelty signals, likely overlaps, missing evidence, and follow-up checks. "
        "Return concise markdown with sections: Assessment Boundary, Possible Novelty Signals, "
        "Likely Overlaps, Missing Evidence, Follow-up Checks, Human Review Required.\n\n"
        f"{citation_instruction()}\n\n"
        f"Research questions JSON:\n{json.dumps(research_questions, ensure_ascii=False, indent=2)}\n\n"
        f"Safe context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _append_novelty_assessment(workspace: Path, record: dict[str, Any]) -> None:
    ledger_path = workspace / "novelty-ledger.yaml"
    ledger = read_yaml(ledger_path)
    assessments = list(ledger.get("assessments", []))
    record = {"id": f"novelty-{len(assessments) + 1:03d}", **record}
    assessments.append(record)
    ledger["version"] = ledger.get("version", 1)
    ledger["assessments"] = assessments
    write_yaml(ledger_path, ledger)


def ai_novelty_assessment(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    research_questions = {
        "approved": read_yaml(workspace / "research-questions.yaml").get("research_questions", []),
        "candidates": read_yaml(workspace / "research-question-candidates.yaml").get("candidates", []),
    }
    query = _research_questions_query(research_questions) or _workspace_topic_query(workspace)
    context = build_safe_context(workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=query)
    if not context["has_evidence"]:
        report = _insufficient_evidence_response("ai_assisted_novelty_assessment", context)
        report["novelty_not_proven"] = True
        report["research_question_count"] = len(research_questions["approved"]) + len(research_questions["candidates"])
        return record_ai_usage(workspace, report)
    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {
            "model": model,
            "input": _novelty_prompt(context, research_questions),
        },
        opener=opener,
    )
    assessment_text = extract_response_text(response)
    report = {
        "version": 1,
        "kind": "ai_assisted_novelty_assessment",
        "provider": "openai",
        "model": model,
        "ai_used": True,
        "requires_user_review": True,
        "novelty_not_proven": True,
        "safe_context_policy": context["policy"],
        "limits": context["limits"],
        "source_count": len(context["sources"]),
        "research_question_count": len(research_questions["approved"]) + len(research_questions["candidates"]),
        "response_id": response.get("id") if isinstance(response, dict) else None,
        "assessment": assessment_text,
        "grounding": validate_grounding(assessment_text, context=context),
    }
    _append_novelty_assessment(
        workspace,
        {
            "kind": report["kind"],
            "provider": report["provider"],
            "model": report["model"],
            "response_id": report["response_id"],
            "requires_user_review": True,
            "novelty_not_proven": True,
            "source_count": report["source_count"],
            "research_question_count": report["research_question_count"],
            "assessment": assessment_text,
        },
    )
    return record_ai_usage(workspace, report)


def _rq_assessment_prompt(context: dict[str, Any], research_questions: dict[str, Any], rq_id: str | None) -> str:
    return (
        "You are assisting with research-question assessment for a local-first research workspace.\n"
        "Use only the provided research questions and safe context. Do not claim that novelty, usefulness, "
        "or evidence quality are proven. Assess likely strengths, weaknesses, scope risks, evidence fit, "
        "field usefulness signals, and follow-up revisions. Return concise markdown with one section per "
        "research question and a final Human Review Required section.\n\n"
        f"{citation_instruction()}\n\n"
        f"Requested research question id: {rq_id or 'all'}\n\n"
        f"Research questions JSON:\n{json.dumps(research_questions, ensure_ascii=False, indent=2)}\n\n"
        f"Safe context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _filter_research_questions(research_questions: dict[str, Any], rq_id: str | None) -> dict[str, Any]:
    if rq_id is None:
        return research_questions
    filtered: dict[str, Any] = {}
    matched = False
    for group, items in research_questions.items():
        group_items = [item for item in items if isinstance(item, dict) and item.get("id") == rq_id]
        if group_items:
            matched = True
        filtered[group] = group_items
    if not matched:
        raise OpenAiError(f"Unknown research question: {rq_id}")
    return filtered


def ai_research_question_assessment(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    rq_id: str | None = None,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    research_questions = {
        "approved": read_yaml(workspace / "research-questions.yaml").get("research_questions", []),
        "candidates": read_yaml(workspace / "research-question-candidates.yaml").get("candidates", []),
    }
    selected_questions = _filter_research_questions(research_questions, rq_id)
    question_count = sum(len(items) for items in selected_questions.values())
    query = _research_questions_query(selected_questions) or _workspace_topic_query(workspace)
    context = build_safe_context(workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=query)
    if not context["has_evidence"]:
        report = _insufficient_evidence_response("ai_research_question_assessment", context)
        report["novelty_not_proven"] = True
        report["research_question_count"] = question_count
        report["rq_id"] = rq_id
        return record_ai_usage(workspace, report)
    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {
            "model": model,
            "input": _rq_assessment_prompt(context, selected_questions, rq_id),
        },
        opener=opener,
    )
    assessment_text = extract_response_text(response)
    return record_ai_usage(
        workspace,
        {
            "version": 1,
            "kind": "ai_research_question_assessment",
            "provider": "openai",
            "model": model,
            "ai_used": True,
            "requires_user_review": True,
            "novelty_not_proven": True,
            "safe_context_policy": context["policy"],
            "limits": context["limits"],
            "source_count": len(context["sources"]),
            "research_question_count": question_count,
            "rq_id": rq_id,
            "response_id": response.get("id") if isinstance(response, dict) else None,
            "assessment": assessment_text,
            "grounding": validate_grounding(assessment_text, context=context),
        },
    )


AI_WORKSPACE_REPORTS = {
    "corpus_summary": {
        "title": "AI corpus summary",
        "sections": "Scope, Main Themes, Evidence Signals, Gaps, Human Review Required",
    },
    "claim_checking": {
        "title": "AI claim-checking assistance",
        "sections": "Claim Coverage, Supported Signals, Missing Evidence, Risky Claims, Human Review Required",
    },
    "citation_gaps": {
        "title": "AI citation gap recommendations",
        "sections": "Likely Citation Gaps, Candidate Source Links, Missing Source Types, Follow-up Checks, Human Review Required",
    },
    "artefact_cross_reference": {
        "title": "AI artefact cross-reference review",
        "sections": "Artefact Coverage, Source Links, Research Question Links, Evidence Gaps, Human Review Required",
    },
    "source_relevance": {
        "title": "AI source relevance recommendations",
        "sections": "Relevant Source Signals, Low-Relevance Risks, Suggested Review Tags, Follow-up Checks, Human Review Required",
    },
    "abstract_screening": {
        "title": "AI-assisted abstract screening",
        "sections": "Likely Relevant Abstracts, Low-Relevance Abstracts, Missing Metadata, Suggested Review Queue, Human Review Required",
    },
    "query_generation": {
        "title": "AI-assisted external search query generation and refinement",
        "sections": "Suggested Queries, Refinement Rationale, Excluded Unsafe Context, Search Budget Notes, Human Approval Required",
    },
    "candidate_validation": {
        "title": "AI-assisted paper relevance, research-question, idea, and novelty validation",
        "sections": "Candidate Relevance, Research Question Fit, Idea Validation Signals, Novelty Risks, Human Review Required",
    },
}


def _workspace_ai_payload(workspace: Path, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "safe_context": context,
        "research_questions": {
            "approved": read_yaml(workspace / "research-questions.yaml").get("research_questions", []),
            "candidates": read_yaml(workspace / "research-question-candidates.yaml").get("candidates", []),
        },
        "claims": read_yaml(workspace / "claims-ledger.yaml").get("claims", []),
        "artefacts": read_yaml(workspace / "artefact-registry.yaml").get("artefacts", []),
        "abstract_candidates": read_yaml(workspace / "outputs" / "recommendations" / "abstract-candidates.yaml")
        if (workspace / "outputs" / "recommendations" / "abstract-candidates.yaml").exists()
        else {"candidates": [], "filtered": [], "skipped": []},
        "external_candidates": read_yaml(workspace / "outputs" / "recommendations" / "external-paper-candidates.yaml")
        if (workspace / "outputs" / "recommendations" / "external-paper-candidates.yaml").exists()
        else {"candidates": []},
    }


def _payload_has_evidence(payload: dict[str, Any]) -> bool:
    """Whether `_workspace_ai_payload` has anything at all to ground a report
    in — not just source excerpts, since some report kinds (abstract
    screening, query generation, candidate validation) legitimately draw on
    abstract/external candidates rather than accepted-source text.
    """
    if payload["safe_context"]["has_evidence"]:
        return True
    if payload["claims"] or payload["artefacts"]:
        return True
    if payload["abstract_candidates"].get("candidates"):
        return True
    if payload["external_candidates"].get("candidates"):
        return True
    return False


def _workspace_report_prompt(kind: str, payload: dict[str, Any]) -> str:
    spec = AI_WORKSPACE_REPORTS[kind]
    return (
        f"You are assisting with {spec['title']} for a local-first, evidence-first research workspace.\n"
        "Use only the supplied safe context and workspace state. Do not claim certainty, do not modify statuses, "
        "and cite source IDs when referring to sources. Return concise markdown with sections: "
        f"{spec['sections']}.\n\n"
        f"{citation_instruction()}\n\n"
        f"Workspace payload JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def ai_workspace_report(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    kind: str,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    if kind not in AI_WORKSPACE_REPORTS:
        allowed = ", ".join(sorted(AI_WORKSPACE_REPORTS))
        raise OpenAiError(f"Invalid AI workspace report kind: {kind}. Expected one of: {allowed}")
    context = build_safe_context(
        workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=_workspace_topic_query(workspace)
    )
    payload = _workspace_ai_payload(workspace, context)
    if not _payload_has_evidence(payload):
        report = _insufficient_evidence_response(kind, context)
        report["status_changes_applied"] = False
        return record_ai_usage(workspace, report)
    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {
            "model": model,
            "input": _workspace_report_prompt(kind, payload),
        },
        opener=opener,
    )
    text = extract_response_text(response)
    return record_ai_usage(
        workspace,
        {
            "version": 1,
            "kind": kind,
            "provider": "openai",
            "model": model,
            "ai_used": True,
            "requires_user_review": True,
            "status_changes_applied": False,
            "safe_context_policy": context["policy"],
            "limits": context["limits"],
            "source_count": len(context["sources"]),
            "claim_count": len(payload["claims"]),
            "artefact_count": len(payload["artefacts"]),
            "abstract_candidate_count": len(payload["abstract_candidates"].get("candidates", [])),
            "external_candidate_count": len(payload["external_candidates"].get("candidates", [])),
            "research_question_count": len(payload["research_questions"]["approved"])
            + len(payload["research_questions"]["candidates"]),
            "response_id": response.get("id") if isinstance(response, dict) else None,
            "report": text,
            "grounding": validate_grounding(
                text, context=context, claims=payload["claims"], artefacts=payload["artefacts"]
            ),
        },
    )


def ai_citation_plan_review(
    workspace: Path,
    credentials: OpenAiCredentials,
    *,
    target_text: str,
    citation_plan: dict[str, Any],
    opener: Callable[[Request], Any] | None = None,
) -> dict[str, Any]:
    model = default_openai_model(workspace)
    prompt = (
        "You are assisting with citation insertion for a local-first, evidence-first research workspace.\n"
        "Use the supplied target document text and deterministic citation plan. Do not edit the document directly. "
        "Propose inline citation locations, link each insertion to evidence source IDs, explain confidence, and require human review.\n\n"
        f"{citation_instruction()}\n\n"
        f"Deterministic citation plan JSON:\n{json.dumps(citation_plan, ensure_ascii=False, indent=2)}\n\n"
        f"Target document text:\n{target_text}"
    )
    response = openai_post(
        "responses",
        credentials,
        {"model": model, "input": prompt},
        opener=opener,
    )
    recommendations_text = extract_response_text(response)
    plan_source_ids = [
        item.get("source_id") for item in citation_plan.get("insertions", []) if isinstance(item, dict)
    ]
    return record_ai_usage(
        workspace,
        {
            "kind": "ai_citation_plan_review",
            "provider": "openai",
            "model": model,
            "ai_used": True,
            "requires_user_review": True,
            "original_document_modified": False,
            "response_id": response.get("id") if isinstance(response, dict) else None,
            "recommendations": recommendations_text,
            "grounding": validate_grounding(recommendations_text, source_ids=plan_source_ids),
        },
    )


def _review_document_prompt(
    target_text: str,
    context: dict[str, Any],
    claims: list[dict[str, Any]],
    citation_plan: dict[str, Any] | None,
    notes: list[dict[str, Any]],
) -> str:
    return (
        "You are reviewing one working document for a local-first, evidence-first research workspace.\n"
        "Use only the supplied target document text, safe source context, claim ledger, citation plan, and notes "
        "below. Produce a structured review with sections: Strengths, Weaknesses, Unsupported Claims, Suggested "
        "Revisions, Human Review Required. Every factual point must cite a specific source/claim/note, or "
        "explicitly state that no supporting evidence exists in the corpus for that point -- never invent support. "
        "Do not edit the document directly; this is a report only.\n\n"
        f"{citation_instruction()}\n\n"
        f"Target document text:\n{target_text}\n\n"
        f"Safe context JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"Claim ledger JSON:\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
        "Citation plan JSON (null if none exists for this target):\n"
        f"{json.dumps(citation_plan, ensure_ascii=False, indent=2) if citation_plan else 'null'}\n\n"
        "Notes JSON (only kinds the user explicitly opted into for this run):\n"
        f"{json.dumps(notes, ensure_ascii=False, indent=2)}"
    )


def ai_review_document(
    workspace: Path,
    credentials: OpenAiCredentials,
    target: str,
    *,
    note_kinds: list[str] | None = None,
    max_sources: int = 10,
    max_excerpt_chars: int = 1200,
    opener: Callable[[Request], Any] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Structured AI review of a target working document against the full
    evidence base: accepted source excerpts, the claim ledger, this
    target's own citation plan (if one exists), and -- only for explicitly
    opted-in kinds -- Phase 25's personal notes/meeting-notes/transcripts
    store. Never modifies the target; always produces a report for human
    review, the same propose-only boundary every other `engine.ai`
    function uses (consistent with the document-vault snapshot-before-
    modify pattern, even though nothing here is actually modified).
    `note_kinds` is a per-kind opt-in, not one blanket "include notes"
    switch: a user may want source text and claims in AI context but not
    personal meeting notes, which can carry more sensitive material --
    mirrors `ai context-preview`'s boundary-drawing precedent.
    """
    from ledgerly.engine.citations import citation_plan_path
    from ledgerly.engine.claims import list_claims
    from ledgerly.engine.conversion import extract_text as extract_target_text
    from ledgerly.engine.document_targets import resolve_document_target
    from ledgerly.engine.notes import NOTE_KINDS, list_notes

    invalid_kinds = sorted(set(note_kinds or []) - NOTE_KINDS)
    if invalid_kinds:
        raise OpenAiError(f"Invalid note kind(s): {', '.join(invalid_kinds)}. Expected one of: {', '.join(sorted(NOTE_KINDS))}")

    resolved = resolve_document_target(workspace, target, cwd=cwd)
    target_text = extract_target_text(resolved.path)

    context = build_safe_context(
        workspace, max_sources=max_sources, max_excerpt_chars=max_excerpt_chars, query=_workspace_topic_query(workspace)
    )
    claims = list_claims(workspace)
    plan_path = citation_plan_path(workspace, resolved.path, ".yaml")
    citation_plan = read_yaml(plan_path) if plan_path.is_file() else None
    selected_notes: list[dict[str, Any]] = []
    for kind in sorted(set(note_kinds or [])):
        selected_notes.extend(list_notes(workspace, kind=kind))

    if not context["has_evidence"] and not claims and not citation_plan and not selected_notes:
        report = _insufficient_evidence_response("ai_review_document", context)
        report["target"] = resolved.target
        return record_ai_usage(workspace, report)

    model = default_openai_model(workspace)
    response = openai_post(
        "responses",
        credentials,
        {
            "model": model,
            "input": _review_document_prompt(target_text, context, claims, citation_plan, selected_notes),
        },
        opener=opener,
    )
    text = extract_response_text(response)
    return record_ai_usage(
        workspace,
        {
            "version": 1,
            "kind": "ai_review_document",
            "provider": "openai",
            "model": model,
            "ai_used": True,
            "requires_user_review": True,
            "original_document_modified": False,
            "target": resolved.target,
            "target_path": str(resolved.path),
            "included_note_kinds": sorted(set(note_kinds or [])),
            "claim_count": len(claims),
            "note_count": len(selected_notes),
            "has_citation_plan": citation_plan is not None,
            "safe_context_policy": context["policy"],
            "limits": context["limits"],
            "source_count": len(context["sources"]),
            "response_id": response.get("id") if isinstance(response, dict) else None,
            "review": text,
            "grounding": validate_grounding(text, context=context, claims=claims, notes=selected_notes),
        },
    )
