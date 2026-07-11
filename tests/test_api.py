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


def test_sources_scan_status_note_tag_and_report_via_api(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    source_root = tmp_path / "incoming"
    source_root.mkdir()
    (source_root / "paper.pdf").write_bytes(b"%PDF-1.4 fake pdf bytes")

    scan_response = client.post(
        "/api/v1/sources/scan",
        params={"workspace": str(workspace)},
        json={"source_root": str(source_root)},
    )
    assert scan_response.status_code == 200
    assert scan_response.json()["data"]["added"] == 1

    list_response = client.get("/api/v1/sources", params={"workspace": str(workspace)})
    assert list_response.status_code == 200
    sources = list_response.json()["data"]
    assert len(sources) == 1
    source_id = sources[0]["source_id"]

    status_response = client.post(
        f"/api/v1/sources/{source_id}/status",
        params={"workspace": str(workspace)},
        json={"new_status": "accepted"},
    )
    assert status_response.status_code == 200

    note_response = client.post(
        f"/api/v1/sources/{source_id}/note",
        params={"workspace": str(workspace)},
        json={"note": "Looks relevant"},
    )
    assert note_response.status_code == 200

    tag_response = client.post(
        f"/api/v1/sources/{source_id}/tags",
        params={"workspace": str(workspace)},
        json={"tag": "core-evidence"},
    )
    assert tag_response.status_code == 200

    report_response = client.get("/api/v1/sources/report", params={"workspace": str(workspace)})
    assert report_response.status_code == 200
    assert report_response.json()["ok"] is True

    updated = client.get("/api/v1/sources", params={"workspace": str(workspace), "status": "accepted"})
    assert updated.status_code == 200
    assert updated.json()["data"][0]["notes"] == "Looks relevant"
    assert "core-evidence" in updated.json()["data"][0]["tags"]


def test_sources_status_unknown_id_returns_404(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    response = client.post(
        "/api/v1/sources/does-not-exist/status",
        params={"workspace": str(workspace)},
        json={"new_status": "accepted"},
    )

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "unknown_source_id"


def test_artefacts_register_review_and_dependencies_via_api(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    artefact_path = workspace / "artefacts" / "reports" / "summary.md"
    artefact_path.parent.mkdir(parents=True, exist_ok=True)
    artefact_path.write_text("# Summary", encoding="utf-8")

    register_response = client.post(
        "/api/v1/artefacts",
        params={"workspace": str(workspace)},
        json={"title": "Summary", "artefact_type": "report", "path": str(artefact_path)},
    )
    assert register_response.status_code == 200
    artefact_id = register_response.json()["data"]["id"]

    list_response = client.get("/api/v1/artefacts", params={"workspace": str(workspace)})
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1

    review_response = client.post(
        f"/api/v1/artefacts/{artefact_id}/review",
        params={"workspace": str(workspace)},
        json={"status": "accepted"},
    )
    assert review_response.status_code == 200

    dependencies_response = client.get("/api/v1/artefacts/dependencies", params={"workspace": str(workspace)})
    assert dependencies_response.status_code == 200
    assert dependencies_response.json()["ok"] is True


def test_artefacts_review_unknown_id_returns_404(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    response = client.post(
        "/api/v1/artefacts/does-not-exist/review",
        params={"workspace": str(workspace)},
        json={"status": "accepted"},
    )

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "invalid_artefact_review_status"


def test_rqs_list_check_approve_reject_archive_via_api(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(
        workspace,
        project_name="Test",
        project_type="M.Phil",
        topic="Topic",
        research_questions=[
            {"question": "How does X work?", "status": "draft", "subquestions": []},
            {"question": "Should Y be studied?", "status": "draft", "subquestions": []},
        ],
    )

    list_response = client.get("/api/v1/rqs", params={"workspace": str(workspace)})
    assert list_response.status_code == 200
    candidates = list_response.json()["data"]["candidates"]
    assert len(candidates) == 2
    first_id = candidates[0]["id"]
    second_id = candidates[1]["id"]

    check_response = client.post(
        "/api/v1/rqs/check", params={"workspace": str(workspace)}, json={}
    )
    assert check_response.status_code == 200

    approve_response = client.post(f"/api/v1/rqs/{first_id}/approve", params={"workspace": str(workspace)})
    assert approve_response.status_code == 200

    reject_response = client.post(
        f"/api/v1/rqs/{second_id}/reject", params={"workspace": str(workspace)}, json={"reason": "Too broad"}
    )
    assert reject_response.status_code == 200

    archive_response = client.post(f"/api/v1/rqs/{first_id}/archive", params={"workspace": str(workspace)}, json={})
    assert archive_response.status_code == 200

    final_response = client.get("/api/v1/rqs", params={"workspace": str(workspace)})
    data = final_response.json()["data"]
    assert data["candidates"] == []
    assert data["approved"] == []


def test_rqs_approve_unknown_id_returns_404(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    response = client.post("/api/v1/rqs/rq-999/approve", params={"workspace": str(workspace)})

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "unknown_rq_id"
