"""Golden-snapshot guards for the four ARI stable contract surfaces (subtask 034).

Contract catalog: ``docs/refactoring/010_contract_preservation_policy.md``.

These verify that the live tree still matches the committed goldens under
``ari-core/tests/fixtures/contracts/`` — the single reviewable "contract diff"
surface later refactor subtasks must not silently drift:

  * public API  (``ari.public.*`` exported symbol tables)     — exact set
  * CLI tree    (``ari = ari.cli:app`` Typer surface)          — structural
  * MCP catalog (14 ``ari-skill-*/src/server.py`` tool names)  — exact set + no
                 new cross-skill name collision (flat-namespace clobber guard)
  * viz REST    (dashboard endpoint inventory + response keys) — literal drift
                 (exact) + additive/subset response-key contract

Single source of truth: this module imports the ``build_*`` / ``compare`` helpers
from ``scripts/snapshot_contracts.py`` so ``pytest`` and
``python scripts/snapshot_contracts.py --check`` can never disagree. When a
surface changes intentionally, regenerate with
``python scripts/snapshot_contracts.py --surface <x> --update``.

The suite runs fully in-process and never launches an MCP skill server
(``pytest.ini`` documents that importing two skills' ``src.server`` in one
process is ambiguous); the MCP catalog is captured by AST.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GEN_PATH = _REPO_ROOT / "scripts" / "snapshot_contracts.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("snapshot_contracts", _GEN_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GEN_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load_generator()


# ── generic self-consistency: golden == fresh build for every surface ────────

@pytest.mark.parametrize("surface", sc.SURFACES)
def test_golden_matches_live(surface):
    """Every golden equals a fresh in-process build (pytest == --check)."""
    fixture = sc._fixture_path(surface)
    assert fixture.exists(), (
        f"missing golden {fixture.relative_to(_REPO_ROOT)}; "
        f"run `python scripts/snapshot_contracts.py --surface {surface} --update`"
    )
    drift = sc.compare(surface, sc.load_golden(surface), sc.build(surface))
    assert not drift, "contract snapshot drift:\n" + "\n".join(drift)


# ── public API: exact per-submodule symbol tables ───────────────────────────

def test_public_api_submodules_present():
    golden = sc.load_golden("public")["symbols"]
    expected = {f"ari.public.{m}" for m in sc._PUBLIC_SUBMODULES}
    assert set(golden) == expected, "public_api.json submodule set drifted"
    # Spot-check load-bearing exports from 010 §2 are recorded.
    assert "CONCEPT_INVARIANTS" in golden["ari.public.claim_gate"]
    assert "PathManager" in golden["ari.public.paths"]
    assert "LLMClient" in golden["ari.public.llm"]
    for sym in ("ARIConfig", "LLMConfig", "EvaluatorConfig"):
        assert sym in golden["ari.public.config_schema"]
    for sym in ("build_verified_context", "render_grounded_block",
                "write_verified_context"):
        assert sym in golden["ari.public.verified_context"]


# ── CLI: the 11 commands + 4 sub-typers (incl. nested registry token) ────────

def test_cli_command_tree():
    root = sc.load_golden("cli")["root"]["commands"]
    commands = {k for k, v in root.items() if v["type"] == "command"}
    groups = {k for k, v in root.items() if v["type"] == "group"}
    assert commands == {
        "clone", "run", "resume", "paper", "status", "skills-list",
        "viz", "projects", "show", "delete", "settings",
    }
    assert groups == {"memory", "ear", "registry", "migrate"}
    # Nested typer must survive the broad try/except import guards (010 §1).
    assert "token" in root["registry"]["commands"]
    assert set(root["registry"]["commands"]["token"]["commands"]) == {
        "issue", "revoke", "list",
    }


def test_cli_env_side_effects_recorded():
    env = sc.load_golden("cli")["env_side_effects"]
    assert "ARI_IDEA_VIRSCI_REAL" in env["run"]
    assert "ARI_RUBRIC" in env["paper"]
    assert "ARI_FEWSHOT_MODE" in env["paper"]


# ── MCP: 59 FastMCP + 28 low-level defs (86 unique names) + collision guard ──

def test_mcp_tool_counts_and_names():
    golden = sc.load_golden("mcp")
    skills = golden["skills"]
    assert set(skills) == {
        "ari-skill-benchmark", "ari-skill-coding", "ari-skill-evaluator",
        "ari-skill-hpc", "ari-skill-idea", "ari-skill-memory",
        "ari-skill-orchestrator", "ari-skill-paper", "ari-skill-paper-re",
        "ari-skill-plot", "ari-skill-replicate", "ari-skill-transform",
        "ari-skill-vlm", "ari-skill-web",
    }, f"MCP skill package set drifted: {sorted(skills)}"
    fastmcp = [t for tools in skills.values() for t in tools if t["idiom"] == "fastmcp"]
    lowlevel = [t for tools in skills.values() for t in tools if t["idiom"] == "lowlevel"]
    assert len(fastmcp) == 59, f"expected 59 FastMCP tools, got {len(fastmcp)}"
    assert len(lowlevel) == 28, f"expected 28 low-level tool defs, got {len(lowlevel)}"
    unique = {t["name"] for tools in skills.values() for t in tools}
    assert len(unique) == 86, f"expected 86 unique tool names, got {len(unique)}"
    assert golden["invariants"]["return_envelope"] == ["error", "result"]
    assert golden["invariants"]["fq_name_pattern"] == "mcp__<skill>__<tool>"


def test_mcp_no_unrecorded_cross_skill_collision():
    """The flat-namespace clobber: only recorded collisions are allowed."""
    fresh = sc.build_mcp_static()
    seen: dict[str, set[str]] = {}
    for skill, tools in fresh["skills"].items():
        for tool in tools:
            seen.setdefault(tool["name"], set()).add(skill)
    duplicates = {n for n, owners in seen.items() if len(owners) > 1}
    recorded = set(sc.load_golden("mcp")["known_collisions"])
    assert duplicates == recorded, (
        "cross-skill MCP tool-name collisions changed "
        f"(fresh={sorted(duplicates)} recorded={sorted(recorded)}); "
        "run `python scripts/snapshot_contracts.py --surface mcp --update`"
    )
    # The one known collision is read_file (coding + orchestrator, both low-level).
    assert recorded == {"read_file"}


# ── viz: route-literal drift (exact) + additive/subset response keys ─────────

def test_viz_route_literals_no_drift():
    golden = set(sc.load_golden("viz")["resolvable_path_literals"])
    fresh = set(sc.build_viz()["resolvable_path_literals"])
    assert fresh == golden, (
        "routes.py self.path literals drifted "
        f"(added={sorted(fresh - golden)} removed={sorted(golden - fresh)}); "
        "run `python scripts/snapshot_contracts.py --surface viz --update`"
    )


def test_viz_endpoint_inventory_shape():
    endpoints = sc.load_golden("viz")["endpoints"]
    assert endpoints, "viz endpoint inventory is empty"
    for ep in endpoints:
        assert set(ep) == {"method", "path", "owner"}
        assert ep["method"] in ("GET", "POST")
    paths_by_method = {(e["method"], e["path"]) for e in endpoints}
    for critical in (
        ("GET", "/state"),
        ("GET", "/api/settings"),
        ("GET", "/api/checkpoints"),
        ("POST", "/api/launch"),
    ):
        assert critical in paths_by_method, f"missing critical endpoint {critical}"


def test_viz_settings_response_keys_are_subset_of_live(monkeypatch):
    """Additive/subset: recorded /api/settings keys ⊆ live response (010 §4 B).

    Mirrors ari-core/tests/test_api_schema_contract.py (the canonical guard);
    does not fork it.
    """
    from ari.viz import api_settings
    from ari.viz import state as _st

    monkeypatch.setattr(_st, "_settings_path", None, raising=False)
    live = api_settings._api_get_settings()
    recorded = sc.load_golden("viz")["response_keys"]["GET /api/settings"]
    missing = [k for k in recorded if k not in live]
    assert not missing, f"/api/settings dropped recorded contract keys: {missing}"
