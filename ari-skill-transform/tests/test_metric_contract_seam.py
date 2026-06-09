"""Integration seam: the run-level metric_contract make_metric_spec persists is
read back by nodes_to_science_data (via _load_run_metric_contract) and reaches the
hard gate through science_data -- the link that was previously DEAD (metric_contract
never propagated to science_data.json, so the declared contract and
claim_evidence_missing were inert on every real run).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from server import _load_run_metric_contract, mcp  # noqa: E402


def test_nodes_to_science_data_is_a_registered_mcp_tool():
    # regression: adding _load_run_metric_contract directly BEFORE the @mcp.tool()
    # decorator once STOLE the decorator, dropping nodes_to_science_data from the
    # skill's tool list (the paper pipeline's transform_data stage then failed with
    # "Tool 'nodes_to_science_data' not found", cascading to no science_data -> the
    # hard gate never ran). The helper must NOT be a tool; the entrypoint MUST be.
    import asyncio
    names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert "nodes_to_science_data" in names
    assert "_load_run_metric_contract" not in names


def test_load_run_metric_contract_reads_sibling(tmp_path):
    (tmp_path / "metric_contract.json").write_text(json.dumps(
        {"key": "tput",
         "claims": [{"claim": "M helps", "required_evidence": ["m_on", "m_off"]}]}))
    mc = _load_run_metric_contract(str(tmp_path / "tree.json"))
    assert mc is not None
    assert mc["claims"][0]["required_evidence"] == ["m_on", "m_off"]


def test_load_run_metric_contract_absent_is_none(tmp_path):
    assert _load_run_metric_contract(str(tmp_path / "tree.json")) is None  # no file


def test_load_run_metric_contract_bad_json_is_none(tmp_path):
    (tmp_path / "metric_contract.json").write_text("{not valid json")
    assert _load_run_metric_contract(str(tmp_path / "tree.json")) is None


def test_seam_metric_contract_reaches_gate(tmp_path):
    # End-to-end seam (no LLM, no hand-injection): contract persisted next to
    # tree.json -> loaded by the transform helper -> placed on science_data exactly
    # as nodes_to_science_data does -> the hard gate flags a declared claim whose
    # required_evidence the run never emitted (the CSR-SpMM Page-Shaping case).
    import pytest
    contract = pytest.importorskip("ari.pipeline.claim_gate.contract")
    (tmp_path / "metric_contract.json").write_text(json.dumps(
        {"key": "tput", "claims": [
            {"claim": "page-shaping controller helps reach-limited regimes",
             "required_evidence": ["thp_on_tput", "thp_off_tput"]}]}))
    mc = _load_run_metric_contract(str(tmp_path / "tree.json"))
    science_data = {  # == what nodes_to_science_data builds: out["metric_contract"] = mc
        "metric_contract": mc,
        "configurations": [{"config_id": "c", "measurements": {"tput": 100.0, "K": 8.0}}],
    }
    fs = contract.check_contract(science_data)
    assert [f["type"] for f in fs] == ["claim_evidence_missing"]
