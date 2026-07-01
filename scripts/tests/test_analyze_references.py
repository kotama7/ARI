"""Unit + smoke + determinism tests for ``scripts/analyze_references.py``.

Covers subtask ``docs/refactoring/subtasks/054_add_reference_graph_analyzer.md``
§8 item 10:

  (a) a string-keyed factory fixture emits a ``dynamic.string_key`` edge with
      evidence, and the "orphan" target is NOT edge-less;
  (b) a two-skill fixture with a duplicate MCP tool name emits a collision;
  (c) a repo smoke test: the 4 ``publish/backends/*`` modules and the 11
      ``ari/prompts/**.md`` templates each have >=1 inbound dynamic edge (i.e.
      are NOT graph orphans despite having no static importer);
  (d) determinism: two runs on the same commit are byte-identical.

Deterministic, no network, no LLM (ARI design principle P2).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_references as ar  # noqa: E402

REPO_ROOT = ar.REPO_ROOT


def _fixture_config(**overrides) -> dict:
    cfg = {
        "scan_roots": ["scan"],
        "include_skills_glob": "ari-skill-*/src",
        "prompt_bases": [],
        "frontend_api_client": None,
        "viz_route_dir": None,
        "data_selectors": [],
        "ignore_globs": ["*/__pycache__/*", "*.pyc"],
    }
    cfg.update(overrides)
    return cfg


def _write(base: Path, rel: str, text: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── (a) string-keyed factory ────────────────────────────────────────────────

def test_string_key_factory_edge_has_evidence(tmp_path: Path) -> None:
    _write(tmp_path, "scan/__init__.py", "")
    _write(
        tmp_path,
        "scan/factory.py",
        "def load(name):\n"
        "    if name == 'alpha':\n"
        "        from .impls import alpha as backend\n"
        "    else:\n"
        "        raise ValueError(name)\n"
        "    return backend\n",
    )
    _write(tmp_path, "scan/impls/__init__.py", "")
    _write(tmp_path, "scan/impls/alpha.py", "def go():\n    return 1\n")

    graph = ar.build_graph(tmp_path, _fixture_config(), manifest=None)
    target = "py.module:scan/impls/alpha.py"
    edges_to_target = [e for e in graph["edges"] if e["to"] == target]
    dyn = [e for e in edges_to_target if e["kind"] == "dynamic.string_key"]
    assert dyn, "string-keyed factory did not produce a dynamic.string_key edge"
    assert all(e["evidence"] for e in dyn), "dynamic edge is missing evidence"
    assert "alpha" in dyn[0]["evidence"]
    # the statically-orphan target must NOT be edge-less
    node = next(n for n in graph["nodes"] if n["id"] == target)
    assert node["edges_in"], "orphan target has no inbound edge kinds"


# ── (b) MCP collision ───────────────────────────────────────────────────────

def test_duplicate_mcp_tool_name_reports_collision(tmp_path: Path) -> None:
    server = (
        "from mcp.server.fastmcp import FastMCP\n"
        "mcp = FastMCP('x')\n\n"
        "@mcp.tool()\n"
        "async def dup_tool():\n"
        "    return 'ok'\n"
    )
    _write(tmp_path, "ari-skill-x/src/server.py", server)
    _write(tmp_path, "ari-skill-y/src/server.py", server)

    graph = ar.build_graph(tmp_path, _fixture_config(scan_roots=[]), manifest=None)
    collisions = {c["tool_name"]: c["skills"] for c in graph["collisions"]}
    assert "dup_tool" in collisions, "duplicate MCP tool name not flagged"
    assert set(collisions["dup_tool"]) == {"x", "y"}
    # both handlers keyed by (skill, tool_name)
    tool_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "mcp.tool"}
    assert {"mcp.tool:x:dup_tool", "mcp.tool:y:dup_tool"} <= tool_ids


def test_low_level_tool_declaration_detected(tmp_path: Path) -> None:
    server = (
        "from mcp.types import Tool\n"
        "def list_tools():\n"
        "    return [Tool(name='run_bash', description='d', inputSchema={})]\n"
    )
    _write(tmp_path, "ari-skill-z/src/server.py", server)
    graph = ar.build_graph(tmp_path, _fixture_config(scan_roots=[]), manifest=None)
    tool_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "mcp.tool"}
    assert "mcp.tool:z:run_bash" in tool_ids


# ── (c) repo smoke ──────────────────────────────────────────────────────────

def _repo_graph() -> dict:
    cfg = ar.load_config(ar.DEFAULT_CONFIG_PATH)
    manifest = ar.load_roots_manifest(None)
    return ar.build_graph(REPO_ROOT, cfg, manifest)


def test_repo_dynamic_overlay_no_orphans() -> None:
    graph = _repo_graph()
    dyn_targets = {
        e["to"] for e in graph["edges"]
        if e["kind"].startswith(("dynamic.", "cross_lang."))
    }
    backends = [
        n for n in graph["nodes"]
        if n["kind"] == "py.module"
        and n["file"].startswith("ari-core/ari/publish/backends/")
        and not n["file"].endswith("__init__.py")
    ]
    assert len(backends) == 4
    assert all(n["id"] in dyn_targets for n in backends)

    prompts = [
        n for n in graph["nodes"]
        if n["kind"] == "data.file" and n["file"].startswith("ari-core/ari/prompts/")
    ]
    assert len(prompts) == 11
    assert all(n["id"] in dyn_targets for n in prompts)


def test_repo_mcp_tools_and_collision() -> None:
    graph = _repo_graph()
    tools = [n for n in graph["nodes"] if n["kind"] == "mcp.tool"]
    assert len(tools) == 87
    collisions = {c["tool_name"]: set(c["skills"]) for c in graph["collisions"]}
    assert collisions.get("read_file") == {"coding", "orchestrator"}


def test_repo_evidence_and_no_sonfigs() -> None:
    graph = _repo_graph()
    for e in graph["edges"]:
        if e["kind"] in ar._EVIDENCE_REQUIRED:
            assert e["evidence"], f"{e['kind']} edge lacks evidence"
    assert not any("sonfigs" in n["file"] for n in graph["nodes"])
    assert not any("sonfigs" in n["id"] for n in graph["nodes"])


def test_repo_schema_keys() -> None:
    graph = _repo_graph()
    assert set(graph) == {
        "schema_version", "generated_at", "commit",
        "roots", "nodes", "edges", "collisions",
    }
    assert graph["schema_version"] == ar.SCHEMA_VERSION


# ── (d) determinism ─────────────────────────────────────────────────────────

def test_determinism_repo() -> None:
    g1 = _repo_graph()
    g2 = _repo_graph()
    assert g1["nodes"] == g2["nodes"]
    assert g1["edges"] == g2["edges"]
    assert g1["collisions"] == g2["collisions"]
