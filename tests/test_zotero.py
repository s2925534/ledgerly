from pathlib import Path
import sqlite3

import pytest

from corroborly.engine.zotero import (
    attachment_health_report,
    attachment_metadata_by_storage_key,
    duplicate_metadata_candidates,
    ensure_path_not_in_zotero,
    export_bibtex_from_metadata,
    fulltext_availability_report,
    has_zotero_fulltext_cache,
    keyword_terms,
    list_zotero_collections,
    metadata_quality_report,
    score_zotero_relevance,
    search_zotero_storage,
    storage_keys_for_collections,
    zotero_metadata_snapshot,
    zotero_readiness_report,
    zotero_relative_path,
    zotero_root_from_storage,
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

    assert zotero_root_from_storage(storage) == tmp_path / "Zotero"
    assert zotero_storage_key(first, storage) == "ABCD1234"
    assert zotero_relative_path(first, storage) == "ABCD1234/Evidence Synthesis.pdf"
    assert has_zotero_fulltext_cache(first, storage) is True
    assert zotero_storage_key(tmp_path / "outside.pdf", storage) is None


def test_ensure_path_not_in_zotero_blocks_writes(tmp_path: Path) -> None:
    zotero_root = tmp_path / "Zotero"
    zotero_root.mkdir()

    with pytest.raises(ValueError, match="Blocked write inside local Zotero directory"):
        ensure_path_not_in_zotero(zotero_root / "blocked.yaml", zotero_root)

    ensure_path_not_in_zotero(tmp_path / "workspace" / "allowed.yaml", zotero_root)


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


def make_zotero_sqlite(zotero_root: Path) -> Path:
    db_path = zotero_root / "zotero.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT);
        CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, path TEXT, contentType TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INTEGER);
        CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER);
        CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, title TEXT, note TEXT);
        CREATE TABLE itemRelations (subject TEXT, predicate TEXT, object TEXT);
        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT,
            key TEXT,
            parentCollectionID INTEGER,
            libraryID INTEGER
        );
        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
        """
    )
    conn.executemany("INSERT INTO itemTypes VALUES (?, ?)", [(1, "journalArticle"), (2, "attachment")])
    conn.executemany(
        "INSERT INTO items VALUES (?, ?, ?)",
        [(10, 1, "PARENT01"), (20, 2, "ABCD1234"), (30, 2, "WXYZ9876"), (40, 1, "RELATED1"), (50, 2, "NOTE0001")],
    )
    conn.executemany(
        "INSERT INTO itemAttachments VALUES (?, ?, ?, ?)",
        [(20, 10, "storage:Evidence Synthesis.pdf", "application/pdf"), (30, 10, "storage:Copy.pdf", "application/pdf")],
    )
    fields = [
        (1, "title"),
        (2, "date"),
        (3, "DOI"),
        (4, "url"),
        (5, "publicationTitle"),
        (6, "abstractNote"),
        (7, "volume"),
        (8, "issue"),
        (9, "pages"),
        (10, "publisher"),
    ]
    conn.executemany("INSERT INTO fields VALUES (?, ?)", fields)
    values = [
        (1, "Evidence Synthesis for Local Research"),
        (2, "2024"),
        (3, "10.1234/example"),
        (4, "https://example.test/paper"),
        (5, "Journal of Local Tools"),
        (6, "An abstract about local evidence review."),
        (7, "12"),
        (8, "3"),
        (9, "45-67"),
        (10, "Local Press"),
    ]
    conn.executemany("INSERT INTO itemDataValues VALUES (?, ?)", values)
    conn.executemany("INSERT INTO itemData VALUES (?, ?, ?)", [(10, value_id, value_id) for value_id, _value in values])
    conn.executemany(
        "INSERT INTO itemData VALUES (?, ?, ?)",
        [(40, 1, 1), (40, 2, 2)],
    )
    conn.execute("INSERT INTO creators VALUES (?, ?, ?, ?)", (1, "Pedro", "Veloso", 0))
    conn.execute("INSERT INTO itemCreators VALUES (?, ?, ?, ?)", (10, 1, 1, 0))
    conn.executemany("INSERT INTO tags VALUES (?, ?)", [(1, "methodology"), (2, "evidence")])
    conn.executemany("INSERT INTO itemTags VALUES (?, ?)", [(10, 1), (10, 2)])
    conn.execute(
        "INSERT INTO itemNotes VALUES (?, ?, ?, ?)",
        (50, 10, "Review note", "<p>Important note about deterministic evidence review.</p>"),
    )
    conn.execute("INSERT INTO itemRelations VALUES (?, ?, ?)", ("PARENT01", "dc:relation", "RELATED1"))
    conn.executemany(
        "INSERT INTO collections VALUES (?, ?, ?, ?, ?)",
        [(100, "Thesis", "COLLROOT", None, 1), (101, "Chapter One", "COLLCH1", 100, 1)],
    )
    conn.executemany("INSERT INTO collectionItems VALUES (?, ?)", [(100, 10), (101, 10)])
    conn.commit()
    conn.close()
    return db_path


def test_readonly_sqlite_metadata_and_collections(tmp_path: Path) -> None:
    storage, first, _second = make_storage(tmp_path)
    zotero_root = storage.parent
    make_zotero_sqlite(zotero_root)

    metadata = attachment_metadata_by_storage_key(zotero_root, "ABCD1234")
    assert metadata is not None
    assert metadata.parent_item_key == "PARENT01"
    assert metadata.title == "Evidence Synthesis for Local Research"
    assert metadata.creators == ["Pedro Veloso"]
    assert metadata.year == "2024"
    assert metadata.doi == "10.1234/example"
    assert metadata.collections[0]["key"] == "COLLROOT"
    assert metadata.tags == ["evidence", "methodology"]
    assert metadata.notes == [
        {"key": "NOTE0001", "title": "Review note", "text": "Important note about deterministic evidence review."}
    ]
    assert metadata.relations == [{"subject": "PARENT01", "predicate": "dc:relation", "object": "RELATED1"}]
    assert metadata.linked_items == [
        {"key": "RELATED1", "item_type": "journalArticle", "title": "Evidence Synthesis for Local Research"}
    ]
    assert metadata.extra_fields["pages"] == "45-67"

    collections = list_zotero_collections(zotero_root)
    assert [collection.key for collection in collections] == ["COLLROOT", "COLLCH1"]
    assert collections[1].path == "Thesis / Chapter One"

    keys = storage_keys_for_collections(zotero_root, ["COLLROOT"], include_subcollections=True)
    assert keys == {"ABCD1234", "WXYZ9876"}


def test_zotero_search_can_match_sqlite_metadata(tmp_path: Path) -> None:
    storage, first, _second = make_storage(tmp_path)
    zotero_root = storage.parent
    make_zotero_sqlite(zotero_root)

    hit = score_zotero_relevance(first, storage, ["veloso"], zotero_root=zotero_root)

    assert hit.score > 0
    assert hit.matched_terms == ["veloso"]
    assert hit.matched_in == ["creators"]

    note_hit = score_zotero_relevance(first, storage, ["deterministic"], zotero_root=zotero_root)
    assert note_hit.score > 0
    assert "notes" in note_hit.matched_in


def test_zotero_reports_snapshot_duplicates_and_bibtex(tmp_path: Path) -> None:
    storage, first, second = make_storage(tmp_path)
    zotero_root = storage.parent
    make_zotero_sqlite(zotero_root)

    quality = metadata_quality_report(zotero_root)
    assert quality["total_attachments"] == 2
    assert quality["missing_title"] == []
    assert quality["with_tags"] == ["ABCD1234", "WXYZ9876"]
    assert quality["with_notes"] == ["ABCD1234", "WXYZ9876"]
    assert quality["with_relations"] == ["ABCD1234", "WXYZ9876"]

    health = attachment_health_report(zotero_root, storage, [first])
    assert health["sqlite_attachments"] == 2
    assert health["missing_attachment_files"] == ["WXYZ9876"]

    fulltext = fulltext_availability_report(storage, [first, second])
    assert fulltext["with_fulltext_cache"] == 1
    assert fulltext["without_fulltext_cache"] == 1

    duplicates = duplicate_metadata_candidates(zotero_root)
    assert len(duplicates) == 1
    assert duplicates[0]["match_type"] == "doi"

    snapshot = zotero_metadata_snapshot(zotero_root)
    assert len(snapshot["attachments"]) == 2
    assert len(snapshot["collections"]) == 2
    assert snapshot["attachments"][0]["zotero_tags"] == ["evidence", "methodology"]

    bibtex = export_bibtex_from_metadata(zotero_root)
    assert "@article{veloso_evidence_2024," in bibtex
    assert "doi = {10.1234/example}" in bibtex
    assert "pages = {45-67}" in bibtex
    assert "note = {evidence; methodology}" in bibtex


def test_zotero_readiness_report_checks_local_paths(tmp_path: Path) -> None:
    storage, first, second = make_storage(tmp_path)
    zotero_root = storage.parent
    make_zotero_sqlite(zotero_root)

    report = zotero_readiness_report(zotero_root, storage, [first, second])

    assert report["storage_exists"] is True
    assert report["sqlite_exists"] is True
    assert report["sqlite_readable"] is True
    assert report["collection_count"] == 2
    assert report["sqlite_attachment_count"] == 2
    assert report["source_file_count"] == 2
    assert report["with_fulltext_cache"] == 1
