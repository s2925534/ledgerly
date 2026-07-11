from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from researchboss.api.app import create_app
from researchboss.core.yamlio import read_yaml
from researchboss.engine.workspace import init_workspace


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_health_route_has_no_workspace_or_auth_dependency(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_project_status_returns_error_envelope_for_unknown_workspace(client: TestClient, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    response = client.get("/api/v1/projects/status", params={"workspace": str(missing)})

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["data"] is None
    assert body["errors"][0]["code"] == "workspace_not_found"


def test_project_status_and_health_use_shared_engine_functions(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    status_response = client.get("/api/v1/projects/status", params={"workspace": str(workspace)})
    health_response = client.get("/api/v1/projects/health", params={"workspace": str(workspace)})

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["ok"] is True
    assert "accepted" in status_body["data"] or isinstance(status_body["data"], dict)

    assert health_response.status_code == 200
    assert health_response.json()["ok"] is True


def test_project_init_creates_workspace_via_api(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "new-workspace"

    response = client.post(
        "/api/v1/projects/init",
        json={
            "workspace": str(workspace),
            "project_name": "API Project",
            "project_type": "M.Phil",
            "topic": "API topic",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    context = read_yaml(workspace / "research-context.yaml")
    assert context["project"]["name"] == "API Project"


def test_project_init_rejects_already_initialized_workspace(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    response = client.post(
        "/api/v1/projects/init",
        json={
            "workspace": str(workspace),
            "project_name": "Should not overwrite",
            "project_type": "M.Phil",
            "topic": "",
        },
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "workspace_already_exists"
    context = read_yaml(workspace / "research-context.yaml")
    assert context["project"]["name"] == "Test"  # original workspace untouched


def test_doc_version_route_never_modifies_the_target_file(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    target = workspace / "artefacts" / "notes" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_text = "line one\n"
    target.write_text(original_text, encoding="utf-8")

    response = client.post(
        "/api/v1/doc/version",
        params={"workspace": str(workspace)},
        json={"target": str(target)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["version_id"] == "docv-001"
    assert target.read_text(encoding="utf-8") == original_text


def test_doc_versions_diff_compare_and_restore_via_api(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    target = workspace / "artefacts" / "notes" / "draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line one\n", encoding="utf-8")

    first = client.post("/api/v1/doc/version", params={"workspace": str(workspace)}, json={"target": str(target)})
    target.write_text("line one\nline two\n", encoding="utf-8")
    second = client.post("/api/v1/doc/version", params={"workspace": str(workspace)}, json={"target": str(target)})
    assert first.status_code == 200 and second.status_code == 200

    versions = client.get(
        "/api/v1/doc/versions", params={"workspace": str(workspace), "target": str(target)}
    )
    assert versions.status_code == 200
    assert [row["version_id"] for row in versions.json()["data"]] == ["docv-001", "docv-002"]

    diff = client.get(
        "/api/v1/doc/diff",
        params={"workspace": str(workspace), "version_id_a": "docv-001", "version_id_b": "docv-002"},
    )
    assert diff.status_code == 200
    assert diff.json()["data"]["diff_supported"] is True

    compare = client.get(
        "/api/v1/doc/compare",
        params={"workspace": str(workspace), "version_id_a": "docv-001", "version_id_b": "docv-002"},
    )
    assert compare.status_code == 200
    assert compare.json()["data"]["comparable"] is False

    restore = client.post(
        "/api/v1/doc/restore",
        params={"workspace": str(workspace)},
        json={"version_id": "docv-001"},
    )
    assert restore.status_code == 200
    restored_data = restore.json()["data"]
    assert restored_data["restored_from_version_id"] == "docv-001"
    assert Path(restored_data["restored_to_path"]).read_text(encoding="utf-8") == "line one\n"
    assert target.read_text(encoding="utf-8") == "line one\nline two\n"  # current document untouched


def test_doc_diff_unknown_version_returns_404_error_envelope(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    response = client.get(
        "/api/v1/doc/diff",
        params={"workspace": str(workspace), "version_id_a": "docv-999", "version_id_b": "docv-998"},
    )

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "unknown_document_version"
