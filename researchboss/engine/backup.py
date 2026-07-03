from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def create_workspace_backup(workspace: Path, *, include_originals: bool = False) -> Path:
    backup_dir = workspace / "outputs" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    output_path = backup_dir / f"{workspace.name}-backup.zip"
    excluded_roots = set()
    if not include_originals:
        excluded_roots.add("sources_original")

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as zf:
        for path in sorted(workspace.rglob("*")):
            if path == output_path or path.is_dir():
                continue
            relative = path.relative_to(workspace)
            if relative.parts and relative.parts[0] in excluded_roots:
                continue
            if relative.parts[:2] == ("outputs", "backups"):
                continue
            zf.write(path, relative.as_posix())
    return output_path
