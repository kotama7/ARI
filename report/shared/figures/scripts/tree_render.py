#!/usr/bin/env python3
"""F02 — example BFTS exploration tree, rendered from frozen tree.json.

Reads:  shared/figures/data/F02_tree.json   (BFTS dump)
Writes: shared/figures/dot/F02_tree.dot     (graphviz source, committed)

The TikZ realisation (shared/figures/tikz/F02_tree.tex) is hand-maintained
in the house design language (tikz/_style.tex) and is NOT regenerated here;
the dot file stays as the data-derived provenance record. If the frozen
tree data changes, update node ids / scores in F02_tree.tex and the
\\figlabeldef{F02.*} entries in en|ja|zh strings.tex to match the new dot.
"""
from __future__ import annotations

import json
from pathlib import Path

THIS = Path(__file__).resolve().parent
DATA = THIS.parent / "data" / "F02_tree.json"
DOT  = THIS.parent / "dot"  / "F02_tree.dot"


def _write_dot(tree: dict) -> None:
    DOT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "digraph T {",
        "  graph [rankdir=TB, ranksep=0.6, nodesep=0.4];",
        "  node  [shape=box, style=\"rounded\", fontsize=10];",
    ]
    for node in tree.get("nodes", []):
        nid = node["id"]
        score = node.get("reward", 0.0)
        lines.append(f'  n{nid} [label="N{nid}\\nr={score:.2f}"];')
    for node in tree.get("nodes", []):
        for c in node.get("children", []):
            lines.append(f"  n{node['id']} -> n{c};")
    lines.append("}")
    DOT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthetic_tree() -> dict:
    return {
        "nodes": [
            {"id": 0, "reward": 0.50, "children": [1, 2]},
            {"id": 1, "reward": 0.62, "children": [3, 4]},
            {"id": 2, "reward": 0.48, "children": [5]},
            {"id": 3, "reward": 0.71, "children": []},
            {"id": 4, "reward": 0.66, "children": [6]},
            {"id": 5, "reward": 0.40, "children": []},
            {"id": 6, "reward": 0.74, "children": []},
        ]
    }


def render_tree(out_dir: Path | None = None) -> Path:
    tree = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else _synthetic_tree()
    _write_dot(tree)
    return DOT


if __name__ == "__main__":
    p = render_tree()
    print(f"wrote {p}")
