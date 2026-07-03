from __future__ import annotations

from pathlib import Path
from typing import Any

from researchboss.core.yamlio import read_yaml, write_yaml
from researchboss.engine.sources import iter_source_files, sha256_file


def find_unregistered_sources(workspace: Path) -> list[dict[str, Any]]:
    context = read_yaml(workspace / "research-context.yaml")
    source_root = context.get("sources", {}).get("root")
    if not source_root:
        return []
    root = Path(source_root)
    if not root.is_dir():
        return []

    register = read_yaml(workspace / "source-register.yaml")
    sources = [source for source in register.get("sources", []) if isinstance(source, dict)]
    known_paths = {str(source.get("file_path")) for source in sources}
    known_hashes = {str(source.get("content_hash")) for source in sources if source.get("content_hash")}

    candidates = []
    for path in iter_source_files(root):
        content_hash = sha256_file(path)
        if str(path) in known_paths or content_hash in known_hashes:
            continue
        candidates.append(
            {
                "file_path": str(path),
                "file_name": path.name,
                "file_ext": path.suffix.lower().lstrip("."),
                "content_hash": content_hash,
            }
        )
    return candidates


def write_watch_report(workspace: Path) -> Path:
    candidates = find_unregistered_sources(workspace)
    output_path = workspace / "outputs" / "recommendations" / "watch-candidates.yaml"
    write_yaml(output_path, {"version": 1, "candidate_count": len(candidates), "candidates": candidates})
    return output_path
