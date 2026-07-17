from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


class BackupEncryptionError(RuntimeError):
    pass


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


def gpg_encryption_available() -> bool:
    return shutil.which("gpg") is not None


def create_encrypted_workspace_backup(
    workspace: Path, *, passphrase: str, include_originals: bool = False, opener=None
) -> Path:
    """Create a workspace backup zip, then encrypt it with gpg symmetric
    passphrase encryption (subprocess -- detect, don't bundle, matching this
    project's existing tesseract/SourceScribe pattern: `gpg` must already be
    installed on the machine, never bundled or imported). The unencrypted
    zip is deleted after encryption succeeds so plaintext never lingers on
    disk. Opt-in only; the default `create_workspace_backup` is unaffected.

    Verified live: `age`'s passphrase mode was considered first but rejected
    -- it hard-requires an interactive /dev/tty prompt and cannot accept a
    passphrase non-interactively at all, so it can't back a scriptable CLI
    flag. `gpg --batch --passphrase-fd 0 --symmetric` was confirmed live to
    work non-interactively with a real encrypt/decrypt round trip.
    """
    if not gpg_encryption_available():
        raise BackupEncryptionError(
            "The 'gpg' command-line tool is required for encrypted backups but was not found on PATH. "
            "Install it (e.g. `brew install gnupg`) or omit --encrypt for an unencrypted backup."
        )
    if not passphrase:
        raise BackupEncryptionError("A non-empty passphrase is required for encrypted backups.")

    zip_path = create_workspace_backup(workspace, include_originals=include_originals)
    encrypted_path = zip_path.with_name(zip_path.name + ".gpg")
    runner = opener or subprocess.run
    try:
        result = runner(
            [
                "gpg",
                "--batch",
                "--yes",
                "--passphrase-fd",
                "0",
                "--symmetric",
                "--cipher-algo",
                "AES256",
                "-o",
                str(encrypted_path),
                str(zip_path),
            ],
            input=passphrase,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise BackupEncryptionError(f"gpg encryption failed: {result.stderr.strip()}")
    finally:
        zip_path.unlink(missing_ok=True)
    return encrypted_path


def decrypt_workspace_backup(encrypted_path: Path, *, passphrase: str, output_path: Path | None = None, opener=None) -> Path:
    """Decrypt a backup created by `create_encrypted_workspace_backup` back
    into a plain zip `inspect_backup`/restore workflows can read normally.
    """
    if not gpg_encryption_available():
        raise BackupEncryptionError(
            "The 'gpg' command-line tool is required to decrypt this backup but was not found on PATH."
        )
    if not passphrase:
        raise BackupEncryptionError("A non-empty passphrase is required to decrypt this backup.")
    if not encrypted_path.is_file():
        raise BackupEncryptionError(f"Encrypted backup not found: {encrypted_path}")

    if output_path is None:
        output_path = (
            encrypted_path.with_suffix("")
            if encrypted_path.suffix == ".gpg"
            else encrypted_path.with_name(encrypted_path.name + ".decrypted")
        )
    runner = opener or subprocess.run
    result = runner(
        ["gpg", "--batch", "--yes", "--passphrase-fd", "0", "--decrypt", "-o", str(output_path), str(encrypted_path)],
        input=passphrase,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BackupEncryptionError(f"gpg decryption failed: {result.stderr.strip()}")
    return output_path


def inspect_backup(backup_path: Path) -> dict[str, object]:
    with ZipFile(backup_path, "r") as zf:
        names = sorted(zf.namelist())
        total_size = sum(info.file_size for info in zf.infolist())
    return {
        "version": 1,
        "backup_path": str(backup_path),
        "file_count": len(names),
        "total_uncompressed_bytes": total_size,
        "contains_original_sources": any(name.startswith("sources_original/") for name in names),
        "files": names,
        "dry_run": True,
    }
