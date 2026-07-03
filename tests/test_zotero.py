from pathlib import Path

from researchboss.engine.zotero import (
    has_zotero_fulltext_cache,
    keyword_terms,
    score_zotero_relevance,
    search_zotero_storage,
    zotero_relative_path,
    zotero_storage_key,
)


def make_storage(tmp_path: Path) -> tuple[Path, Path, Path]:
    storage = tmp_path / "Zotero" / "storage"
    first_dir = storage / "ABCD1234"
    second_dir = storage / "WXYZ9876"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)

    first = first_dir / "Evidence Synthesis.pdf"
    second = second_dir / "Unrelated Notes.pdf"
    first.write_text("pdf-ish", encoding="utf-8")
    second.write_text("pdf-ish", encoding="utf-8")
    (first_dir / ".zotero-ft-cache").write_text(
        "This paper discusses local first research workspaces and evidence review.",
        encoding="utf-8",
    )
    return storage, first, second


def test_zotero_storage_paths_and_cache_detection(tmp_path: Path) -> None:
    storage, first, _second = make_storage(tmp_path)

    assert zotero_storage_key(first, storage) == "ABCD1234"
    assert zotero_relative_path(first, storage) == "ABCD1234/Evidence Synthesis.pdf"
    assert has_zotero_fulltext_cache(first, storage) is True
    assert zotero_storage_key(tmp_path / "outside.pdf", storage) is None


def test_keyword_terms_are_normalized_and_deduplicated() -> None:
    assert keyword_terms("Evidence, evidence local-first") == ["evidence", "local-first"]


def test_zotero_relevance_scores_filename_and_fulltext_cache(tmp_path: Path) -> None:
    storage, first, second = make_storage(tmp_path)

    first_hit = score_zotero_relevance(first, storage, ["evidence", "workspace"])
    second_hit = score_zotero_relevance(second, storage, ["evidence", "workspace"])

    assert first_hit.score > second_hit.score
    assert first_hit.matched_terms == ["evidence", "workspace"]
    assert first_hit.matched_in == ["filename", "fulltext_cache"]
    assert first_hit.snippet is not None


def test_search_zotero_storage_returns_ranked_hits(tmp_path: Path) -> None:
    storage, first, second = make_storage(tmp_path)

    hits = search_zotero_storage(storage, ["evidence"], [second, first], limit=5)

    assert [hit.file_path for hit in hits] == [first]
