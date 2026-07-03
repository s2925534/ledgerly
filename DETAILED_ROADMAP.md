# ResearchBoss Detailed Roadmap

Project version: 0.1.1

Last updated: 2026-07-03

This roadmap tracks implementation progress for ResearchBoss. Update this file whenever development changes feature status, project scope, version, or recommended next steps.

## 1. Executive Summary

ResearchBoss is currently in the early post-Phase 1 stage.

Implemented:

- Python package structure.
- Typer CLI foundation.
- Local workspace initialization.
- Local YAML and Markdown workspace state files.
- Source folder scanning.
- Read-only local Zotero storage scanning.
- Deterministic local Zotero storage keyword search over filenames and `.zotero-ft-cache`.
- Source hashing and duplicate detection.
- Source review statuses: `pending_review`, `accepted`, `maybe`, `ignored`.
- Workspace discovery, selection, and local default workspace memory.
- JSONL logs and YAML run summaries.
- README, AGENTS.md, architecture notes, TODO, changelog, and tests.

Partially implemented:

- Zotero support: local storage-folder support exists; Zotero API, collection selection, and local `zotero.sqlite` metadata lookup are not implemented.
- Research questions: init-time capture exists; full workflow commands are not implemented.
- AI setup: local preference metadata exists; AI behavior is not implemented.

Not implemented:

- Conversion and metadata extraction.
- CSV and SQLite profiling.
- Artefact generation and richer artefact registry behavior.
- Claim checking and citation gap detection.
- Optional OpenAI workflows.
- FastAPI backend.
- Cross-platform UI.
- Packaging.

Current repository state: coherent and test-covered for Phase 1, with later phases intentionally not started.

## 2. Repository Structure Review

Current important structure:

```text
researchboss/
  core/
    constants.py
    runlog.py
    yamlio.py
  engine/
    sources.py
    workspace.py
    zotero.py
  cli.py
  __init__.py
  __main__.py

tests/
  test_cli.py
  test_sources.py
  test_workspace.py
  test_zotero.py

docs/
  ARCHITECTURE.md

AGENTS.md
CHANGELOG.md
DETAILED_ROADMAP.md
LICENSE
README.md
TODO.md
pyproject.toml
```

Important folders:

- `researchboss/core`: low-level constants, YAML I/O, logging, and run summaries.
- `researchboss/engine`: reusable business logic for workspace creation, source scanning, source review, and local Zotero storage helpers.
- `researchboss/cli.py`: Typer command layer.
- `tests`: pytest coverage for CLI and engine behavior.
- `docs`: architecture and planning notes.
- `workspaces`: ignored generated local workspaces.

Expected future folders:

- `researchboss/api` for FastAPI.
- `frontend` or equivalent UI planning folder.
- `docs/api` for API contracts.
- `docs/packaging` for desktop packaging notes.

## 3. Implemented Features

| Feature | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Python package structure | Implemented | `researchboss/`, `pyproject.toml` | Package installs as `researchboss`. |
| Typer CLI | Implemented | `researchboss/cli.py` | CLI commands are tested. |
| `researchboss init` | Implemented | `researchboss/cli.py`, `researchboss/engine/workspace.py` | Creates local workspace skeleton. |
| Workspace files | Implemented | `researchboss/core/constants.py`, `workspace.py` | YAML and Markdown state files are created. |
| Local scan | Implemented | `researchboss/engine/sources.py` | Scans supported source files. |
| Zotero storage scan | Implemented | `sources.py`, `zotero.py` | Reads local `storage/`; no API use. |
| Zotero storage search | Implemented | `researchboss/engine/zotero.py`, `cli.py` | Searches filenames and `.zotero-ft-cache`. |
| Hashing | Implemented | `sha256_file` in `sources.py` | SHA-256 content hash. |
| Duplicate detection | Implemented | `scan_sources` in `sources.py` | Duplicate by content hash. |
| Source statuses | Implemented | `SOURCE_STATUSES` in `sources.py` | Pending, accepted, maybe, ignored. |
| Source review workflow | Implemented | `set_source_status`, CLI source commands | Local YAML-only state updates. |
| Logs and summaries | Implemented | `researchboss/core/runlog.py` | JSONL logs and YAML summaries. |
| Progress bars | Implemented | `scan` in `cli.py` | Rich progress display. |
| Tests | Implemented | `tests/` | Current suite covers Phase 1 and Zotero storage helpers. |
| README and AGENTS.md | Implemented | `README.md`, `AGENTS.md` | Contributor and user docs exist. |

## 4. Phase-by-Phase Audit

### Phase 1: Engine and CLI Foundation

Status: complete, with extra local Zotero storage improvements.

Implemented:

- Package structure, CLI, init, workspace files, source scanning, source review, logging, run summaries, progress bars, tests, README, AGENTS.md.
- Workspace discovery and default workspace memory.
- Runtime checks through `doctor` and before `init`.
- Local Zotero storage scan/search without AI or API use.

Remaining Phase 1 refinements:

- Store Zotero parent root automatically when `storage/` is selected.
- Consider validating `--kind` values instead of accepting arbitrary provider strings.

### Phase 2: Conversion and Metadata

Status: not started.

Next work:

- TXT and MD conversion.
- DOCX conversion.
- PDF conversion with page markers.
- Conversion cache by file hash.
- Failed conversion handling.
- DOI detection and basic citation metadata extraction without invented metadata.

### Phase 3: Data and Artefacts

Status: not started.

Next work:

- CSV profiling.
- SQLite profiling.
- Data profile reports.
- Rich artefact registry records.

### Phase 4: Research Questions and Stages

Status: partially started during init only.

Implemented:

- Init-time research questions.
- Draft and approved separation.
- Optional subquestions.

Next work:

- Templates for M.Phil, PhD, Other academic, Industry, and Custom.
- Stage templates.
- RQ approve/reject/archive commands.
- Warning thresholds.

### Phase 5: Optional OpenAI Features

Status: not implemented.

Implemented:

- Local AI preference metadata only.
- AI disabled in generated app settings.

Next work:

- `researchboss ai test`.
- Environment-based `OPENAI_API_KEY` handling.
- Safe context builder.
- Optional review and novelty flows.
- Tests for privacy boundaries.

### Phase 6: FastAPI Local Backend

Status: not started.

Next work:

- Define engine contracts first.
- Add local API routes after core behavior is tested.

### Phase 7: Cross-Platform UI Preparation

Status: not started.

Next work:

- Document UI strategy.
- Define API contract.
- Keep UI logic outside engine/core.

### Phase 8: Packaging

Status: not started.

Next work:

- Packaging plan.
- PyInstaller or equivalent notes.
- Windows, macOS, Linux distribution notes.

## 5. CLI Audit

| Command | Status | Notes |
| --- | --- | --- |
| `researchboss init` | Implemented | Creates workspace and prompts for initial context. |
| `researchboss status` | Implemented | Shows source counts. |
| `researchboss config validate` | Implemented | Checks required workspace paths and YAML readability. |
| `researchboss scan` | Implemented | Scans configured or provided source root. |
| `researchboss sources list` | Implemented | Lists source register records. |
| `researchboss sources review` | Implemented | Interactive pending source review. |
| `researchboss sources accept` | Implemented | Marks source accepted. |
| `researchboss sources ignore` | Implemented | Marks source ignored with reason. |
| `researchboss sources maybe` | Implemented | Marks source maybe. |
| `researchboss sources status` | Implemented | Shows source status counts. |
| `researchboss zotero search` | Implemented | Local storage keyword search; no AI/API. |
| `researchboss zotero collections` | Missing | Future API/local metadata work. |
| `researchboss zotero select-collections` | Missing | Future API/local metadata work. |
| `researchboss zotero test` | Missing | Future validation command. |
| `researchboss convert` | Missing | Phase 2. |
| `researchboss data profile` | Missing | Phase 3. |
| `researchboss data list` | Missing | Phase 3. |
| `researchboss data status` | Missing | Phase 3. |
| `researchboss rqs list` | Missing | Phase 4. |
| `researchboss rqs suggest` | Missing | Phase 4 or Phase 5 depending on AI use. |
| `researchboss rqs approve` | Missing | Phase 4. |
| `researchboss rqs reject` | Missing | Phase 4. |
| `researchboss rqs archive` | Missing | Phase 4. |
| `researchboss review` | Missing | Later integrated review workflow. |
| `researchboss assess-novelty` | Missing | Phase 5. |
| `researchboss ai test` | Missing | Phase 5. |
| `researchboss report` | Missing | Later reporting. |
| `researchboss watch` | Missing | Later automation. |

## 6. Config and Workspace Audit

Workspace creation currently generates the Phase 1 file and folder skeleton, including research context/state files, source registers, review lists, ledgers, terminology, feedback, memory files, artefact registry, app settings, `.gitignore`, source folders, artefact folders, output folders, logs, run summaries, and context versions.

Known config improvement:

- When `sources.mode` is `zotero_storage`, also store the Zotero parent directory, not only `sources.root` pointing at `storage/`.

## 7. Source Workflow Audit

Implemented:

- Discover local source files.
- Hash files.
- Detect duplicates by hash.
- Create source IDs.
- Mark new sources as `pending_review` or `maybe`.
- Accept, ignore, and maybe source workflow.
- Exclude ignored/accepted/maybe state per workspace.

Missing or future:

- Metadata-only source status.
- Failed conversion status.
- Manual review required status beyond current config flag.
- Downstream enforcement that only accepted sources are used for research tasks.

## 8. Zotero Audit

Implemented:

- Detect default Zotero `storage/` path on macOS and Windows.
- Scan local Zotero storage folders.
- Record Zotero storage key and relative storage path.
- Detect `.zotero-ft-cache`.
- Search filenames and `.zotero-ft-cache` text deterministically.
- Avoid modifying Zotero files.
- Avoid writing into Zotero storage.

Missing:

- Store Zotero parent directory automatically.
- Read-only local `zotero.sqlite` metadata lookup.
- Zotero local API.
- Collection listing and selection.
- Include subcollections setting.
- Entire library vs selected collection mode.

## 9. Data Source Audit

Status: not implemented.

Missing:

- CSV profiling.
- SQLite profiling.
- JSON source registration.
- Data source statuses.
- Data profile reports.
- Tests proving full datasets are not sent to AI.

## 10. Artefact Audit

Status: skeleton only.

Implemented:

- Artefact folders.
- `artefact-registry.yaml` shell.

Missing:

- Artefact metadata records.
- Linked sources and research questions.
- AI-generated metadata flags.
- `requires_user_review` flag.

## 11. AI and OpenAI Audit

Status: not implemented.

Implemented:

- AI preference metadata.
- `ai.enabled: false` in local app settings.
- `.env` ignored.
- `.env.example` exists.

Missing:

- OpenAI provider setup command.
- API key validation.
- Safe context builder.
- Novelty assessment.
- Corpus summary behavior.
- Privacy-boundary tests.

## 12. Tests Audit

Framework: pytest.

Current tested areas:

- CLI smoke tests.
- Workspace initialization.
- Source scanning and review.
- Workspace selection.
- Runtime checks.
- Local Zotero storage helpers and CLI search.

Current expected validation:

```bash
python -m py_compile researchboss/cli.py researchboss/engine/sources.py researchboss/engine/zotero.py researchboss/engine/workspace.py researchboss/core/runlog.py researchboss/core/yamlio.py researchboss/core/constants.py
python -m pytest
```

Recommended next tests:

- Zotero parent root config.
- TXT/MD conversion.
- Conversion cache.
- Failed conversion records.

## 13. Security and Privacy Audit

Current privacy posture:

- MVP does not require cloud services.
- No external academic search.
- No AI document upload behavior exists.
- Source files are read-only inputs.
- Zotero storage is read-only.
- `.env` is ignored.

Known follow-up:

- Add tests for future AI privacy boundaries before implementing AI-assisted flows.

## 14. Documentation Audit

Implemented:

- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `TODO.md`
- `CHANGELOG.md`
- `DETAILED_ROADMAP.md`
- Setup and test instructions.
- Initial OpenAI and Zotero notes.
- Local-first privacy boundaries.

Missing:

- Full API contract.
- Desktop/web/mobile strategy.
- Packaging documentation.

## 15. Immediate Next Steps

1. Store Zotero parent root automatically.
   - Why: local `zotero.sqlite` metadata support needs `/Zotero`, not only `/Zotero/storage`.
   - Likely files: `workspace.py`, `cli.py`, tests, README.
   - Tests: workspace init and CLI init with Zotero storage.
   - Complexity: low.
   - Phase: 1 refinement.

2. Validate scan provider values.
   - Why: prevent accidental unknown provider strings in source records.
   - Likely files: `sources.py`, `cli.py`, tests.
   - Tests: invalid `--kind`.
   - Complexity: low.
   - Phase: 1 refinement.

3. Add read-only Zotero SQLite metadata lookup.
   - Why: enables useful title/author/year metadata without Zotero API or AI.
   - Likely files: new `engine/zotero_metadata.py`, CLI/tests/docs.
   - Tests: temp SQLite fixture.
   - Complexity: medium.
   - Phase: 1 refinement / Phase 2 support.

4. Add TXT conversion.
   - Why: first conversion path with low risk.
   - Likely files: new conversion engine, CLI/tests/docs.
   - Tests: TXT source to `sources_text`.
   - Complexity: low.
   - Phase: 2.

5. Add MD conversion.
   - Why: quick second text conversion path.
   - Likely files: conversion engine/tests.
   - Tests: MD source to text output.
   - Complexity: low.
   - Phase: 2.

6. Add conversion cache keyed by hash.
   - Why: avoids repeated conversion and supports reproducibility.
   - Likely files: conversion engine, source register updates.
   - Tests: repeated conversion no-op.
   - Complexity: medium.
   - Phase: 2.

7. Add failed conversion handling.
   - Why: failures must be visible and recoverable.
   - Likely files: conversion engine, `sources_failed`, source status fields.
   - Tests: unsupported/broken file path.
   - Complexity: medium.
   - Phase: 2.

8. Add PDF conversion with page markers.
   - Why: core evidence workflow needs page-specific text.
   - Likely files: conversion engine, dependency selection, tests.
   - Tests: sample PDF fixture.
   - Complexity: high.
   - Phase: 2.

9. Add DOI detection.
   - Why: citation metadata should start with deterministic extraction.
   - Likely files: metadata engine, tests.
   - Tests: DOI patterns and no invented metadata.
   - Complexity: medium.
   - Phase: 2.

10. Add CSV profiling.
    - Why: begins data source support.
    - Likely files: data engine, CLI, tests.
    - Tests: row/column/missing/type profile.
    - Complexity: medium.
    - Phase: 3.

## 16. Recommended Resume Point

Resume with a Phase 1 refinement: automatically store the Zotero parent root when a Zotero `storage/` folder is selected or detected. After that, move to Phase 2 conversion, starting with TXT and MD conversion tests.

## 17. Maintenance Rule

Whenever development changes ResearchBoss behavior:

- Update this roadmap.
- Update `README.md` project version.
- Update package version in `pyproject.toml` and `researchboss/__init__.py` when releasing or committing user-visible feature work.
- Update `CHANGELOG.md`.
- Keep tests passing before commit or push.
