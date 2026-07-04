#!/usr/bin/env python3
"""Deterministic generator/verifier for ARI contract snapshot fixtures.

Subtask 034 (``docs/refactoring/subtasks/034_add_contract_snapshot_fixtures.md``);
contract catalog: ``docs/refactoring/010_contract_preservation_policy.md``.

This script freezes the four ARI stable contract surfaces as committed, machine
diffable golden JSON fixtures under ``ari-core/tests/fixtures/contracts/`` and
verifies the live tree still matches them:

  * ``public``  -> ``public_api.json``    (``ari.public.*`` exported symbol tables)
  * ``cli``     -> ``cli_tree.json``      (the ``ari = ari.cli:app`` Typer surface)
  * ``mcp``     -> ``mcp_tools.json``      (14 ``ari-skill-*/src/server.py`` tool catalog)
  * ``viz``     -> ``viz_endpoints.json``  (dashboard REST inventory + response keys)

Design principle P2 (determinism): stdlib only (``ast``/``json``/``importlib``);
no LLM, no network, no timestamps/commit SHAs in the payload, so every
regeneration is byte-stable and diffs are meaningful.  The in-process surfaces
(public via import, cli via Typer introspection, mcp/viz via AST) never launch an
MCP skill server (``pytest.ini`` documents that importing two skills' ``src.server``
in one process is ambiguous).

Usage::

    python scripts/snapshot_contracts.py --surface all --check    # verify (default)
    python scripts/snapshot_contracts.py --surface public --update # regenerate

``ari-core/tests/test_contract_snapshots.py`` imports the ``build_*`` / ``compare``
helpers here so ``pytest`` and ``--check`` can never disagree (single source of
truth).  This script adds no third-party dependency and wires no CI gate (that is
subtasks 029/030/032/046).
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARI_CORE = REPO_ROOT / "ari-core"
FIXTURES_DIR = ARI_CORE / "tests" / "fixtures" / "contracts"
ARI_CORE_VERSION = "0.9.0"

# ari-core is normally editable-installed; make the import robust when run from a
# checkout where it is not on sys.path yet.
if str(ARI_CORE) not in sys.path:
    sys.path.insert(0, str(ARI_CORE))

SURFACES = ("public", "cli", "mcp", "viz")

# ---------------------------------------------------------------------------
# JSON emit helpers (byte-stable)
# ---------------------------------------------------------------------------


def dumps(obj: object) -> str:
    """Deterministic JSON text: sorted keys, unicode kept, trailing newline."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _meta(surface: str) -> dict:
    return {
        "generated_by": "scripts/snapshot_contracts.py",
        "surface": surface,
        "ari_core_version": ARI_CORE_VERSION,
        "note": (
            "regenerate with "
            f"scripts/snapshot_contracts.py --surface {surface} --update"
        ),
    }


def _fixture_path(surface: str) -> Path:
    return FIXTURES_DIR / {
        "public": "public_api.json",
        "cli": "cli_tree.json",
        "mcp": "mcp_tools.json",
        "viz": "viz_endpoints.json",
    }[surface]


# ---------------------------------------------------------------------------
# Surface: public API (in-process import, exact-set)
# ---------------------------------------------------------------------------

_PUBLIC_SUBMODULES = (
    "claim_gate",
    "config_schema",
    "container",
    "cost_tracker",
    "llm",
    "paths",
    "run_env",
    "verified_context",
)


def build_public() -> dict:
    """Per-submodule exported-symbol table for ``ari.public.*``.

    Keys on ``ari.public.<submodule>`` (``ari.public.__init__`` re-exports nothing
    at top level).  For the ``import *`` submodules (container, cost_tracker,
    run_env) the module's resolved ``__all__`` is captured, so a change in the
    underlying ``__all__`` is caught.
    """
    symbols: dict[str, list[str]] = {}
    for name in _PUBLIC_SUBMODULES:
        mod = importlib.import_module(f"ari.public.{name}")
        all_names = getattr(mod, "__all__", None)
        if all_names is None:
            all_names = [n for n in dir(mod) if not n.startswith("_")]
        symbols[f"ari.public.{name}"] = sorted(set(all_names))
    return {"schema_version": 1, "_meta": _meta("public"), "symbols": symbols}


# ---------------------------------------------------------------------------
# Surface: CLI tree (in-process Typer/Click introspection, structural)
# ---------------------------------------------------------------------------

# Curated flag->env-var side effects that Typer cannot expose (hand-maintained;
# grounded in the command sources on 2026-07-01):
#   ari-core/ari/cli/run.py:202-210        -> ARI_IDEA_VIRSCI_*
#   ari-core/ari/cli/projects.py:81-90     -> ARI_RUBRIC / ARI_FEWSHOT_MODE / ...
_CLI_ENV_SIDE_EFFECTS = {
    "paper": [
        "ARI_FEWSHOT_MODE",
        "ARI_NUM_REFLECTIONS",
        "ARI_NUM_REVIEWS_ENSEMBLE",
        "ARI_RUBRIC",
    ],
    "run": [
        "ARI_IDEA_VIRSCI_K",
        "ARI_IDEA_VIRSCI_N_AUTHORS",
        "ARI_IDEA_VIRSCI_N_PAPERS",
        "ARI_IDEA_VIRSCI_REAL",
        "ARI_IDEA_VIRSCI_TEAM_SIZE",
    ],
}

# Top-level ``ari`` subcommands registered under an import guard in
# ``ari-core/ari/cli/__init__.py`` (``try: … add_typer(…) except Exception``):
# ``memory`` (memory_cli), ``ear`` (cli_ear), ``registry`` (registry.cli). Each
# is present only when its optional dependency imports, so a lean environment
# (e.g. CI without the extra) legitimately omits it. The contract snapshot must
# not treat that env-driven absence as drift — see ``compare`` for cli.
_CLI_OPTIONAL_SUBCOMMANDS = frozenset({"memory", "ear", "registry"})


def _cli_drop_absent_optional(golden_root: dict, fresh_root: dict) -> tuple[dict, dict]:
    """Return copies of the two cli command trees with any import-guarded optional
    top-level subcommand that is absent on EITHER side removed from BOTH — so an
    optional subcommand missing in a lean env is ignored, while a genuine change
    to the core tree (or to an optional subcommand present in both) still drifts."""
    import copy

    g = copy.deepcopy(golden_root or {})
    f = copy.deepcopy(fresh_root or {})
    gc = g.get("commands") if isinstance(g, dict) else None
    fc = f.get("commands") if isinstance(f, dict) else None
    if isinstance(gc, dict) and isinstance(fc, dict):
        for name in _CLI_OPTIONAL_SUBCOMMANDS:
            if (name in gc) != (name in fc):  # present on one side only
                gc.pop(name, None)
                fc.pop(name, None)
    return g, f


def _describe_click(cmd) -> dict:
    # Duck-typed, NOT ``isinstance(cmd, click.Group)`` / ``isinstance(param,
    # click.Argument)``: Typer >= 0.26 vendors its own click (``typer._click``),
    # so its command/param objects are not instances of the real ``click`` classes
    # and the isinstance checks silently collapse the whole tree to an empty
    # ``command``. ``param_type_name`` ('argument'|'option') and a ``.commands``
    # dict are stable click APIs across both the real and vendored click.
    args: list[str] = []
    opts: list[str] = []
    for param in cmd.params:
        if getattr(param, "param_type_name", None) == "argument":
            args.append(param.name)
        else:
            opts.extend(getattr(param, "opts", []))
            opts.extend(getattr(param, "secondary_opts", []))
    subcommands = getattr(cmd, "commands", None)
    is_group = isinstance(subcommands, dict)
    node: dict = {
        "type": "group" if is_group else "command",
        "arguments": args,  # positional order preserved (contract-bearing)
        "options": sorted(set(opts)),
    }
    if is_group:
        node["commands"] = {
            name: _describe_click(sub)
            for name, sub in sorted(subcommands.items())
        }
    return node


def build_cli() -> dict:
    import typer.main

    from ari.cli import app

    root = typer.main.get_command(app)
    return {
        "schema_version": 1,
        "_meta": _meta("cli"),
        "root": _describe_click(root),
        "env_side_effects": _CLI_ENV_SIDE_EFFECTS,
    }


# ---------------------------------------------------------------------------
# Surface: MCP tool catalog (static AST, exact-set)
# ---------------------------------------------------------------------------

_MCP_INVARIANTS = {
    "return_envelope": ["error", "result"],
    "fq_name_pattern": "mcp__<skill>__<tool>",
    "namespace": "flat_snake_case",
}


def _is_mcp_tool_decorator(dec: ast.expr) -> bool:
    node = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "tool"
        and isinstance(node.value, ast.Name)
        and node.value.id == "mcp"
    )


def _decorator_name_override(dec: ast.expr):
    if isinstance(dec, ast.Call):
        for kw in dec.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                return kw.value.value
    return None


def _func_arg_names(func) -> list[str]:
    a = func.args
    names = [x.arg for x in a.posonlyargs] + [x.arg for x in a.args]
    names += [x.arg for x in a.kwonlyargs]
    return sorted(names)


def _is_tool_ctor(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name) and f.id == "Tool":
        return True
    return isinstance(f, ast.Attribute) and f.attr == "Tool"


def _tool_ctor_fields(call: ast.Call):
    name = None
    props: list[str] = []
    for kw in call.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            name = kw.value.value
        elif kw.arg == "inputSchema" and isinstance(kw.value, ast.Dict):
            for k, v in zip(kw.value.keys, kw.value.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "properties"
                    and isinstance(v, ast.Dict)
                ):
                    props = [
                        pk.value
                        for pk in v.keys
                        if isinstance(pk, ast.Constant) and isinstance(pk.value, str)
                    ]
    return name, sorted(props)


def _scan_skill_tools(server_py: Path) -> list[dict]:
    tree = ast.parse(server_py.read_text(encoding="utf-8"))
    tools: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if _is_mcp_tool_decorator(dec):
                    name = _decorator_name_override(dec) or node.name
                    tools.append(
                        {"name": name, "args": _func_arg_names(node), "idiom": "fastmcp"}
                    )
        elif isinstance(node, ast.Call) and _is_tool_ctor(node):
            name, props = _tool_ctor_fields(node)
            if name is not None:
                tools.append({"name": name, "args": props, "idiom": "lowlevel"})
    tools.sort(key=lambda t: (t["name"], t["idiom"]))
    return tools


def _skill_server_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for child in sorted(REPO_ROOT.glob("ari-skill-*")):
        server = child / "src" / "server.py"
        if server.is_file():
            out.append((child.name, server))
    return out


def build_mcp_static() -> dict:
    skills: dict[str, list[dict]] = {}
    for skill_name, server in _skill_server_files():
        skills[skill_name] = _scan_skill_tools(server)

    # Cross-skill duplicate tool names (the flat-namespace clobber: the
    # MCPClient._tool_registry resolves last-skill-wins). Recorded, NOT fixed.
    seen: dict[str, list[str]] = {}
    for skill_name, tools in skills.items():
        for tool in tools:
            seen.setdefault(tool["name"], [])
            if skill_name not in seen[tool["name"]]:
                seen[tool["name"]].append(skill_name)
    known_collisions = {
        name: sorted(owners) for name, owners in seen.items() if len(owners) > 1
    }
    return {
        "schema_version": 1,
        "_meta": _meta("mcp"),
        "skills": skills,
        "invariants": _MCP_INVARIANTS,
        "known_collisions": known_collisions,
    }


# ---------------------------------------------------------------------------
# Surface: dashboard endpoints (curated inventory + AST drift scan)
# ---------------------------------------------------------------------------

# Curated method+path+owner inventory, transcribed from the primary-source
# backend inventory docs/refactoring/reports/viz_api_contract_inventory.md
# (subtask 020, itself grounded in ari-core/ari/viz/routes.py + api_*.py).
_VIZ_ENDPOINTS = [
    # --- GET (do_GET) ---
    {"method": "GET", "path": "/logo.png", "owner": "routes"},
    {"method": "GET", "path": "/", "owner": "routes"},
    {"method": "GET", "path": "/static/<path>", "owner": "routes"},
    {"method": "GET", "path": "/memory/<node_id>", "owner": "routes"},
    {"method": "GET", "path": "/state", "owner": "routes"},
    {"method": "GET", "path": "/api/gpu-monitor", "owner": "api_process"},
    {"method": "GET", "path": "/api/ollama/<path>", "owner": "api_ollama"},
    {"method": "GET", "path": "/codefile", "owner": "routes"},
    {"method": "GET", "path": "/api/models", "owner": "checkpoint_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/paper.<ext>", "owner": "routes"},
    {"method": "GET", "path": "/api/env-keys", "owner": "api_settings"},
    {"method": "GET", "path": "/api/ollama-resources", "owner": "api_ollama"},
    {"method": "GET", "path": "/api/checkpoints", "owner": "checkpoint_api"},
    {"method": "GET", "path": "/api/rubrics", "owner": "api_settings"},
    {"method": "GET", "path": "/api/fewshot/<rubric>", "owner": "api_fewshot"},
    {"method": "GET", "path": "/api/checkpoint/<id>/summary", "owner": "checkpoint_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/memory", "owner": "node_work_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/memory_access", "owner": "api_memory"},
    {"method": "GET", "path": "/api/memory/health", "owner": "api_memory"},
    {"method": "GET", "path": "/api/memory/detect", "owner": "api_memory"},
    {"method": "GET", "path": "/api/checkpoint/<id>/files", "owner": "file_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/file", "owner": "file_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/file/raw", "owner": "file_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/filetree", "owner": "node_work_api"},
    {"method": "GET", "path": "/api/checkpoint/<id>/filecontent", "owner": "node_work_api"},
    {"method": "GET", "path": "/api/ear/<rid>/publish-yaml", "owner": "ear"},
    {"method": "GET", "path": "/api/ear/<rid>", "owner": "ear"},
    {"method": "GET", "path": "/api/nodes/<rid>/<nid>/report", "owner": "ear"},
    {"method": "GET", "path": "/api/settings", "owner": "api_settings"},
    {"method": "GET", "path": "/api/publish/settings", "owner": "api_publish"},
    {"method": "GET", "path": "/api/publish/<rid>/preview", "owner": "api_publish"},
    {"method": "GET", "path": "/api/publish/<rid>/record", "owner": "api_publish"},
    {"method": "GET", "path": "/api/profiles", "owner": "api_settings"},
    {"method": "GET", "path": "/api/upload", "owner": "routes"},
    {"method": "GET", "path": "/api/experiment-detail", "owner": "ui_helpers"},
    {"method": "GET", "path": "/api/active-checkpoint", "owner": "routes"},
    {"method": "GET", "path": "/api/workflow", "owner": "api_settings"},
    {"method": "GET", "path": "/api/skill/<name>", "owner": "api_settings"},
    {"method": "GET", "path": "/api/skills", "owner": "api_settings"},
    {"method": "GET", "path": "/api/resource-metrics", "owner": "ui_helpers"},
    {"method": "GET", "path": "/api/container/info", "owner": "routes"},
    {"method": "GET", "path": "/api/container/images", "owner": "routes"},
    {"method": "GET", "path": "/api/workflow/default", "owner": "api_workflow"},
    {"method": "GET", "path": "/api/workflow/flow", "owner": "api_workflow"},
    {"method": "GET", "path": "/api/scheduler/detect", "owner": "api_settings"},
    {"method": "GET", "path": "/api/slurm/partitions", "owner": "api_settings"},
    {"method": "GET", "path": "/api/logs", "owner": "api_experiment"},
    {"method": "GET", "path": "/api/sub-experiments", "owner": "api_orchestrator"},
    {"method": "GET", "path": "/api/sub-experiments/<rid>", "owner": "api_orchestrator"},
    {"method": "GET", "path": "/api/lineage-decisions/<ckpt>", "owner": "checkpoint_api"},
    {"method": "GET", "path": "/api/paperbench/papers", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/arxiv/<id>", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/papers/<id>/license", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/run/<jid>/logs", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/run/<jid>/results", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/run/<jid>/report", "owner": "api_paperbench"},
    {"method": "GET", "path": "/api/paperbench/run/<jid>", "owner": "api_paperbench"},
    # --- POST (do_POST) ---
    {"method": "POST", "path": "/api/settings", "owner": "api_settings"},
    {"method": "POST", "path": "/api/memory/start-local", "owner": "api_memory"},
    {"method": "POST", "path": "/api/memory/stop-local", "owner": "api_memory"},
    {"method": "POST", "path": "/api/memory/restart", "owner": "api_memory"},
    {"method": "POST", "path": "/api/launch", "owner": "api_experiment"},
    {"method": "POST", "path": "/api/sub-experiments/launch", "owner": "api_orchestrator"},
    {"method": "POST", "path": "/api/run-stage", "owner": "api_experiment"},
    {"method": "POST", "path": "/api/config/generate", "owner": "api_tools"},
    {"method": "POST", "path": "/api/chat-goal", "owner": "api_tools"},
    {"method": "POST", "path": "/api/upload", "owner": "api_tools"},
    {"method": "POST", "path": "/api/upload/delete", "owner": "api_tools"},
    {"method": "POST", "path": "/api/env-keys", "owner": "api_settings"},
    {"method": "POST", "path": "/api/ssh/test", "owner": "api_tools"},
    {"method": "POST", "path": "/api/switch-checkpoint", "owner": "checkpoint_lifecycle"},
    {"method": "POST", "path": "/api/ear/<rid>/curate", "owner": "ear"},
    {"method": "POST", "path": "/api/ear/<rid>/publish-yaml", "owner": "ear"},
    {"method": "POST", "path": "/api/ear/clone-verify", "owner": "ear"},
    {"method": "POST", "path": "/api/publish/settings", "owner": "api_publish"},
    {"method": "POST", "path": "/api/publish/<rid>/promote", "owner": "api_publish"},
    {"method": "POST", "path": "/api/publish/<rid>", "owner": "api_publish"},
    {"method": "POST", "path": "/api/fewshot/<rid>/sync", "owner": "api_fewshot"},
    {"method": "POST", "path": "/api/fewshot/<rid>/upload", "owner": "api_fewshot"},
    {"method": "POST", "path": "/api/fewshot/<rid>/<ex>/delete", "owner": "api_fewshot"},
    {"method": "POST", "path": "/api/paperbench/papers/import", "owner": "api_paperbench"},
    {"method": "POST", "path": "/api/paperbench/papers/<id>/delete", "owner": "api_paperbench"},
    {"method": "POST", "path": "/api/paperbench/papers/<id>/metadata", "owner": "api_paperbench"},
    {"method": "POST", "path": "/api/paperbench/run", "owner": "api_paperbench"},
    {"method": "POST", "path": "/api/paperbench/cost-estimate", "owner": "api_paperbench"},
    {"method": "POST", "path": "/api/ollama/<path>", "owner": "api_ollama"},
    {"method": "POST", "path": "/api/gpu-monitor", "owner": "api_process"},
    {"method": "POST", "path": "/api/stop", "owner": "api_process"},
    {"method": "POST", "path": "/api/checkpoint/file/save", "owner": "file_api"},
    {"method": "POST", "path": "/api/checkpoint/file/delete", "owner": "file_api"},
    {"method": "POST", "path": "/api/checkpoint/compile", "owner": "file_api"},
    {"method": "POST", "path": "/api/checkpoint/<id>/file/upload", "owner": "file_api"},
    {"method": "POST", "path": "/api/delete-checkpoint", "owner": "checkpoint_lifecycle"},
    {"method": "POST", "path": "/api/workflow", "owner": "api_settings"},
    {"method": "POST", "path": "/api/workflow/flow", "owner": "api_workflow"},
    {"method": "POST", "path": "/api/workflow/skills", "owner": "api_workflow"},
    {"method": "POST", "path": "/api/workflow/disabled-tools", "owner": "api_workflow"},
    {"method": "POST", "path": "/api/container/pull", "owner": "routes"},
]

# Always-present response keys mirrored (NOT forked) from
# ari-core/tests/test_api_schema_contract.py, which remains the canonical
# response-shape guard. Compared with additive/subset semantics.
_VIZ_RESPONSE_KEYS = {
    "GET /api/checkpoints[]": [
        "best_metric",
        "id",
        "mtime",
        "node_count",
        "path",
        "review_score",
        "status",
    ],
    "GET /api/checkpoint/<id>/summary": ["id", "nodes_tree", "path"],
    "GET /api/settings": [
        "container_mode",
        "container_pull",
        "letta_base_url",
        "letta_embedding_config",
        "llm_model",
        "llm_provider",
        "ollama_host",
        "ors",
        "retrieval_backend",
        "slurm_partition",
        "slurm_walltime",
        "temperature",
        "vlm_review_enabled",
        "vlm_review_model",
    ],
}


def _expr_base_is_self_path(node: ast.expr) -> bool:
    """True if *node* is ``self.path`` or a chained call/attr rooted at it.

    Handles ``self.path``, ``self.path.rstrip('/')``, ``self.path.split('?')[0]``.
    """
    cur = node
    while True:
        if (
            isinstance(cur, ast.Attribute)
            and cur.attr == "path"
            and isinstance(cur.value, ast.Name)
            and cur.value.id == "self"
        ):
            return True
        if isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Subscript):
            cur = cur.value
        else:
            return False


def _scan_route_literals(routes_py: Path) -> list[str]:
    """Best-effort: path string literals compared against ``self.path``.

    Extracts ``self.path == "/x"``, ``self.path.startswith("/x")`` /
    ``endswith`` string args (only literals starting with ``/``). Dynamic paths
    (``re.match`` regexes, f-strings) are intentionally not resolved and live
    only in the curated ``endpoints`` inventory.
    """
    tree = ast.parse(routes_py.read_text(encoding="utf-8"))
    lits: set[str] = set()

    def _add(value: object) -> None:
        if isinstance(value, str) and value.startswith("/"):
            lits.add(value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_expr_base_is_self_path(op) for op in operands):
                for op in operands:
                    if isinstance(op, ast.Constant):
                        _add(op.value)
        elif isinstance(node, ast.Call):
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in ("startswith", "endswith")
                and _expr_base_is_self_path(fn.value)
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant):
                        _add(arg.value)
                    elif isinstance(arg, ast.Tuple):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant):
                                _add(elt.value)
    return sorted(lits)


def build_viz() -> dict:
    routes_py = ARI_CORE / "ari" / "viz" / "routes.py"
    return {
        "schema_version": 1,
        "_meta": _meta("viz"),
        "endpoints": _VIZ_ENDPOINTS,
        "response_keys": _VIZ_RESPONSE_KEYS,
        "response_keys_source": (
            "ari-core/tests/test_api_schema_contract.py (canonical); mirrored "
            "here with additive/subset semantics"
        ),
        "resolvable_path_literals": _scan_route_literals(routes_py),
    }


# ---------------------------------------------------------------------------
# Build dispatch + compare
# ---------------------------------------------------------------------------

_BUILDERS = {
    "public": build_public,
    "cli": build_cli,
    "mcp": build_mcp_static,
    "viz": build_viz,
}


def build(surface: str) -> dict:
    return _BUILDERS[surface]()


def load_golden(surface: str) -> dict:
    return json.loads(_fixture_path(surface).read_text(encoding="utf-8"))


def compare(surface: str, golden: dict, fresh: dict) -> list[str]:
    """Return a list of human-readable drift messages (empty == in sync).

    The whole payload is deterministic and byte-stable, so the base check is a
    full structural equality; per-surface hints make failures actionable.
    """
    hint = (
        f"run `python scripts/snapshot_contracts.py --surface {surface} --update` "
        "if the change is intentional."
    )
    msgs: list[str] = []

    if surface == "public":
        gs, fsym = golden.get("symbols", {}), fresh.get("symbols", {})
        for mod in sorted(set(gs) | set(fsym)):
            g, f = set(gs.get(mod, [])), set(fsym.get(mod, []))
            if g != f:
                msgs.append(
                    f"[public] {mod}: removed={sorted(g - f)} added={sorted(f - g)}"
                )
    elif surface == "mcp":
        gk = golden.get("skills", {})
        fk = fresh.get("skills", {})
        for skill in sorted(set(gk) | set(fk)):
            if gk.get(skill) != fk.get(skill):
                gnames = {t["name"] for t in gk.get(skill, [])}
                fnames = {t["name"] for t in fk.get(skill, [])}
                msgs.append(
                    f"[mcp] {skill}: removed={sorted(gnames - fnames)} "
                    f"added={sorted(fnames - gnames)} (or args changed)"
                )
        if golden.get("known_collisions") != fresh.get("known_collisions"):
            msgs.append(
                "[mcp] cross-skill name collisions changed: "
                f"golden={golden.get('known_collisions')} "
                f"fresh={fresh.get('known_collisions')}"
            )
        if golden.get("invariants") != fresh.get("invariants"):
            msgs.append("[mcp] invariants block changed")
    elif surface == "viz":
        g = set(golden.get("resolvable_path_literals", []))
        f = set(fresh.get("resolvable_path_literals", []))
        if g != f:
            msgs.append(
                f"[viz] route path literals: removed={sorted(g - f)} "
                f"added={sorted(f - g)}"
            )
        if golden.get("endpoints") != fresh.get("endpoints"):
            msgs.append("[viz] curated endpoint inventory changed")
        if golden.get("response_keys") != fresh.get("response_keys"):
            msgs.append("[viz] mirrored response_keys changed")
    else:  # cli — structural equality of the introspected tree + env effects
        # Ignore import-guarded optional subcommands absent in a lean env (CI).
        g_root, f_root = _cli_drop_absent_optional(golden.get("root"), fresh.get("root"))
        if g_root != f_root:
            msgs.append("[cli] command/option tree drifted from golden")
        if golden.get("env_side_effects") != fresh.get("env_side_effects"):
            msgs.append("[cli] env_side_effects drifted from golden")
        # Neutralize the byte backstop below for env-driven optional-subcommand
        # absence by comparing normalized payloads.
        golden = {**golden, "root": g_root}
        fresh = {**fresh, "root": f_root}

    # Backstop: any residual byte difference (e.g. schema_version/_meta) is drift.
    if not msgs and dumps(golden) != dumps(fresh):
        msgs.append(f"[{surface}] payload differs from golden (see full diff)")

    if msgs:
        msgs.append(hint)
    return msgs


def _write(surface: str) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = _fixture_path(surface)
    path.write_text(dumps(build(surface)), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def _check(surface: str) -> list[str]:
    path = _fixture_path(surface)
    if not path.exists():
        return [f"[{surface}] missing golden: {path.relative_to(REPO_ROOT)}"]
    return compare(surface, load_golden(surface), build(surface))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--surface", choices=(*SURFACES, "all"), default="all",
        help="contract surface to snapshot/verify",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify (default)")
    mode.add_argument("--update", action="store_true", help="regenerate goldens")
    args = parser.parse_args(argv)

    surfaces = SURFACES if args.surface == "all" else (args.surface,)

    if args.update:
        for surface in surfaces:
            _write(surface)
        return 0

    drift: list[str] = []
    for surface in surfaces:
        drift.extend(_check(surface))
    if drift:
        print("Contract snapshot drift detected:\n" + "\n".join(drift), file=sys.stderr)
        return 1
    print(f"contract snapshots in sync: {', '.join(surfaces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
