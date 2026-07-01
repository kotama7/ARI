#!/usr/bin/env python3
# ruff: noqa
"""
_capture_baseline.py — ONE-OFF measurement helper for refactoring subtask 001.

*** NON-CANONICAL. NOT the enforced checker. ***
The canonical, CI-enforced complexity/quality checker is `scripts/check_complexity.py`
(owned by subtask 025) and `scripts/generate_quality_report.py` (subtask 031).
This file deliberately lives beside the report artifacts under
`docs/refactoring/reports/` and MUST NOT be promoted to `scripts/`.

It regenerates, deterministically, the machine-readable artifacts of the
subtask-001 empirical baseline census:
  - loc_census.csv     (per-file LOC + cohort + band, via `wc -l` semantics)
  - import_edges.json   (internal ari import edges, via stdlib `ast`)
  - fan_in.csv          (per-module fan-in / fan-out + SCC id)

Tools: stdlib only (`ast`, `subprocess`, `csv`, `json`). No radon, no pydeps.
Reproduce from repo root:  python docs/refactoring/reports/_capture_baseline.py
"""
from __future__ import annotations

import ast
import csv
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPORTS = REPO / "docs" / "refactoring" / "reports"

# LOC bands (data-derived anchors; RECORDED, not enforced by this subtask).
BAND_WARN = 500
BAND_REVIEW = 800
BAND_SPLIT = 1200


def sh(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def git_ls(prefix: str) -> list[str]:
    out = sh("git", "ls-files", prefix)
    return [ln for ln in out.splitlines() if ln]


def wc_l(rel: str) -> int:
    # `wc -l` counts newline characters (matches the CLI census used in the report).
    data = (REPO / rel).read_bytes()
    return data.count(b"\n")


def band(loc: int) -> str:
    if loc > BAND_SPLIT:
        return "split"
    if loc > BAND_REVIEW:
        return "review"
    if loc > BAND_WARN:
        return "warn"
    return "-"


def stamp() -> dict[str, str]:
    sha = sh("git", "rev-parse", "HEAD").strip()
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": sha,
        "python": platform.python_version(),
        "ruff": "0.15.2",
        "generator": "docs/refactoring/reports/_capture_baseline.py (NON-CANONICAL, subtask 001)",
    }


# --------------------------------------------------------------------------- LOC
def build_loc_census(meta: dict[str, str]) -> None:
    rows: list[tuple[str, int, str, str]] = []

    def add(paths: list[str], cohort: str) -> None:
        for p in paths:
            loc = wc_l(p)
            rows.append((p, loc, cohort, band(loc)))

    core_py = [p for p in git_ls("ari-core/ari/") if p.endswith(".py")]
    add(core_py, "core-prod")
    test_py = [p for p in git_ls("ari-core/tests/") if p.endswith(".py")]
    add(test_py, "core-test")

    skills = sorted(
        d.name for d in REPO.glob("ari-skill-*") if d.is_dir()
    )
    for sk in skills:
        sk_py = [p for p in git_ls(f"{sk}/src/") if p.endswith(".py")]
        add(sk_py, f"skill:{sk}")

    fe = [
        p
        for p in git_ls("ari-core/ari/viz/frontend/src/")
        if p.endswith((".ts", ".tsx"))
    ]
    add(fe, "frontend")

    rows.sort(key=lambda r: (r[2], r[0]))
    out = REPORTS / "loc_census.csv"
    with out.open("w", newline="") as fh:
        fh.write(
            "# loc_census.csv — subtask 001 LOC baseline (wc -l semantics; git-tracked files only)\n"
        )
        fh.write("# command: python docs/refactoring/reports/_capture_baseline.py\n")
        fh.write(
            f"# git_sha={meta['git_sha']} python={meta['python']} generated_utc={meta['generated_utc']}\n"
        )
        fh.write(
            "# cohorts: core-prod (ari-core/ari), core-test (ari-core/tests), skill:<name> (ari-skill-*/src), frontend (viz/frontend/src ts,tsx)\n"
        )
        fh.write("# band: warn>500 review>800 split>1200 (RECORDED, not enforced here)\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["path", "loc", "cohort", "band"])
        w.writerows(rows)
    return rows


# ---------------------------------------------------------------------- imports
def path_to_module(rel: str) -> str | None:
    # ari-core/ari/agent/loop.py -> ari.agent.loop ; .../ari/__init__.py -> ari
    prefix = "ari-core/"
    if not rel.startswith(prefix) or not rel.endswith(".py"):
        return None
    inner = rel[len(prefix):-3]  # e.g. ari/agent/loop
    parts = inner.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or parts[0] != "ari":
        return None
    return ".".join(parts)


def resolve_target(node: ast.AST, cur_mod: str, known: set[str]) -> set[str]:
    edges: set[str] = set()
    cur_parts = cur_mod.split(".")
    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.name
            if name == "ari" or name.startswith("ari."):
                edges.add(name)
    elif isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            # relative: base package = cur package trimmed by (level-1) for module files
            # For a module ari.a.b (file b.py in package ari.a), level 1 base = ari.a
            base = cur_parts[: len(cur_parts) - node.level] if node.level <= len(cur_parts) else []
            mod = ".".join(base + ([node.module] if node.module else []))
        else:
            mod = node.module or ""
        if mod == "ari" or mod.startswith("ari."):
            # try to resolve `from mod import x` to submodule mod.x if that is a known module
            resolved_any = False
            for alias in node.names:
                cand = f"{mod}.{alias.name}"
                if cand in known:
                    edges.add(cand)
                    resolved_any = True
            if not resolved_any:
                edges.add(mod)
    return edges


def norm_to_known(target: str, known: set[str]) -> str | None:
    # Map an import target to the nearest known internal module (package resolution).
    if target in known:
        return target
    # drop trailing components until a known module matches (e.g. ari.paths.PathManager -> ari.paths)
    parts = target.split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        cand = ".".join(parts)
        if cand in known:
            return cand
    return None


def build_import_graph(meta: dict[str, str]) -> None:
    core_py = [p for p in git_ls("ari-core/ari/") if p.endswith(".py")]
    mod_of = {p: path_to_module(p) for p in core_py}
    known = {m for m in mod_of.values() if m}

    edges: set[tuple[str, str]] = set()
    parse_errors: list[str] = []
    for rel, mod in mod_of.items():
        if not mod:
            continue
        try:
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            parse_errors.append(f"{rel}: {e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for tgt in resolve_target(node, mod, known):
                    resolved = norm_to_known(tgt, known)
                    if resolved and resolved != mod:
                        edges.add((mod, resolved))

    edge_list = sorted([list(e) for e in edges])

    # fan-in / fan-out
    all_mods = sorted(known)
    fan_out: dict[str, int] = {m: 0 for m in all_mods}
    fan_in: dict[str, int] = {m: 0 for m in all_mods}
    for src, dst in edges:
        fan_out[src] = fan_out.get(src, 0) + 1
        fan_in[dst] = fan_in.get(dst, 0) + 1

    # Tarjan SCC
    scc_id = tarjan_scc(all_mods, edges)
    # size of each scc
    from collections import Counter
    sizes = Counter(scc_id.values())
    cyclic = sorted({m for m in all_mods if sizes[scc_id[m]] > 1})
    self_loops = sorted({s for s, d in edges if s == d})

    with (REPORTS / "import_edges.json").open("w") as fh:
        json.dump(
            {
                "_meta": {
                    **meta,
                    "command": "python docs/refactoring/reports/_capture_baseline.py",
                    "method": "stdlib ast scan of git-tracked ari-core/ari/**/*.py; internal ari.* edges only",
                    "scannable_scope": "ari-core/ari (internal). Cross-package edges recorded in 001_complexity_baseline.md",
                },
                "module_count": len(all_mods),
                "edge_count": len(edge_list),
                "parse_errors": parse_errors,
                "cycles": {
                    "scc_multi_node_members": cyclic,
                    "self_loops": self_loops,
                    "note": "Tarjan SCC over internal edge list. Members of any SCC with size>1 are cyclic.",
                },
                "edges": edge_list,
            },
            fh,
            indent=2,
        )

    with (REPORTS / "fan_in.csv").open("w", newline="") as fh:
        fh.write("# fan_in.csv — subtask 001 internal-import fan-in/fan-out over ari-core/ari\n")
        fh.write("# command: python docs/refactoring/reports/_capture_baseline.py\n")
        fh.write(
            f"# git_sha={meta['git_sha']} python={meta['python']} generated_utc={meta['generated_utc']}\n"
        )
        fh.write("# fan_in=in-edges (blast radius); fan_out=out-edges; scc_size>1 => in an import cycle\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["module", "fan_in", "fan_out", "scc_size"])
        for m in sorted(all_mods, key=lambda x: (-fan_in[x], x)):
            w.writerow([m, fan_in[m], fan_out[m], sizes[scc_id[m]]])

    return {
        "module_count": len(all_mods),
        "edge_count": len(edge_list),
        "cyclic_members": cyclic,
        "self_loops": self_loops,
        "parse_errors": parse_errors,
    }


def tarjan_scc(nodes: list[str], edges: set[tuple[str, str]]) -> dict[str, int]:
    from collections import defaultdict

    adj: dict[str, list[str]] = defaultdict(list)
    for s, d in sorted(edges):
        adj[s].append(d)
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    result: dict[str, int] = {}
    scc_counter = [0]

    sys.setrecursionlimit(10000)

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj[v]:
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w):
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            cid = scc_counter[0]
            scc_counter[0] += 1
            while True:
                w = stack.pop()
                on_stack[w] = False
                result[w] = cid
                if w == v:
                    break

    for v in sorted(nodes):
        if v not in index:
            strongconnect(v)
    return result


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    meta = stamp()
    build_loc_census(meta)
    summary = build_import_graph(meta)
    print(json.dumps({"meta": meta, "graph": summary}, indent=2, default=str))


if __name__ == "__main__":
    main()
