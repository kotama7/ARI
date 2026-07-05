"""Unit + smoke + determinism tests for ``scripts/check_dead_code.py`` (055).

Covers ``docs/refactoring/subtasks/055_add_dead_code_candidate_checker.md`` §12:

  (a) precedence -- a PUBLIC_CONTRACT node (route / MCP tool) with no static
      importer stays PUBLIC_CONTRACT; a dynamic-seam file stays DYNAMIC;
  (b) the hard-downgrade rule -- an orphan symbol in a production-live module is
      LIVE (not a candidate); an orphan in an orphan module WITHOUT ruff
      corroboration is REVIEW_REQUIRED, never SAFE_DELETE;
  (c) SAFE_DELETE requires ruff corroboration (or the config opt-out), and a
      net-new SAFE_DELETE trips ``--check`` exit 1 while the allowlist suppresses
      it (exit 0);
  (d) TEST_ONLY / under-traced-seam classification;
  (e) missing/malformed graph -> ``SystemExit(2)``;
  (f) determinism -- two runs on the same graph are byte-identical;
  (g) repo smoke -- the 013 §7 deletion firewall holds against the real graph.

Deterministic, no network, no LLM (ARI design principle P2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_dead_code as cdc  # noqa: E402

REPO_ROOT = cdc.REPO_ROOT
REPO_GRAPH = REPO_ROOT / "scripts" / "quality" / "baselines" / "reference_graph.json"


def _cfg(**overrides) -> dict:
    """A defaults-backed config dict with optional (possibly nested) overrides."""
    cfg = cdc.load_config(Path("/nonexistent-check-dead-code-config"))
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            merged = dict(cfg[key])
            merged.update(val)
            cfg[key] = merged
        else:
            cfg[key] = val
    return cfg


def _node(nid, kind, file, loc=1, reachable_from=None, edges_in=None) -> dict:
    return {
        "id": nid, "kind": kind, "file": file, "loc": loc,
        "reachable_from": list(reachable_from or []),
        "edges_in": list(edges_in or []),
    }


def _graph(nodes, collisions=None) -> dict:
    return {
        "schema_version": 1, "generated_at": "2026-07-01T00:00:00+00:00",
        "commit": "deadbeef", "roots": [], "nodes": nodes, "edges": [],
        "collisions": collisions or [],
    }


def _by_id(cands):
    return {c.id: c for c in cands}


# ── (a) precedence: PUBLIC_CONTRACT / DYNAMIC never dead ─────────────────────

def test_route_and_mcp_are_public_contract_without_importer():
    nodes = [
        _node("route:/api/state", "route", "ari-core/ari/viz", 0, edges_in=["cross_lang.http"]),
        _node("mcp.tool:paper:generate_section", "mcp.tool",
              "ari-skill-paper/src/server.py", 1, reachable_from=["R4"], edges_in=["dynamic.mcp"]),
        _node("py.module:ari-core/ari/public/llm.py", "py.module",
              "ari-core/ari/public/llm.py", 10),  # orphan but public/
        _node("ts.module:ari-core/ari/viz/frontend/src/services/api.ts", "ts.module",
              "ari-core/ari/viz/frontend/src/services/api.ts", 800),  # R8 entry, orphan
    ]
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), {}))
    assert got["route:/api/state"].classification == cdc.PUBLIC_CONTRACT
    assert got["mcp.tool:paper:generate_section"].classification == cdc.PUBLIC_CONTRACT
    assert got["py.module:ari-core/ari/public/llm.py"].classification == cdc.PUBLIC_CONTRACT
    assert got["ts.module:ari-core/ari/viz/frontend/src/services/api.ts"].classification == cdc.PUBLIC_CONTRACT


def test_dynamic_seam_prompt_and_backend_are_dynamic():
    nodes = [
        _node("data.file:ari-core/ari/prompts/agent/system.md", "data.file",
              "ari-core/ari/prompts/agent/system.md", 14),  # orphan, seam path
        _node("py.module:ari-core/ari/publish/backends/zenodo.py", "py.module",
              "ari-core/ari/publish/backends/zenodo.py", 139, edges_in=["dynamic.string_key"]),
        # skill-local prompt with NO edge -- caught by the seam path, not edges_in
        _node("data.file:ari-skill-replicate/src/prompts/skeleton.md", "data.file",
              "ari-skill-replicate/src/prompts/skeleton.md", 144),
    ]
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), {}))
    assert all(c.classification == cdc.DYNAMIC_REFERENCE_RISK for c in got.values())


# ── (b) hard-downgrade rule ─────────────────────────────────────────────────

def test_orphan_symbol_in_live_module_is_live_not_candidate():
    nodes = [
        _node("py.module:ari-core/ari/foo.py", "py.module", "ari-core/ari/foo.py",
              120, reachable_from=["R1"], edges_in=["static.import"]),
        _node("py.symbol:ari-core/ari/foo.py:helper", "py.symbol",
              "ari-core/ari/foo.py", 8),  # orphan symbol, live module
    ]
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), {}))
    assert got["py.symbol:ari-core/ari/foo.py:helper"].classification == cdc.LIVE


def test_orphan_in_orphan_module_without_ruff_is_review_not_delete():
    nodes = [
        _node("py.module:ari-core/ari/foo.py", "py.module", "ari-core/ari/foo.py", 120),
        _node("py.symbol:ari-core/ari/foo.py:junk", "py.symbol", "ari-core/ari/foo.py", 8),
    ]
    # require_ruff_corroboration is True by default; empty ruff index.
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), {}))
    sym = got["py.symbol:ari-core/ari/foo.py:junk"]
    assert sym.classification == cdc.REVIEW_REQUIRED
    assert sym.reason == "unresolved"
    # the module itself (loc 120 > max_loc 40) is also not deletable
    assert got["py.module:ari-core/ari/foo.py"].classification == cdc.REVIEW_REQUIRED


# ── (c) SAFE_DELETE needs ruff (or opt-out); --check ratchet ────────────────

def test_safe_delete_requires_ruff_corroboration():
    nodes = [
        _node("py.module:ari-core/ari/foo.py", "py.module", "ari-core/ari/foo.py", 120),
        _node("py.symbol:ari-core/ari/foo.py:junk", "py.symbol", "ari-core/ari/foo.py", 8),
    ]
    ruff = {"ari-core/ari/foo.py": {"junk"}}
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), ruff))
    assert got["py.symbol:ari-core/ari/foo.py:junk"].classification == cdc.SAFE_DELETE_CANDIDATE
    # opt-out: no ruff needed when corroboration is disabled
    cfg = _cfg(safe_delete={"require_ruff_corroboration": False})
    got2 = _by_id(cdc.classify_all(_graph(nodes), cfg, {}))
    assert got2["py.symbol:ari-core/ari/foo.py:junk"].classification == cdc.SAFE_DELETE_CANDIDATE


def _write_check_fixture(tmp_path: Path) -> tuple[Path, Path]:
    nodes = [
        _node("py.module:ari-core/ari/foo.py", "py.module", "ari-core/ari/foo.py", 120),
        _node("py.symbol:ari-core/ari/foo.py:junk", "py.symbol", "ari-core/ari/foo.py", 8),
    ]
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_graph(nodes)), encoding="utf-8")
    cfg = tmp_path / "cfg.yaml"
    # JSON is valid YAML -- disable ruff corroboration so the orphan is SAFE_DELETE.
    cfg.write_text(json.dumps({"safe_delete": {"require_ruff_corroboration": False}}),
                   encoding="utf-8")
    return graph, cfg


def test_check_ratchet_exit_codes(tmp_path: Path):
    graph, cfg = _write_check_fixture(tmp_path)
    out = tmp_path / "r.md"
    base = ["--graph", str(graph), "--config", str(cfg), "--no-ruff",
            "--output", str(out), "--allow", str(tmp_path / "missing.allow.yaml")]
    # warning-mode-first: default posture reports and exits 0
    assert cdc.main(base) == 0
    # --check: a net-new SAFE_DELETE over budget fails
    assert cdc.main(base + ["--check"]) == 1
    # allowlist suppresses the known candidate -> exit 0
    allow = tmp_path / "seed.allow.yaml"
    allow.write_text(json.dumps({"known": [{"id": "py.symbol:ari-core/ari/foo.py:junk"}]}),
                     encoding="utf-8")
    assert cdc.main(["--graph", str(graph), "--config", str(cfg), "--no-ruff",
                     "--output", str(out), "--allow", str(allow), "--check"]) == 0
    # --warning-only never fails even with a net-new candidate
    assert cdc.main(base + ["--warning-only"]) == 0


# ── (d) TEST_ONLY + under-traced seam ───────────────────────────────────────

def test_schemas_loader_is_test_only_and_skill_helper_is_under_traced():
    nodes = [
        _node("py.symbol:ari-core/ari/schemas/__init__.py:load", "py.symbol",
              "ari-core/ari/schemas/__init__.py", 5),
        _node("py.module:ari-skill-idea/src/snapshot.py", "py.module",
              "ari-skill-idea/src/snapshot.py", 550),
    ]
    got = _by_id(cdc.classify_all(_graph(nodes), _cfg(), {}))
    assert got["py.symbol:ari-core/ari/schemas/__init__.py:load"].classification == cdc.TEST_ONLY
    seam = got["py.module:ari-skill-idea/src/snapshot.py"]
    assert seam.classification == cdc.REVIEW_REQUIRED
    assert seam.reason == "under_traced_seam"


# ── (e) malformed / missing graph -> exit 2 ─────────────────────────────────

def test_missing_graph_exits_2(tmp_path: Path):
    with pytest.raises(SystemExit) as ei:
        cdc.load_graph(tmp_path / "nope.json")
    assert ei.value.code == 2


def test_bad_schema_version_exits_2(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "nodes": [], "edges": [], "roots": []}),
                   encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        cdc.load_graph(bad)
    assert ei.value.code == 2


# ── (f) determinism ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not REPO_GRAPH.exists(), reason="053/054 reference graph not built")
def test_determinism_repo():
    graph = cdc.load_graph(REPO_GRAPH)
    cfg = _cfg()
    r1 = cdc.render_json(cdc.to_report(graph, cdc.classify_all(graph, cfg, {}), {**cfg, "graph": "g"}))
    r2 = cdc.render_json(cdc.to_report(graph, cdc.classify_all(graph, cfg, {}), {**cfg, "graph": "g"}))
    assert r1 == r2


# ── (g) repo smoke: the 013 §7 deletion firewall holds ──────────────────────

@pytest.mark.skipif(not REPO_GRAPH.exists(), reason="053/054 reference graph not built")
def test_repo_firewall_holds():
    graph = cdc.load_graph(REPO_GRAPH)
    cands = cdc.classify_all(graph, _cfg(), {})  # no ruff -> most conservative
    checks = cdc.firewall_checks(cands)
    failed = [name for name, ok, _ref in checks if not ok]
    assert not failed, f"firewall checks failed: {failed}"
    by_id = _by_id(cands)
    # spot-check the load-bearing expectations (055 §13.4)
    for be in ("ari_registry", "local_tarball", "zenodo", "gh"):
        nid = f"py.module:ari-core/ari/publish/backends/{be}.py"
        assert by_id[nid].classification == cdc.DYNAMIC_REFERENCE_RISK
    assert by_id["py.symbol:ari-core/ari/schemas/__init__.py:load"].classification == cdc.TEST_ONLY
    assert by_id["py.module:ari-core/ari/__init__.py"].classification != cdc.SAFE_DELETE_CANDIDATE
    assert by_id["py.module:ari-core/ari/public/__init__.py"].classification != cdc.SAFE_DELETE_CANDIDATE
    # no contract/dynamic surface ever lands in SAFE_DELETE
    assert not [c for c in cands if c.classification == cdc.SAFE_DELETE_CANDIDATE]
