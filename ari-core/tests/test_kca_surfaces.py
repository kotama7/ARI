"""Agent and human surfaces preserve the K/C/A authority boundary."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from typer.testing import CliRunner

from ari.cli import app
from ari.skill_manifest import load_skill_manifest


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {
    "register_skill",
    "promote_skill",
    "revoke_skill",
    "rewrite_knowledge_lock",
    "register_provider",
    "promote_provider",
    "revoke_provider",
    "rewrite_provider_lock",
    "rewrite_capability_binding",
    "register_harness",
    "promote_harness",
    "revoke_harness",
    "rewrite_harness_lock",
    "change_tolerance",
    "replace_oracle",
    "force_pass",
}


def _server(package: str):
    path = ROOT / package / "src" / "server.py"
    spec = importlib.util.spec_from_file_location(package.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_mcp_admin_surface_absent():
    expected = {
        "ari-skill-knowledge": {
            "search_knowledge_skills",
            "describe_knowledge_skill",
            "list_active_knowledge_skills",
            "request_knowledge_skill",
        },
        "ari-skill-harness": {
            "search_harnesses",
            "describe_harness",
            "request_auxiliary_verification",
            "read_attestation",
            "list_verification_requirements",
        },
    }
    for package, names in expected.items():
        manifest = load_skill_manifest(ROOT / package / "skill.yaml")
        declared = {item.name for item in manifest.tools}
        live = {item.name for item in asyncio.run(_server(package).list_tools())}
        assert declared == live == names
        assert not (declared & FORBIDDEN)
        assert manifest.enabled_by_default is False
        assert manifest.credential_scopes == []


def test_mcp_requests_are_non_authoritative(monkeypatch):
    knowledge = _server("ari-skill-knowledge")
    monkeypatch.setattr(knowledge, "_admission", lambda _name: {"run_id": "run-1"})
    monkeypatch.setattr(knowledge, "_catalog_entries", lambda: [])
    result = asyncio.run(knowledge.call_tool(
        "request_knowledge_skill", {"skill_id": "x", "reason": "test"}
    ))
    assert '"authoritative": false' in result[0].text
    assert "fixed-knowledge-binder-required" in result[0].text

    harness = _server("ari-skill-harness")
    monkeypatch.setattr(harness, "_admission", lambda _name: {
        "run_id": "run-1",
        "verification_contract_digest": "sha256:" + "1" * 64,
        "active_harness_lock_digest": "sha256:" + "2" * 64,
    })
    result = asyncio.run(harness.call_tool("request_auxiliary_verification", {
        "property_id": "numerical-equivalence",
        "method": "differential-testing",
        "reason": "test",
        "harness_hint": "attacker/chosen",
    }))
    assert '"authoritative": false' in result[0].text
    assert '"non_authoritative_harness_hint": "attacker/chosen"' in result[0].text


def test_three_catalog_cli_surfaces_are_separate():
    runner = CliRunner()
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    for group in ("knowledge", "provider", "harness"):
        assert group in top.output
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0
        assert not any(name in result.output for name in FORBIDDEN)
    assert "Capability Provider" in runner.invoke(app, ["provider", "--help"]).output
    assert "non-executable Knowledge" in runner.invoke(app, ["knowledge", "--help"]).output


def test_harness_suite_cli_cannot_actor_select_execution():
    result = CliRunner().invoke(app, ["harness", "suite", "run"])
    assert result.exit_code != 0
    assert "Fixed Verifier" in result.output
