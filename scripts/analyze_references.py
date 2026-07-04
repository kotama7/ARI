#!/usr/bin/env python3
"""Build a deterministic reference graph over the ARI codebase.

Realizes ``docs/refactoring/013_reference_graph_and_dead_code_plan.md`` §6/§8
and the subtask ``docs/refactoring/subtasks/054_add_reference_graph_analyzer.md``
(chain ``053 -> 054 -> 055 -> 056 -> 057 -> 058`` in
``docs/refactoring/007_subtask_index.md``).

This is the *analyzer* half of the dead-code chain: it emits the graph that the
classifier (``check_dead_code.py``, subtask 055) later consumes. It NEVER
classifies dead code, and it NEVER edits runtime code -- it only reads the tree
and writes its own report artifact under ``docs/refactoring/reports/``.

Why it exists (013 §2): *"absence of a static import edge is necessary but not
sufficient evidence of deadness."* ARI is import-driven at its extensibility
seams -- publish backends dispatched by string, prompt/rubric/schema DATA reached
by filesystem key, MCP tools reached by name over stdio, and dashboard endpoints
reached cross-language from the React client. A naive import graph flags all of
those live surfaces as dead. This analyzer overlays those dynamic edges, each
carrying a falsifiable ``evidence`` string (``file:line`` + the matched key).

Determinism (ARI design principle P2): stdlib ``ast`` + PyYAML only; no LLM, no
network; every array is sorted by ``id``; the only wall-clock value is the
top-level ``generated_at``. Two runs on the same commit produce byte-identical
``nodes``/``edges``/``collisions``. ``--check`` re-derives the graph and diffs it
(ignoring ``generated_at``) against the committed artifact.

House style mirrors ``scripts/docs/check_doc_sources.py`` and
``scripts/readme_sync.py``: ``argparse``, ``REPO_ROOT = parents[1]``, PyYAML
guarded to ``SystemExit(2)``, exit ``2`` on usage/environment error.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "analyze_references: PyYAML is required (pip install pyyaml).\n"
    )
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1

DEFAULT_CONFIG_PATH = REPO_ROOT / "scripts" / "quality" / "analyze_references.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "refactoring" / "reports" / "reference_graph.json"
# Subtask 053's machine-readable roots manifest (read-only input).
ROOTS_CANDIDATES = (
    REPO_ROOT / "docs" / "refactoring" / "reports" / "053_reference_roots.json",
    REPO_ROOT / "docs" / "refactoring" / "reports" / "reference_roots.json",
)

# Fallback config when the YAML is absent -- keeps the analyzer self-contained.
BUILTIN_CONFIG = {
    "scan_roots": ["ari-core/ari"],
    "include_skills_glob": "ari-skill-*/src",
    "prompt_bases": [
        "ari-core/ari/prompts",
        "ari-skill-paper-re/src/prompts",
        "ari-skill-replicate/src/prompts",
    ],
    "frontend_api_client": "ari-core/ari/viz/frontend/src/services/api.ts",
    "viz_route_dir": "ari-core/ari/viz",
    "data_selectors": [
        {
            "glob": "ari-core/config/reviewer_rubrics/*.yaml",
            "from_file": "ari-core/ari/cli/projects.py",
            "evidence": "ari-core/ari/cli/projects.py:81 ARI_RUBRIC (--rubric)",
        },
        {
            "glob": "ari-core/config/paperbench_rubrics/*.yaml",
            "from_file": "ari-core/ari/cli/projects.py",
            "evidence": "ari-core/ari/cli/projects.py:81 ARI_RUBRIC (--rubric)",
        },
        {
            "glob": "ari-core/config/profiles/*.yaml",
            "from_file": "ari-core/ari/cli/run.py",
            "evidence": "ari-core/ari/cli/run.py:140 --profile",
        },
        {
            "glob": "ari-core/config/reviewer_rubrics/fewshot_examples/neurips/*.json",
            "from_file": "ari-core/ari/cli/projects.py",
            "evidence": "ari-core/ari/cli/projects.py:86 ARI_FEWSHOT_MODE",
        },
        {
            "glob": "ari-core/ari/schemas/*.schema.json",
            "from_file": "ari-core/ari/schemas/__init__.py",
            "evidence": "ari-core/ari/schemas/__init__.py:11 load(name)",
        },
        {
            "glob": "ari-core/config/workflow.yaml",
            "from_file": "ari-core/ari/cli/run.py",
            "evidence": "ari-core/ari/cli/run.py:91 package workflow.yaml",
        },
        {
            "glob": "ari-core/ari/configs/*.yaml",
            "from_file": "ari-core/ari/configs/_loader.py",
            "evidence": "ari-core/ari/configs/_loader.py FilesystemConfigLoader",
        },
    ],
    "ignore_globs": ["*/__pycache__/*", "*/node_modules/*", "*.pyc"],
}


# ── graph accumulator ──────────────────────────────────────────────────────

class Graph:
    """Deterministic node/edge accumulator (dedup by id / edge tuple)."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}
        self._edges: dict[tuple, dict] = {}
        self._collisions: dict[str, dict] = {}
        self.notes: list[str] = []

    def add_node(self, node_id: str, kind: str, file: str, loc: int) -> None:
        if node_id not in self._nodes:
            self._nodes[node_id] = {
                "id": node_id,
                "kind": kind,
                "file": file,
                "loc": loc,
                "reachable_from": [],
                "edges_in": [],
            }

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def add_edge(self, src: str, dst: str, kind: str, evidence: str) -> None:
        # 013 §6.1: dynamic / cross-language edges are falsifiable -- refuse to
        # record one without a file:line + matched-key evidence string.
        if kind in _EVIDENCE_REQUIRED and not evidence:
            raise ValueError(f"edge {src}->{dst} ({kind}) lacks required evidence")
        key = (src, dst, kind, evidence)
        if key not in self._edges:
            self._edges[key] = {
                "from": src,
                "to": dst,
                "kind": kind,
                "evidence": evidence,
            }

    def add_collision(self, tool_name: str, skills: list[str], note: str) -> None:
        self._collisions[tool_name] = {
            "tool_name": tool_name,
            "skills": sorted(skills),
            "note": note,
        }

    def finalize(self) -> tuple[list[dict], list[dict], list[dict]]:
        # edges_in: inbound edge kinds per node.
        inbound: dict[str, set] = {}
        for e in self._edges.values():
            if e["to"] in self._nodes:
                inbound.setdefault(e["to"], set()).add(e["kind"])
        for nid, kinds in inbound.items():
            self._nodes[nid]["edges_in"] = sorted(kinds)
        nodes = sorted(self._nodes.values(), key=lambda n: n["id"])
        edges = sorted(
            self._edges.values(),
            key=lambda e: (e["from"], e["to"], e["kind"], e["evidence"]),
        )
        collisions = sorted(self._collisions.values(), key=lambda c: c["tool_name"])
        return nodes, edges, collisions

    def compute_reachability(self, seeds: dict[str, set]) -> None:
        adj: dict[str, list[str]] = {}
        for e in self._edges.values():
            adj.setdefault(e["from"], []).append(e["to"])
        reach: dict[str, set] = {}
        for root_id in sorted(seeds):
            frontier = [s for s in seeds[root_id] if s in self._nodes]
            seen = set(frontier)
            while frontier:
                cur = frontier.pop()
                for nxt in adj.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            for nid in seen:
                reach.setdefault(nid, set()).add(root_id)
        for nid, roots in reach.items():
            if nid in self._nodes:
                self._nodes[nid]["reachable_from"] = sorted(roots)


_EVIDENCE_REQUIRED = frozenset(
    {"dynamic.string_key", "dynamic.path", "dynamic.mcp", "cross_lang.http"}
)


# ── helpers ────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    cfg = dict(BUILTIN_CONFIG)
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            sys.stderr.write(f"analyze_references: {path} is not a mapping.\n")
            raise SystemExit(2)
        cfg.update(loaded)
    return cfg


def load_roots_manifest(explicit: Path | None) -> dict | None:
    if explicit is not None:
        if not explicit.exists():
            return None
        try:
            return json.loads(explicit.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"analyze_references: bad roots manifest: {exc}\n")
            raise SystemExit(2)
    for cand in ROOTS_CANDIDATES:
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except ValueError:
                return None
    return None


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        sha = out.stdout.strip()
        return sha or "unknown"
    except OSError:  # pragma: no cover - git absent
        return "unknown"


def is_ignored(rel: str, ignore_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in ignore_globs)


def posix_rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def module_id(rel: str) -> str:
    return f"py.module:{rel}"


def symbol_id(rel: str, name: str) -> str:
    return f"py.symbol:{rel}:{name}"


def dotted_for(path: Path, pkg_root: Path | None) -> str | None:
    """Dotted module name relative to a package root, else None.

    ``pkg_root`` is the directory *above* the top-level package (e.g.
    ``ari-core/`` for the ``ari`` package, so ``ari-core/ari/publish/x.py`` ->
    ``ari.publish.x``). Skill ``src`` trees pass ``pkg_root=None`` (their bare
    ``server`` module names would otherwise collide across skills)."""
    if pkg_root is None:
        return None
    try:
        rel = path.relative_to(pkg_root)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def line_count(path: Path) -> int:
    try:
        return path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    except OSError:
        return 0


def node_len(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    start = getattr(node, "lineno", None)
    if end and start:
        return end - start + 1
    return 1


# ── python static layer ────────────────────────────────────────────────────

class PyFile:
    __slots__ = ("rel", "path", "dotted", "is_pkg", "tree", "symbols")

    def __init__(self, rel: str, path: Path, dotted: str | None, tree: ast.AST):
        self.rel = rel
        self.path = path
        self.dotted = dotted
        self.is_pkg = path.name == "__init__.py"
        self.tree = tree
        self.symbols: set[str] = set()


def collect_py_files(base: Path, cfg: dict) -> list[PyFile]:
    ignore = cfg["ignore_globs"]
    # (root_dir, pkg_root): scan roots get a real package root (their parent);
    # skill src trees get None so bare ``server`` names never collide.
    roots: list[tuple[Path, Path | None]] = [
        (base / r, (base / r).parent) for r in cfg["scan_roots"]
    ]
    skills_glob = cfg.get("include_skills_glob")
    if skills_glob:
        for src_dir in sorted(base.glob(skills_glob)):
            if src_dir.is_dir():
                roots.append((src_dir, None))
    seen: set[Path] = set()
    out: list[PyFile] = []
    for root, pkg_root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if path in seen:
                continue
            seen.add(path)
            rel = posix_rel(path, base)
            if is_ignored(rel, ignore):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            out.append(PyFile(rel, path, dotted_for(path, pkg_root), tree))
    return out


def register_python_nodes(graph: Graph, files: list[PyFile]) -> dict[str, str]:
    """Add module + top-level symbol nodes; return dotted -> module_id index."""
    dotted_index: dict[str, str] = {}
    for pf in files:
        mid = module_id(pf.rel)
        graph.add_node(mid, "py.module", pf.rel, line_count(pf.path))
        if pf.dotted:
            dotted_index[pf.dotted] = mid
        for node in pf.tree.body:
            names = _toplevel_symbol_names(node)
            for name in names:
                pf.symbols.add(name)
                graph.add_node(
                    symbol_id(pf.rel, name), "py.symbol", pf.rel, node_len(node)
                )
    return dotted_index


def _toplevel_symbol_names(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        out = []
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out.append(tgt.id)
        return out
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _resolve_relative(pf: PyFile, module: str | None, level: int) -> str | None:
    """Resolve a ``from . import x`` base package to a dotted name."""
    if pf.dotted is None:
        return None
    base_parts = pf.dotted.split(".")
    if not pf.is_pkg:
        base_parts = base_parts[:-1]
    if level - 1 > len(base_parts):
        return None
    if level - 1:
        base_parts = base_parts[: len(base_parts) - (level - 1)]
    if module:
        base_parts = base_parts + module.split(".")
    return ".".join(base_parts) if base_parts else None


def add_static_edges(graph: Graph, files: list[PyFile], dotted_index: dict[str, str]) -> None:
    symbols_by_dotted: dict[str, set] = {
        pf.dotted: pf.symbols for pf in files if pf.dotted
    }
    for pf in files:
        mid = module_id(pf.rel)
        used_names = _load_names(pf.tree)
        for node in ast.walk(pf.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _emit_import(graph, mid, alias.name, dotted_index, pf.rel, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                target = (
                    _resolve_relative(pf, node.module, node.level)
                    if node.level
                    else node.module
                )
                if not target:
                    continue
                for alias in node.names:
                    sub = f"{target}.{alias.name}"
                    if sub in dotted_index:
                        _emit_import(graph, mid, sub, dotted_index, pf.rel, node.lineno)
                    elif target in dotted_index:
                        _emit_import(graph, mid, target, dotted_index, pf.rel, node.lineno)
                        # best-effort symbol-level static.call
                        if (
                            alias.name in symbols_by_dotted.get(target, ())
                            and alias.name in used_names
                        ):
                            graph.add_edge(
                                mid,
                                symbol_id(dotted_index[target].split(":", 1)[1], alias.name),
                                "static.call",
                                f"{pf.rel}:{node.lineno} use {alias.name}",
                            )


def _emit_import(
    graph: Graph, mid: str, dotted: str, index: dict[str, str], rel: str, lineno: int
) -> None:
    node = index.get(dotted)
    if node is None:
        # try longest known package prefix (e.g. ``import ari.publish.x`` where
        # only ``ari.publish`` is a package node)
        parts = dotted.split(".")
        while parts:
            parts.pop()
            cand = ".".join(parts)
            if cand in index:
                node = index[cand]
                break
    if node and node != mid:
        graph.add_edge(mid, node, "static.import", f"{rel}:{lineno} import {dotted}")


def _load_names(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.add(node.id)
    return out


# ── dynamic overlay ────────────────────────────────────────────────────────

def overlay_string_dispatch(graph: Graph, files: list[PyFile], dotted_index: dict[str, str]) -> None:
    """(§7.4-1) ``if var == "key": import impl`` chains + dict registries."""
    for pf in files:
        for node in ast.walk(pf.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _scan_if_chain(graph, pf, node, dotted_index)
            elif isinstance(node, ast.Assign):
                _scan_dict_registry(graph, pf, node)


def _scan_if_chain(graph: Graph, pf: PyFile, func: ast.AST, dotted_index: dict[str, str]) -> None:
    src_sym = symbol_id(pf.rel, func.name)
    if not graph.has_node(src_sym):
        return
    for sub in ast.walk(func):
        if not isinstance(sub, ast.If):
            continue
        key = _eq_string_key(sub.test)
        if key is None:
            continue
        for inner in ast.walk(sub):
            if isinstance(inner, ast.ImportFrom):
                target = (
                    _resolve_relative(pf, inner.module, inner.level)
                    if inner.level
                    else inner.module
                )
                if not target:
                    continue
                for alias in inner.names:
                    dotted = f"{target}.{alias.name}"
                    dst = dotted_index.get(dotted)
                    if dst:
                        graph.add_edge(
                            src_sym, dst, "dynamic.string_key",
                            f"{pf.rel}:{inner.lineno} key='{key}'",
                        )


def _eq_string_key(test: ast.AST) -> str | None:
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and isinstance(test.comparators[0].value, str)
    ):
        return test.comparators[0].value
    return None


def _scan_dict_registry(graph: Graph, pf: PyFile, node: ast.Assign) -> None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return
    var = node.targets[0].id
    value = node.value
    if not isinstance(value, ast.Dict) or not value.keys:
        return
    src_sym = symbol_id(pf.rel, var)
    if not graph.has_node(src_sym):
        return
    for k, v in zip(value.keys, value.values):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            return
        if not isinstance(v, ast.Name):
            return
    for k, v in zip(value.keys, value.values):
        if v.id in pf.symbols:
            graph.add_edge(
                src_sym, symbol_id(pf.rel, v.id), "dynamic.string_key",
                f"{pf.rel}:{node.lineno} {var}['{k.value}']",
            )


def overlay_lazy_registry(graph: Graph, files: list[PyFile], dotted_index: dict[str, str]) -> None:
    """(§7.4-1) ``BaseRegistry.register_lazy("key", loader)`` where the ``loader``
    function body does ``from .backends import mod`` (subtask 014 unified the former
    ``if name == "key": import impl`` chains behind this form). Without this, a
    lazily-registered backend module has no static in-edge and reads as dead."""
    for pf in files:
        # loader-function name -> registration key(s) it is wired under
        keys_by_loader: dict[str, list[str]] = {}
        for node in ast.walk(pf.tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("register_lazy", "register")
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and isinstance(node.args[1], ast.Name)
            ):
                keys_by_loader.setdefault(node.args[1].id, []).append(node.args[0].value)
        if not keys_by_loader:
            continue
        for node in ast.walk(pf.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in keys_by_loader:
                continue
            src_sym = symbol_id(pf.rel, node.name)
            if not graph.has_node(src_sym):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.ImportFrom):
                    continue
                target = (
                    _resolve_relative(pf, inner.module, inner.level)
                    if inner.level
                    else inner.module
                )
                if not target:
                    continue
                for alias in inner.names:
                    dst = dotted_index.get(f"{target}.{alias.name}")
                    if dst:
                        key = keys_by_loader[node.name][0]
                        graph.add_edge(
                            src_sym, dst, "dynamic.string_key",
                            f"{pf.rel}:{inner.lineno} register_lazy('{key}')",
                        )


def overlay_prompt_loads(graph: Graph, files: list[PyFile], base: Path, cfg: dict) -> None:
    """(§7.4-2) ``.load("key")`` / ``.load_versioned("key")`` -> ``key.md``."""
    prompt_bases = [base / p for p in cfg.get("prompt_bases", [])]
    # enumerate every prompt .md so uncalled templates still appear as nodes
    for pbase in prompt_bases:
        if not pbase.exists():
            continue
        for md in sorted(pbase.rglob("*.md")):
            if md.name == "README.md":
                continue
            rel = posix_rel(md, base)
            graph.add_node(f"data.file:{rel}", "data.file", rel, line_count(md))
    for pf in files:
        mid = module_id(pf.rel)
        for node in ast.walk(pf.tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr in ("load", "load_versioned")):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            key = arg.value
            for pbase in prompt_bases:
                md = pbase / f"{key}.md"
                if md.exists():
                    rel = posix_rel(md, base)
                    graph.add_node(f"data.file:{rel}", "data.file", rel, line_count(md))
                    graph.add_edge(
                        mid, f"data.file:{rel}", "dynamic.path",
                        f"{pf.rel}:{node.lineno} .{fn.attr}('{key}')",
                    )
                    break


def overlay_prompt_manifest(graph: Graph, base: Path, manifest: dict | None) -> None:
    """(§7.4-2 backstop) Consume 053's ``prompt_load_sites`` so templates loaded
    by a NON-literal key (e.g. ``.load(_SYSTEM_PROMPT_KEY)``,
    ``.load(config.select_prompt)``) still get a falsifiable dynamic edge."""
    if not manifest:
        return
    sites: dict[str, str] = {}
    for seam in manifest.get("dynamic_seams", []):
        if isinstance(seam.get("prompt_load_sites"), dict):
            sites.update(seam["prompt_load_sites"])
    for key, callsite in sorted(sites.items()):
        rel_call = callsite.split(":", 1)[0]
        from_rel = f"ari-core/ari/{rel_call}"
        src = module_id(from_rel)
        if not graph.has_node(src):
            continue
        md = base / "ari-core" / "ari" / "prompts" / f"{key}.md"
        if not md.exists():
            continue
        rel = posix_rel(md, base)
        graph.add_node(f"data.file:{rel}", "data.file", rel, line_count(md))
        graph.add_edge(
            src, f"data.file:{rel}", "dynamic.path",
            f"{callsite} .load('{key}')",
        )


def overlay_data_selectors(graph: Graph, base: Path, cfg: dict) -> None:
    """(§7.4-3) DATA reached by identifier / env var, not by import."""
    for sel in cfg.get("data_selectors", []):
        from_rel = sel["from_file"]
        src = module_id(from_rel)
        if not graph.has_node(src):
            continue  # selection site not scanned (e.g. sandboxed fixture)
        for path in sorted(base.glob(sel["glob"])):
            if not path.is_file():
                continue
            rel = posix_rel(path, base)
            graph.add_node(f"data.file:{rel}", "data.file", rel, line_count(path))
            graph.add_edge(
                src, f"data.file:{rel}", "dynamic.path",
                f"{sel['evidence']} -> {Path(rel).name}",
            )


def overlay_mcp_tools(graph: Graph, base: Path, cfg: dict) -> None:
    """(§7.4-4) FastMCP ``@*.tool`` + low-level ``Tool(name=...)`` handlers."""
    skills_glob = cfg.get("include_skills_glob")
    if not skills_glob:
        return
    client_rel = "ari-core/ari/mcp/client.py"
    client_node = module_id(client_rel)
    by_name: dict[str, set] = {}
    for src_dir in sorted(base.glob(skills_glob)):
        if not src_dir.is_dir():
            continue
        skill = src_dir.parent.name
        if skill.startswith("ari-skill-"):
            skill = skill[len("ari-skill-"):]
        for path in sorted(src_dir.rglob("*.py")):
            rel = posix_rel(path, base)
            if is_ignored(rel, cfg["ignore_globs"]):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            for tool, lineno in _extract_tools(tree):
                tid = f"mcp.tool:{skill}:{tool}"
                graph.add_node(tid, "mcp.tool", rel, 1)
                graph.add_edge(
                    client_node if graph.has_node(client_node) else tid,
                    tid, "dynamic.mcp",
                    f"{client_rel}:336 call_tool('{tool}') <- {rel}:{lineno}",
                )
                by_name.setdefault(tool, set()).add(skill)
    for tool, skills in by_name.items():
        if len(skills) > 1:
            graph.add_collision(
                tool, list(skills),
                "flat MCP namespace clobber (client.py:283 last-skill-wins)",
            )


def _extract_tools(tree: ast.AST) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    out.append((node.name, node.lineno))
                    break
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fname == "Tool":
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, str):
                            out.append((kw.value.value, node.lineno))
    return out


def overlay_cross_language(graph: Graph, base: Path, cfg: dict) -> None:
    """(§7.4-5) ``services/api.ts`` fetch/WS paths -> viz route registrations."""
    api_rel = cfg.get("frontend_api_client")
    viz_dir_rel = cfg.get("viz_route_dir")
    if not api_rel or not viz_dir_rel:
        return
    api_path = base / api_rel
    viz_dir = base / viz_dir_rel
    if not api_path.exists() or not viz_dir.exists():
        return
    ts_node = f"ts.module:{api_rel}"
    graph.add_node(ts_node, "ts.module", api_rel, line_count(api_path))
    ts_paths = _extract_ts_paths(api_path.read_text(encoding="utf-8", errors="replace"))
    route_paths = _extract_route_paths(viz_dir, base, cfg)
    for tp in sorted(ts_paths):
        for rp in route_paths:
            if _paths_match(tp, rp):
                rnode = f"route:{rp}"
                graph.add_node(rnode, "route", viz_dir_rel, 0)
                graph.add_edge(
                    ts_node, rnode, "cross_lang.http",
                    f"{api_rel} '{tp}' ~ {viz_dir_rel} '{rp}'",
                )


def _extract_ts_paths(text: str) -> set[str]:
    out: set[str] = set()
    # Match quoted / backtick path literals that start with a slash, cutting at
    # the first template-interpolation so ``/api/x/${id}/y`` yields ``/api/x/``.
    for m in re.finditer(r"[`'\"](/[A-Za-z0-9_\-/]*)", text):
        p = m.group(1)
        if len(p) > 1:
            out.add(p.rstrip("/") if p != "/" else p)
    return out


def _extract_route_paths(viz_dir: Path, base: Path, cfg: dict) -> set[str]:
    out: set[str] = set()
    for path in sorted(viz_dir.rglob("*.py")):
        rel = posix_rel(path, base)
        if is_ignored(rel, cfg["ignore_globs"]):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if v.startswith("/") and len(v) > 1 and re.fullmatch(r"/[A-Za-z0-9_\-/]+", v):
                    out.add(v.rstrip("/"))
    return out


def _paths_match(ts_path: str, route_path: str) -> bool:
    a, b = ts_path.rstrip("/"), route_path.rstrip("/")
    if a == b:
        return True
    # Only treat a prefix as a match when the SHORTER path is itself specific
    # (>= 2 segments), so a bare ``/api`` or ``/state`` never fans out.
    shorter = a if len(a) < len(b) else b
    if shorter.count("/") < 2:
        return False
    return a.startswith(b + "/") or b.startswith(a + "/")


def overlay_env_pairs(graph: Graph, files: list[PyFile]) -> None:
    """(§7.4-6) ``ARI_*`` env writer -> reader coupling (import-invisible)."""
    writers: dict[str, list[tuple[str, int]]] = {}
    readers: dict[str, list[tuple[str, int]]] = {}
    for pf in files:
        for node in ast.walk(pf.tree):
            var, is_write = _env_var(node)
            if var is None:
                continue
            bucket = writers if is_write else readers
            bucket.setdefault(var, []).append((pf.rel, getattr(node, "lineno", 0)))
    for var in sorted(set(writers) & set(readers)):
        for w_rel, w_line in writers[var]:
            for r_rel, _ in readers[var]:
                w_node, r_node = module_id(w_rel), module_id(r_rel)
                if w_node == r_node or not graph.has_node(r_node):
                    continue
                graph.add_edge(
                    w_node, r_node, "dynamic.string_key",
                    f"env:{var} writer={w_rel}:{w_line} -> reader={r_rel}",
                )


def _env_var(node: ast.AST) -> tuple[str | None, bool]:
    # reader: getenv("ARI_*") / os.environ.get("ARI_*")
    if isinstance(node, ast.Call):
        fn = node.func
        attr = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if attr in ("getenv", "get") and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("ARI_"):
                if attr == "get" and not _is_environ(getattr(fn, "value", None)):
                    return None, False
                return a.value, False
        if attr == "setdefault" and _is_environ(getattr(fn, "value", None)) and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("ARI_"):
                return a.value, True
    # subscript: os.environ["ARI_*"] (Load=reader, Store=writer)
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value.startswith("ARI_"):
            return sl.value, isinstance(node.ctx, ast.Store)
    return None, False


def _is_environ(value: ast.AST | None) -> bool:
    return isinstance(value, ast.Attribute) and value.attr == "environ"


# ── root seeding + reachability ────────────────────────────────────────────

def build_roots_and_seeds(
    manifest: dict | None, graph: Graph
) -> tuple[list[dict], dict[str, set]]:
    roots: list[dict] = []
    seeds: dict[str, set] = {}

    def seed(root_id: str, rel: str) -> None:
        nid = module_id(rel)
        if graph.has_node(nid):
            seeds.setdefault(root_id, set()).add(nid)

    if manifest and isinstance(manifest.get("static_roots"), list):
        for r in manifest["static_roots"]:
            roots.append({
                "id": r.get("id", "?"),
                "kind": r.get("class", "root"),
                "anchor": r.get("anchor", ""),
            })
        _seed_from_manifest(manifest, seed)
    else:
        _auto_seed(graph, seed)
        roots = [
            {"id": rid, "kind": "auto_seed", "anchor": ""} for rid in sorted(seeds)
        ]
    return sorted(roots, key=lambda r: r["id"]), seeds


def _seed_from_manifest(manifest: dict, seed) -> None:
    index = {r.get("id"): r for r in manifest.get("static_roots", [])}
    seed("R1", "ari-core/ari/cli/__init__.py")
    for m in ("cli/__init__", "cli/commands", "cli/run", "cli/projects"):
        seed("R2", f"ari-core/ari/{m}.py")
    for rel in ("memory_cli.py", "cli_ear.py", "registry/cli.py", "cli/migrate.py"):
        seed("R3", f"ari-core/ari/{rel}")
    r4 = index.get("R4", {})
    for skill in list(r4.get("fastmcp", [])) + list(r4.get("lowlevel_server", [])):
        seed("R4", f"ari-skill-{skill}/src/server.py")
    seed("R5", "ari-core/ari/mcp/client.py")
    r6 = index.get("R6", {})
    for mod in r6.get("api_modules", []):
        seed("R6", f"ari-core/ari/viz/{mod}.py")
    for mod in ("routes", "websocket", "server", "state", "state_sync"):
        seed("R6", f"ari-core/ari/viz/{mod}.py")
    r7 = index.get("R7", {})
    for sub in r7.get("submodules", []):
        seed("R7", f"ari-core/ari/public/{sub}.py")
    seed("R12", "ari-core/ari/registry/app.py")


def _auto_seed(graph: Graph, seed) -> None:
    # Fallback when 053's manifest is absent (§7.3): seed R2/R7 from the tree.
    seed("R1", "ari-core/ari/cli/__init__.py")
    for rel in ("cli/__init__", "cli/commands", "cli/run", "cli/projects"):
        seed("R2", f"ari-core/ari/{rel}.py")
    for sub in (
        "claim_gate", "config_schema", "container", "cost_tracker",
        "llm", "paths", "run_env", "verified_context",
    ):
        seed("R7", f"ari-core/ari/public/{sub}.py")


# ── output ─────────────────────────────────────────────────────────────────

def build_graph(base: Path, cfg: dict, manifest: dict | None) -> dict:
    graph = Graph()
    files = collect_py_files(base, cfg)
    dotted_index = register_python_nodes(graph, files)
    add_static_edges(graph, files, dotted_index)
    overlay_string_dispatch(graph, files, dotted_index)
    overlay_lazy_registry(graph, files, dotted_index)
    overlay_prompt_loads(graph, files, base, cfg)
    overlay_prompt_manifest(graph, base, manifest)
    overlay_data_selectors(graph, base, cfg)
    overlay_mcp_tools(graph, base, cfg)
    overlay_cross_language(graph, base, cfg)
    overlay_env_pairs(graph, files)
    roots, seeds = build_roots_and_seeds(manifest, graph)
    graph.compute_reachability(seeds)
    nodes, edges, collisions = graph.finalize()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": git_commit(),
        "roots": roots,
        "nodes": nodes,
        "edges": edges,
        "collisions": collisions,
    }


def render_markdown(graph: dict) -> str:
    nodes, edges = graph["nodes"], graph["edges"]
    node_kinds: dict[str, int] = {}
    for n in nodes:
        node_kinds[n["kind"]] = node_kinds.get(n["kind"], 0) + 1
    edge_kinds: dict[str, int] = {}
    for e in edges:
        edge_kinds[e["kind"]] = edge_kinds.get(e["kind"], 0) + 1

    def _inbound_dynamic(pred) -> tuple[int, int]:
        ids = {n["id"] for n in nodes if pred(n)}
        covered = {
            e["to"] for e in edges
            if e["to"] in ids and e["kind"].startswith(("dynamic.", "cross_lang."))
        }
        return len(covered), len(ids)

    backends = _inbound_dynamic(
        lambda n: n["file"].startswith("ari-core/ari/publish/backends/")
        and n["file"].endswith(".py") and n["kind"] == "py.module"
        and not n["file"].endswith("__init__.py")
    )
    prompts = _inbound_dynamic(
        lambda n: n["kind"] == "data.file"
        and n["file"].startswith("ari-core/ari/prompts/")
    )
    rubrics = _inbound_dynamic(
        lambda n: n["kind"] == "data.file"
        and n["file"].startswith("ari-core/config/reviewer_rubrics/")
        and n["file"].endswith(".yaml")
    )
    has_sonfigs = any("sonfigs" in n["file"] for n in nodes)

    lines = [
        "# Reference Graph (subtask 054)",
        "",
        "> Generated by `scripts/analyze_references.py`. Realizes "
        "`docs/refactoring/013_reference_graph_and_dead_code_plan.md` §6/§8. "
        "Deterministic (P2); classification is deferred to subtask 055.",
        "",
        f"- commit: `{graph['commit']}`",
        f"- generated_at: `{graph['generated_at']}`",
        f"- schema_version: `{graph['schema_version']}`",
        f"- roots: {len(graph['roots'])} · nodes: {len(nodes)} · "
        f"edges: {len(edges)} · collisions: {len(graph['collisions'])}",
        "",
        "## Nodes by kind",
        "",
        "| kind | count |",
        "|------|-------|",
    ]
    for k in sorted(node_kinds):
        lines.append(f"| `{k}` | {node_kinds[k]} |")
    lines += ["", "## Edges by kind", "", "| kind | count |", "|------|-------|"]
    for k in sorted(edge_kinds):
        lines.append(f"| `{k}` | {edge_kinds[k]} |")
    lines += [
        "",
        "## Dynamic-overlay proof (013 §6.1 falsifiability)",
        "",
        "Statically-orphan but live-by-string surfaces, each with >=1 inbound "
        "dynamic/cross-language edge:",
        "",
        "| surface | with inbound dynamic edge | total |",
        "|---------|---------------------------|-------|",
        f"| publish backends (`publish/backends/*.py`) | {backends[0]} | {backends[1]} |",
        f"| prompt templates (`ari/prompts/**.md`) | {prompts[0]} | {prompts[1]} |",
        f"| reviewer rubrics (`reviewer_rubrics/*.yaml`) | {rubrics[0]} | {rubrics[1]} |",
        "",
        f"- MCP tool nodes: {node_kinds.get('mcp.tool', 0)} "
        f"(collisions: {len(graph['collisions'])})",
        f"- `sonfigs/` node present: **{'YES (BUG)' if has_sonfigs else 'no'}**",
        "",
    ]
    if graph["collisions"]:
        lines += ["## MCP tool-name collisions", "", "| tool | skills |", "|------|--------|"]
        for c in graph["collisions"]:
            lines.append(f"| `{c['tool_name']}` | {', '.join(c['skills'])} |")
        lines.append("")
    return "\n".join(lines)


def _strip_volatile(graph: dict) -> dict:
    return {k: v for k, v in graph.items() if k != "generated_at"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", type=Path, default=None,
                        help="053 reference-roots manifest (default: auto-detect)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help="analyzer config YAML")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="reference_graph.json path")
    parser.add_argument("--base", type=Path, default=None,
                        help="scan base dir (default: config base_dir or repo root)")
    parser.add_argument("--include-skills", dest="include_skills",
                        action="store_true", default=True,
                        help="scan ari-skill-*/src (default: on)")
    parser.add_argument("--no-include-skills", dest="include_skills",
                        action="store_false")
    parser.add_argument("--include-frontend", dest="include_frontend",
                        action="store_true", default=True,
                        help="scan viz frontend for cross_lang.http (default: on)")
    parser.add_argument("--no-include-frontend", dest="include_frontend",
                        action="store_false")
    parser.add_argument("--format", choices=["json"], default="json",
                        help="primary artifact format (json only)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the derived graph differs from --output")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if not args.include_skills:
        cfg["include_skills_glob"] = None
    if not args.include_frontend:
        cfg["frontend_api_client"] = None
    base = args.base or (
        Path(cfg["base_dir"]) if cfg.get("base_dir") else REPO_ROOT
    )
    base = base.resolve()
    manifest = load_roots_manifest(args.roots)

    graph = build_graph(base, cfg, manifest)

    if args.check:
        if not args.output.exists():
            sys.stderr.write(f"analyze_references: {args.output} does not exist.\n")
            return 2
        try:
            committed = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"analyze_references: unreadable {args.output}: {exc}\n")
            return 2
        if _strip_volatile(graph) == _strip_volatile(committed):
            print(f"reference_graph up to date ({len(graph['nodes'])} nodes).")
            return 0
        sys.stderr.write("reference_graph drift: re-run without --check.\n")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path = args.output.with_suffix(".md")
    md_path.write_text(render_markdown(graph) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output.relative_to(REPO_ROOT) if _under(args.output) else args.output}: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
        f"{len(graph['collisions'])} collisions"
    )
    return 0


def _under(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
