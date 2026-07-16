from pathlib import Path
from zipfile import ZipFile

import pytest

from ledgerly.engine.backup import (
    BackupEncryptionError,
    create_encrypted_workspace_backup,
    create_workspace_backup,
    decrypt_workspace_backup,
    gpg_encryption_available,
    inspect_backup,
)
from ledgerly.engine.workspace import init_workspace

requires_gpg = pytest.mark.skipif(not gpg_encryption_available(), reason="No local gpg binary available")


def test_create_workspace_backup_excludes_original_sources_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "secret.txt").write_text("source", encoding="utf-8")
    (workspace / "memory.md").write_text("# Memory\nnote", encoding="utf-8")

    output_path = create_workspace_backup(workspace)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())
    assert "memory.md" in names
    assert "sources_original/manual/secret.txt" not in names


def test_create_workspace_backup_can_include_original_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "sources_original" / "manual" / "source.txt").write_text("source", encoding="utf-8")

    output_path = create_workspace_backup(workspace, include_originals=True)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())
    assert "sources_original/manual/source.txt" in names


def test_inspect_backup_reports_contents_without_restoring(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "memory.md").write_text("# Memory\nnote", encoding="utf-8")
    output_path = create_workspace_backup(workspace)

    report = inspect_backup(output_path)

    assert report["dry_run"] is True
    assert report["file_count"] > 0
    assert report["contains_original_sources"] is False


class _FakeGpgResult:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_create_encrypted_workspace_backup_rejects_empty_passphrase(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")

    with pytest.raises(BackupEncryptionError, match="passphrase"):
        create_encrypted_workspace_backup(workspace, passphrase="")


def test_create_encrypted_workspace_backup_deletes_plaintext_zip_on_success(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "memory.md").write_text("# Memory\nnote", encoding="utf-8")

    calls = []

    def fake_opener(cmd, *, input, capture_output, text):
        calls.append((cmd, input))
        # Simulate gpg by writing a placeholder encrypted file.
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_bytes(b"fake-encrypted-bytes")
        return _FakeGpgResult(returncode=0)

    encrypted_path = create_encrypted_workspace_backup(workspace, passphrase="hunter2", opener=fake_opener)

    assert encrypted_path.name.endswith(".zip.gpg")
    assert encrypted_path.is_file()
    assert not encrypted_path.with_name(encrypted_path.name[: -len(".gpg")]).exists()  # plaintext zip gone
    assert calls[0][1] == "hunter2"
    assert "--symmetric" in calls[0][0]
    assert "hunter2" not in calls[0][0]  # passphrase passed via stdin, never argv


def test_create_encrypted_workspace_backup_raises_on_gpg_failure_and_still_cleans_up(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")

    def failing_opener(cmd, *, input, capture_output, text):
        return _FakeGpgResult(returncode=2, stderr="gpg: bad things happened")

    with pytest.raises(BackupEncryptionError, match="gpg encryption failed"):
        create_encrypted_workspace_backup(workspace, passphrase="hunter2", opener=failing_opener)

    # The plaintext zip must not linger even when encryption fails.
    backup_dir = workspace / "outputs" / "backups"
    assert not any(backup_dir.glob("*.zip"))


def test_decrypt_workspace_backup_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BackupEncryptionError, match="not found"):
        decrypt_workspace_backup(tmp_path / "missing.zip.gpg", passphrase="hunter2")


def test_decrypt_workspace_backup_uses_stdin_for_passphrase(tmp_path: Path) -> None:
    encrypted_path = tmp_path / "backup.zip.gpg"
    encrypted_path.write_bytes(b"fake-encrypted-bytes")
    calls = []

    def fake_opener(cmd, *, input, capture_output, text):
        calls.append((cmd, input))
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"decrypted-zip-bytes")
        return _FakeGpgResult(returncode=0)

    output_path = decrypt_workspace_backup(encrypted_path, passphrase="hunter2", opener=fake_opener)

    assert output_path.name == "backup.zip"
    assert output_path.read_bytes() == b"decrypted-zip-bytes"
    assert calls[0][1] == "hunter2"


@requires_gpg
def test_encrypted_backup_round_trip_with_real_gpg(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")
    (workspace / "memory.md").write_text("# Memory\nsecret note", encoding="utf-8")

    encrypted_path = create_encrypted_workspace_backup(workspace, passphrase="correct horse battery staple")
    assert encrypted_path.is_file()
    assert encrypted_path.name.endswith(".zip.gpg")
    plaintext_zip = encrypted_path.with_name(encrypted_path.name[: -len(".gpg")])
    assert not plaintext_zip.exists()  # never lingers on disk

    with pytest.raises(BackupEncryptionError, match="gpg decryption failed"):
        decrypt_workspace_backup(encrypted_path, passphrase="wrong passphrase")

    decrypted_path = decrypt_workspace_backup(encrypted_path, passphrase="correct horse battery staple")
    report = inspect_backup(decrypted_path)
    assert report["file_count"] > 0
    with ZipFile(decrypted_path) as zf:
        assert "memory.md" in zf.namelist()
        assert "secret note" in zf.read("memory.md").decode("utf-8")
