# TODO

## Phase 1: Engine and CLI Foundation

- [x] Fix `researchboss/cli.py` indentation errors so the package imports.
- [x] Import or remove the `ScanResult` annotation in the scan command.
- [x] Install and verify development dependencies from `pyproject.toml`.
- [x] Add a `tests/` folder with pytest coverage for workspace initialization.
- [x] Add tests for source scanning, hashing, duplicate detection, and allowed extensions.
- [x] Add tests for source status transitions: accepted, ignored, and maybe.
- [x] Add Typer CLI smoke tests for `init`, `status`, `config validate`, `scan`, and `sources` commands.
- [x] Validate source status values instead of accepting arbitrary strings.
- [x] Add `AGENTS.md` with project instructions and development rules.
- [x] Remove or replace the unused PyCharm sample `main.py`.
- [x] Decide whether `.idea/` should stay out of source control.
- [x] Expand README setup, testing, and architecture notes after the CLI is fixed.
- [x] Add numbered init prompts with retry validation instead of raw Click errors.
- [x] Capture optional research questions, draft status, and subquestions during init.
- [x] Capture init setup context: stakeholders, citation style, output type, data expectations, source review default, AI preference, and privacy preference.
- [x] Print concrete next-step commands after successful init.
- [x] Resolve omitted `--workspace` interactively across workspace-aware commands.
- [x] Auto-select a single discovered workspace and remember a default when several workspaces exist.
- [x] Add `researchboss version`.
- [x] Add `researchboss doctor` runtime checks and run the same preflight before `researchboss init`.
- [x] Add coverage for `python -m researchboss`.
- [x] Mark Phase 1 complete in README roadmap and add a Quick Start.
- [x] Record `zotero_storage` as the scan provider from workspace config when `--kind` is omitted.
- [x] Capture Zotero storage item keys and `.zotero-ft-cache` presence during storage scans.
- [x] Add read-only deterministic Zotero storage keyword search without AI or Zotero API use.
- [x] Store the Zotero parent root automatically when `storage/` is selected.
- [x] Add read-only `zotero.sqlite` metadata lookup using immutable SQLite connections.
- [x] Link Zotero storage files to parent Zotero items.
- [x] Add offline collection listing from local SQLite.
- [x] Add selected-collections and entire-library scan modes.
- [x] Add include/exclude subcollections support.
- [x] Add local metadata quality checks.
- [x] Add attachment health checks.
- [x] Add local full-text cache availability report.
- [x] Score deterministic Zotero search against local metadata.
- [x] Add local Zotero metadata snapshots.
- [x] Enrich source-register entries with Zotero metadata.
- [x] Add duplicate detection across Zotero metadata.
- [x] Add conservative offline BibTeX export from local metadata.

## Future Zotero Work

- [ ] Add future Zotero API collection listing and selection only if needed after offline workflows are stable.
- [ ] Add richer local SQLite coverage for notes, tags, relations, and item links.
- [ ] Add more complete BibTeX item-type and field mapping.

## Phase 2: Conversion and Metadata

- [x] Add TXT and MD conversion first.
- [x] Add DOCX conversion.
- [x] Add PDF conversion with page markers.
- [x] Add conversion cache keyed by file hash.
- [x] Add failed conversion handling and conversion statuses.
- [x] Add DOI detection.
- [x] Add basic citation metadata extraction without inventing missing metadata.
- [x] Add tests for all conversion paths.

## Phase 3: Data and Artefacts

- [x] Add CSV profiling: rows, columns, missing values, and inferred types.
- [x] Add SQLite profiling: tables, columns, and row counts where practical.
- [x] Add JSON source registration and profiling.
- [x] Add data profile reports under `outputs/data-profiles`.
- [x] Expand artefact registry records with linked sources and metadata.
- [x] Add tests for data profiling and artefact registry behavior.

## Phase 4: Research Questions and Stages

- [ ] Add richer research question templates for M.Phil, PhD, Other academic research, Industry research, and Custom.
- [x] Add M.Phil and PhD stage templates.
- [x] Add stage statuses.
- [x] Add research question candidate, approval, rejection, and archive workflows beyond init-time capture.
- [ ] Add warning thresholds without hard limits by default.
- [x] Add tests for research question and stage workflows.

## Phase 5: Optional OpenAI Features

- [ ] Add `researchboss ai test`.
- [ ] Read `OPENAI_API_KEY` from the environment without printing or logging it.
- [ ] Keep OpenAI disabled unless explicitly enabled.
- [ ] Keep Anthropic, Claude, and local LLM providers as future flags only.
- [ ] Add a safe context builder that never sends whole PDFs, CSVs, or SQLite databases.
- [ ] Add optional AI-assisted review.
- [ ] Add optional novelty assessment backed by `novelty-ledger.yaml`.
- [ ] Add tests for missing API key behavior and privacy boundaries.

## Phase 6: FastAPI Local Backend

- [ ] Add a local FastAPI app.
- [ ] Add routes for projects, sources, artefacts, research questions, reports, settings, logs, AI, and novelty.
- [ ] Reuse engine logic rather than duplicating business logic.
- [ ] Add API tests.

## Phase 7: Cross-Platform UI Preparation

- [ ] Document the desktop, web, and mobile UI strategy.
- [ ] Define a clear API contract.
- [ ] Add a frontend folder or explicit planned UI structure.
- [ ] Keep UI logic out of the core engine.

## Phase 8: Packaging

- [ ] Add packaging plan.
- [ ] Add PyInstaller or equivalent notes for the Python engine.
- [ ] Add future Flutter desktop packaging notes.
- [ ] Document Windows, macOS, and Linux considerations.
