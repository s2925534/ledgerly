# Corroborly Architecture

Corroborly is planned as a layered local-first research workspace.

## Layers

```text
CLI / future API / future UI
        |
        v
corroborly.engine
        |
        v
corroborly.core
        |
        v
local workspace files
```

## Core

`corroborly.core` contains small utilities with minimal policy:

- workspace file and folder constants
- YAML read/write helpers
- JSONL run logging
- YAML run summaries

## Engine

`corroborly.engine` contains reusable business logic:

- workspace initialization
- source discovery
- file hashing
- duplicate detection
- source register updates
- source review status transitions
- read-only Zotero storage metadata extraction from local paths
- read-only Zotero SQLite metadata lookup through immutable local connections
- offline Zotero collection listing, selected-collection scans, reports, snapshots, duplicate checks, and BibTeX export
- deterministic Zotero storage keyword search over filenames, `.zotero-ft-cache` text, and local SQLite metadata
- deterministic source conversion for TXT, MD, DOCX, and simple page-marked PDF text extraction
- conversion cache and failed conversion records
- deterministic citation metadata extraction without invented fields
- local CSV, SQLite, and JSON data profiling
- artefact registry records with linked source and research question IDs
- manual claim ledger and citation gap detection
- research stage templates and research question state transitions
- local Markdown reports, one-shot watch reports, workspace backups, and config migrations
- read-only CSL style title parsing for Zotero-compatible citation style wording
- init-time research question capture into approved and draft YAML files
- init-time setup preferences such as citation style, expected data files, source review defaults, AI preference metadata, and privacy preference

The CLI should call engine functions instead of duplicating file mutation logic.

## CLI

`corroborly.cli` is the Typer command layer. It handles prompts, options, progress display, tables, and command-level logging.

The CLI should stay thin so a future FastAPI backend can use the same engine logic.

CLI-only responsibilities include:

- interactive init questions and numbered menu validation
- runtime readiness checks before init and through `corroborly doctor`
- workspace discovery when `--workspace` is omitted
- local default workspace selection stored in `workspaces/.corroborly-cli.local.yaml`
- user-facing next-step command examples

The workspace selector is intentionally local and file-based. It does not introduce a remote registry or database.

## Workspace

A Corroborly workspace is a local folder containing YAML, Markdown, source, artefact, output, and log files. The current implementation creates the workspace skeleton and stores source review, conversion, metadata, data profile, research question, claim, artefact, report, and migration state in local files.

Workspace identity is currently inferred by the presence of `research-context.yaml` and `source-register.yaml`. Commands that need workspace context can receive `--workspace` explicitly. If omitted, the CLI discovers workspaces from the current directory and `./workspaces/*`; a single discovered workspace is selected automatically, and multiple workspaces are presented as a numbered list.

## Future Backend

The planned FastAPI backend should expose the same engine behavior through local API routes. It should not become a separate business-logic implementation.

## Future UI

The future desktop/web/mobile UI should consume the local API contract. UI state should not be mixed into `corroborly.core` or `corroborly.engine`.

## Privacy Boundary

Corroborly should treat original source files as read-only inputs. MVP operation should not require cloud services, remote databases, or external academic search. Optional AI features must use a safe context builder and must not upload whole documents or datasets.

AI behavior is not implemented. Init records only local AI preference metadata and writes `ai.enabled: false` in workspace settings.

Local Zotero support intentionally avoids the Zotero API for now. The engine can scan the `storage/` folder, register supported source files, store the Zotero storage item key, detect `.zotero-ft-cache`, read `zotero.sqlite` through immutable read-only SQLite connections, list and filter collections, enrich source records with metadata, generate local reports, snapshot metadata, detect duplicate candidates, export conservative BibTeX, and search filename/cache/metadata text deterministically. Corroborly must not write into Zotero storage or modify Zotero-owned files.

The entire local Zotero directory is a hard no-write boundary. No current command, development workflow, or future AI feature may modify anything inside Zotero's local directory. All derived outputs must be written inside the Corroborly workspace.

Workspace Zotero config includes strict one-way flags:

```yaml
strict_one_way_from_zotero_to_corroborly: true
block_writes_to_zotero_directory: true
```

Future AI whole-file, whole-directory, full-paper reasoning, and artefact cross-reference modes may be added only as explicit opt-in options. They must remain disabled by default, write outputs only inside the Corroborly workspace, and preserve the Zotero no-write boundary.
