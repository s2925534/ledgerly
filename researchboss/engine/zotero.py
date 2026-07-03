from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


FULLTEXT_CACHE_NAME = ".zotero-ft-cache"
MAX_CACHE_CHARS = 200_000
SNIPPET_RADIUS = 80


@dataclass(frozen=True)
class ZoteroSearchHit:
    file_path: Path
    storage_key: Optional[str]
    score: int
    matched_terms: list[str]
    matched_in: list[str]
    has_fulltext_cache: bool
    snippet: Optional[str]


def zotero_storage_key(path: Path, storage_root: Path) -> Optional[str]:
    """Return the Zotero storage item folder name for a path under storage_root."""
    try:
        relative = path.resolve().relative_to(storage_root.resolve())
    except ValueError:
        return None

    if not relative.parts:
        return None
    return relative.parts[0]


def zotero_relative_path(path: Path, storage_root: Path) -> Optional[str]:
    try:
        return str(path.resolve().relative_to(storage_root.resolve()))
    except ValueError:
        return None


def zotero_fulltext_cache_path(path: Path, storage_root: Path) -> Optional[Path]:
    key = zotero_storage_key(path, storage_root)
    if not key:
        return None
    return storage_root / key / FULLTEXT_CACHE_NAME


def has_zotero_fulltext_cache(path: Path, storage_root: Path) -> bool:
    cache_path = zotero_fulltext_cache_path(path, storage_root)
    return bool(cache_path and cache_path.is_file())


def read_zotero_fulltext_cache(path: Path, storage_root: Path, *, limit: int = MAX_CACHE_CHARS) -> str:
    cache_path = zotero_fulltext_cache_path(path, storage_root)
    if not cache_path or not cache_path.is_file():
        return ""
    text = cache_path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def keyword_terms(query: str | Iterable[str]) -> list[str]:
    if isinstance(query, str):
        raw = query
    else:
        raw = " ".join(query)

    terms = []
    seen = set()
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", raw.lower()):
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _snippet(text: str, term: str) -> Optional[str]:
    lower = text.lower()
    index = lower.find(term.lower())
    if index < 0:
        return None
    start = max(0, index - SNIPPET_RADIUS)
    end = min(len(text), index + len(term) + SNIPPET_RADIUS)
    snippet = " ".join(text[start:end].split())
    return snippet or None


def score_zotero_relevance(file_path: Path, storage_root: Path, terms: list[str]) -> ZoteroSearchHit:
    name_text = file_path.name.lower()
    cache_text = read_zotero_fulltext_cache(file_path, storage_root)
    cache_lower = cache_text.lower()

    score = 0
    matched_terms: list[str] = []
    matched_in: list[str] = []
    first_snippet: Optional[str] = None

    for term in terms:
        term_score = 0
        locations = []
        if term in name_text:
            term_score += 10
            locations.append("filename")
        if term in cache_lower:
            term_score += 3
            locations.append("fulltext_cache")
            if first_snippet is None:
                first_snippet = _snippet(cache_text, term)

        if term_score:
            score += term_score
            matched_terms.append(term)
            for location in locations:
                if location not in matched_in:
                    matched_in.append(location)

    return ZoteroSearchHit(
        file_path=file_path,
        storage_key=zotero_storage_key(file_path, storage_root),
        score=score,
        matched_terms=matched_terms,
        matched_in=matched_in,
        has_fulltext_cache=has_zotero_fulltext_cache(file_path, storage_root),
        snippet=first_snippet,
    )


def search_zotero_storage(
    storage_root: Path,
    terms: list[str],
    file_paths: Iterable[Path],
    *,
    limit: int = 10,
) -> list[ZoteroSearchHit]:
    hits = [score_zotero_relevance(path, storage_root, terms) for path in file_paths]
    hits = [hit for hit in hits if hit.score > 0]
    hits.sort(key=lambda hit: (-hit.score, str(hit.file_path).lower()))
    return hits[:limit]
