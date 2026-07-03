from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from researchboss.core.yamlio import read_yaml, write_yaml


EVIDENCE_FILES = [
    "accepted-sources.yaml",
    "source-register.yaml",
    "claims-ledger.yaml",
    "research-questions.yaml",
    "research-question-candidates.yaml",
    "artefact-registry.yaml",
]


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


def _yaml_text(data: object) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
