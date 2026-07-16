from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from ledgerly.core.yamlio import read_yaml, write_yaml


EVIDENCE_FILES = [
    "accepted-sources.yaml",
    "source-register.yaml",
    "claims-ledger.yaml",
    "research-questions.yaml",
    "research-question-candidates.yaml",
    "artefact-registry.yaml",
]


@dataclass(frozen=True)
class CorpusExport:
    corpus_path: Path
    manifest_path: Path
    included_count: int
    skipped_count: int


def export_evidence_bundle(workspace: Path) -> Path:
    output_dir = workspace / "outputs" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "evidence-bundle.zip"
    accepted = set(read_yaml(workspace / "accepted-sources.yaml").get("source_ids", []))
    register = read_yaml(workspace / "source-register.yaml")
    accepted_sources = [
        source
        for source in register.get("sources", [])
        if isinstance(source, dict) and source.get("source_id") in accepted
    ]
    manifest = {
        "version": 1,
        "includes_original_files": False,
        "accepted_source_count": len(accepted_sources),
        "contents": EVIDENCE_FILES + ["outputs/data-profiles/*.yaml"],
    }
    manifest_path = workspace / "outputs" / "reports" / "evidence-bundle-manifest.yaml"
    write_yaml(manifest_path, manifest)

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zf:
        zf.write(manifest_path, "manifest.yaml")
        zf.writestr("accepted-source-records.yaml", _yaml_text({"version": 1, "sources": accepted_sources}))
        for relative in EVIDENCE_FILES:
            path = workspace / relative
            if path.is_file():
                zf.write(path, relative)
        profile_dir = workspace / "outputs" / "data-profiles"
        if profile_dir.is_dir():
            for path in sorted(profile_dir.glob("*.yaml")):
                zf.write(path, path.relative_to(workspace).as_posix())
    return output_path


def export_accepted_source_corpus(workspace: Path) -> CorpusExport:
    output_dir = workspace / "outputs" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = output_dir / "accepted-source-corpus.txt"
    manifest_path = output_dir / "accepted-source-corpus-manifest.yaml"

    accepted = set(read_yaml(workspace / "accepted-sources.yaml").get("source_ids", []))
    register = read_yaml(workspace / "source-register.yaml")
    included = []
    skipped = []
    sections = []
    for source in register.get("sources", []):
        if not isinstance(source, dict) or source.get("source_id") not in accepted:
            continue
        conversion = source.get("conversion") if isinstance(source.get("conversion"), dict) else {}
        text_path = Path(str(conversion.get("output_path") or ""))
        if not text_path.is_file():
            skipped.append(
                {
                    "source_id": source.get("source_id"),
                    "reason": "converted_text_missing",
                    "text_path": str(text_path) if str(text_path) != "." else None,
                }
            )
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            skipped.append({"source_id": source.get("source_id"), "reason": "converted_text_empty", "text_path": str(text_path)})
            continue
        header = _corpus_header(source, text_path)
        sections.append(header + "\n\n" + text + "\n")
        included.append(_corpus_manifest_record(source, text_path, len(text)))

    corpus_path.write_text(("\n" + "=" * 80 + "\n\n").join(sections), encoding="utf-8")
    manifest = {
        "version": 1,
        "includes_original_files": False,
        "corpus_path": str(corpus_path),
        "included_count": len(included),
        "skipped_count": len(skipped),
        "included_sources": included,
        "skipped_sources": skipped,
        "notes": "The corpus is built from workspace converted text for accepted sources only.",
    }
    write_yaml(manifest_path, manifest)
    return CorpusExport(corpus_path=corpus_path, manifest_path=manifest_path, included_count=len(included), skipped_count=len(skipped))


def _corpus_header(source: dict[str, Any], text_path: Path) -> str:
    metadata = source.get("citation_metadata") if isinstance(source.get("citation_metadata"), dict) else {}
    title = source.get("zotero_title") or metadata.get("title") or source.get("file_name") or "Unknown title"
    authors = source.get("zotero_creators") or metadata.get("authors") or "Unknown authors"
    if isinstance(authors, list):
        authors = "; ".join(str(author) for author in authors) or "Unknown authors"
    year = source.get("zotero_year") or metadata.get("year") or "Unknown year"
    lines = [
        f"Source ID: {source.get('source_id')}",
        f"Title: {title}",
        f"Authors: {authors}",
        f"Year: {year}",
        f"Converted text path: {text_path}",
    ]
    return "\n".join(lines)


def _corpus_manifest_record(source: dict[str, Any], text_path: Path, character_count: int) -> dict[str, Any]:
    metadata = source.get("citation_metadata") if isinstance(source.get("citation_metadata"), dict) else {}
    return {
        "source_id": source.get("source_id"),
        "title": source.get("zotero_title") or metadata.get("title") or source.get("file_name"),
        "authors": source.get("zotero_creators") or metadata.get("authors"),
        "year": source.get("zotero_year") or metadata.get("year"),
        "text_path": str(text_path),
        "character_count": character_count,
    }


def _yaml_text(data: object) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


def build_supervisor_bundle(workspace: Path) -> Path:
    """A single self-contained "hand this to my supervisor" bundle: the claim
    ledger, every citation plan created so far, and the workspace review
    report, as one readable Markdown digest plus a zip. Deliberately Markdown
    + zip rather than PDF — no PDF-generation dependency exists anywhere in
    this project today, and a Markdown digest is trivially convertible to
    PDF by the supervisor (or the user) with whatever tool they already have.
    """
    from ledgerly.engine.claims import citation_gap_claims, claim_source_validation_report, list_claims
    from ledgerly.engine.reports import generate_workspace_report

    output_dir = workspace / "outputs" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    workspace_report_path = generate_workspace_report(workspace)
    claims = list_claims(workspace)
    gap_ids = {claim.get("id") for claim in citation_gap_claims(workspace)}
    validation = claim_source_validation_report(workspace)
    issues_by_claim = {row.get("claim_id"): row.get("issues", []) for row in validation.get("claims", [])}

    plan_dir = workspace / "outputs" / "citation-plans"
    plan_paths = sorted(plan_dir.glob("citation-plan-*.md")) if plan_dir.is_dir() else []

    lines = [
        "# Supervisor Review Bundle",
        "",
        f"Generated: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
        "",
        "## Claim Ledger",
        "",
        "| ID | Status | Citation gap | Sources | Issues | Text |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        claim_id = claim.get("id", "")
        issue_count = len(issues_by_claim.get(claim_id, []))
        text = (claim.get("text") or "").replace("|", "\\|")
        lines.append(
            f"| {claim_id} | {claim.get('status', '')} | {'yes' if claim_id in gap_ids else 'no'} | "
            f"{len(claim.get('linked_sources', []))} | {issue_count} | {text} |"
        )
    if not claims:
        lines.append("| _none recorded yet_ | | | | | |")

    lines.extend(["", "## Citation Plans", ""])
    if plan_paths:
        for plan_path in plan_paths:
            lines.extend([f"### {plan_path.stem}", "", plan_path.read_text(encoding="utf-8").strip(), ""])
    else:
        lines.append("No citation plans created yet.")

    lines.extend(["", "## Workspace Review Report", "", workspace_report_path.read_text(encoding="utf-8").strip(), ""])

    digest_path = output_dir / "supervisor-bundle.md"
    digest_path.write_text("\n".join(lines), encoding="utf-8")

    bundle_path = output_dir / "supervisor-bundle.zip"
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as zf:
        zf.write(digest_path, digest_path.name)
        zf.write(workspace_report_path, workspace_report_path.name)
        zf.writestr("claims-ledger.yaml", _yaml_text({"version": 1, "claims": claims}))
        for plan_path in plan_paths:
            zf.write(plan_path, plan_path.relative_to(workspace).as_posix())
    return bundle_path
