# Changelog

All notable changes to ResearchBoss will be documented in this file.

## Unreleased

- Bumped project version to 0.1.1.
- Added `DETAILED_ROADMAP.md` as the living 17-section implementation roadmap.
- Added an explicit current version line to the README.
- Added read-only local Zotero storage search over filenames and `.zotero-ft-cache` text without AI or Zotero API use.
- Added Zotero storage metadata to scanned source records: storage key, relative path, and full-text-cache presence.
- Updated `researchboss scan` to inherit `zotero_storage` provider mode from workspace config when `--kind` is omitted.
- Phase 2 work is planned next: TXT/MD conversion, conversion caching, and citation metadata extraction.

## 0.1.0 - 2026-07-03

Phase 1 engine and CLI foundation completed.

Added:

- Local-first workspace initialization.
- Default YAML and Markdown workspace state files.
- Source folder skeletons for original files, converted text, metadata, failed sources, artefacts, outputs, logs, and context versions.
- Typer CLI command layer with `init`, `doctor`, `version`, `status`, `config validate`, `scan`, and `sources` commands.
- Runtime readiness checks before `researchboss init` and through `researchboss doctor`.
- `python -m researchboss` entrypoint coverage.
- Local source scanning for PDF, DOCX, TXT, MD, CSV, SQLite, and DB files.
- SHA-256 hashing and duplicate detection by content hash.
- Source review states: `pending_review`, `accepted`, `maybe`, and `ignored`.
- Convenience YAML files for accepted, maybe, and ignored source IDs.
- JSONL command logs and YAML run summaries.
- Richer init wizard for research level, topic, research questions, subquestions, stakeholders, citation style, output type, data expectations, AI preference metadata, evidence/privacy preferences, and source review defaults.
- Workspace discovery when `--workspace` is omitted.
- Automatic selection when exactly one workspace is discovered.
- Numbered workspace selection and local default workspace memory when several workspaces exist.
- Concrete next-step command examples after successful init.
- MIT license and author metadata.
- README, TODO, architecture, and validation documentation for the Phase 1 baseline.

Notes:

- AI behavior is not implemented in Phase 1. Init records local AI preference metadata only and keeps AI disabled.
- Zotero support is storage-folder scanning only. Zotero API collection selection is planned for later work.
- Accepted sources are tracked locally, but downstream conversion and research workflows are planned for Phase 2 and later.
