from pathlib import Path

from researchboss.core.yamlio import read_yaml
from researchboss.engine.claims import add_claim, citation_gap_claims, list_claims, write_citation_gap_report
from researchboss.engine.workspace import init_workspace


def test_claim_ledger_and_citation_gap_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test Project", project_type="M.Phil", topic="")

    supported = add_claim(workspace, text="Supported claim", linked_sources=["source-001"])
    unsupported = add_claim(workspace, text="Unsupported claim")
    output_path = write_citation_gap_report(workspace)

    assert supported["id"] == "claim-001"
    assert unsupported["id"] == "claim-002"
    assert [claim["id"] for claim in list_claims(workspace)] == ["claim-001", "claim-002"]
    assert [claim["id"] for claim in citation_gap_claims(workspace)] == ["claim-002"]
    report = read_yaml(output_path)
    assert report["gap_count"] == 1
    assert report["claims"][0]["text"] == "Unsupported claim"
