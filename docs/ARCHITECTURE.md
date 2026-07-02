# ResearchBoss Architecture

ResearchBoss is planned as a layered local-first research workspace.

## Layers

```text
CLI / future API / future UI
        |
        v
researchboss.engine
        |
        v
researchboss.core
        |
        v
local workspace files
```

## Core

`researchboss.core` contains small utilities with minimal policy:

- workspace file and folder constants
- YAML read/write helpers
- JSONL run logging
- YAML run summaries

## Engine

`researchboss.engine` contains reusable business logic:

- workspace initialization
- source discovery
- file hashing
- duplicate detection
- source register updates
- source review status transitions

The CLI should call engine functions instead of duplicating file mutation logic.

## CLI

`researchboss.cli` is the Typer command layer. It handles prompts, options, progress display, tables, and command-level logging.

The CLI should stay thin so a future FastAPI backend can use the same engine logic.

## Workspace

A ResearchBoss workspace is a local folder containing YAML, Markdown, source, artefact, output, and log files. The current implementation creates the Phase 1 workspace skeleton and stores source review state in local YAML files.

## Future Backend

The planned FastAPI backend should expose the same engine behavior through local API routes. It should not become a separate business-logic implementation.

## Future UI

The future desktop/web/mobile UI should consume the local API contract. UI state should not be mixed into `researchboss.core` or `researchboss.engine`.

## Privacy Boundary

ResearchBoss should treat original source files as read-only inputs. MVP operation should not require cloud services, remote databases, or external academic search. Optional AI features must use a safe context builder and must not upload whole documents or datasets.
