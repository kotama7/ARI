"""
ari-skill-transform: Convert BFTS internal data to science-facing format.

Strips all BFTS-internal fields before passing data to plot/paper skills.
"""
import json
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transform-skill")


def _load_nodes(nodes_json_path: str) -> list[dict]:
    data = json.loads(Path(nodes_json_path).read_text())
    return data if isinstance(data, list) else data.get("nodes", [])


def _extract_parameters(node: dict) -> dict:
    """Extract scientific parameters from node memory — no internal fields."""
    params: dict = {}
    for mem in (node.get("memory") or []):
        text = mem if isinstance(mem, str) else mem.get("content", "")
        # Compiler flags
        flags = re.findall(r"-O[0-9s]\S*|-march=\S+|-f[a-z_-]+=?\S*", text)
        for f in flags:
            params.setdefault("flags", [])
            if f not in params["flags"]:
                params["flags"].append(f)
        # Thread count
        for m in re.findall(
            r"OMP_NUM_THREADS=?(\d+)|(?:threads?|num_threads)[=: ]+(\d+)",
            text, re.IGNORECASE
        ):
            t = m[0] or m[1]
            if t:
                params["threads"] = int(t)
    return params


@mcp.tool()
def nodes_to_science_data(nodes_json_path: str) -> dict:
    """
    Convert nodes_tree.json (BFTS internal) to publication-ready scientific data.

    Strips all BFTS-internal fields:
      label, depth, node_id, parent_id, status, has_real_data

    Returns only scientifically meaningful content:
      configurations, metric_name, best_config, summary_stats

    Args:
        nodes_json_path: Path to nodes_tree.json produced by BFTS

    Returns:
        configurations: ranked list of {rank, parameters, metrics}
        metric_name:    primary metric key (e.g. "MFLOPS")
        best_config:    top-ranked configuration
        summary_stats:  {best, second_best, top5_range, count}
    """
    try:
        nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": str(e), "configurations": []}

    science_nodes = []
    for n in nodes:
        if not (n.get("has_real_data") and n.get("metrics")):
            continue
        params = _extract_parameters(n)
        science_nodes.append({
            "parameters": params,
            "metrics": n.get("metrics", {}),
        })

    def _best_metric(node: dict) -> float:
        m = node["metrics"]
        return max(m.values()) if m else 0.0

    science_nodes.sort(key=_best_metric, reverse=True)

    metric_name = "metric"
    if science_nodes:
        keys = list(science_nodes[0]["metrics"].keys())
        if keys:
            metric_name = keys[0]

    ranked = [
        {"rank": i + 1, **node}
        for i, node in enumerate(science_nodes)
    ]

    best = _best_metric(science_nodes[0]) if science_nodes else 0.0
    second = _best_metric(science_nodes[1]) if len(science_nodes) > 1 else 0.0
    top5 = sorted([_best_metric(n) for n in science_nodes[:5]])

    return {
        "configurations": ranked,
        "metric_name": metric_name,
        "best_config": ranked[0] if ranked else {},
        "summary_stats": {
            "best": best,
            "second_best": second,
            "top5_range": [top5[0], top5[-1]] if top5 else [],
            "count": len(ranked),
        },
    }


if __name__ == "__main__":
    mcp.run()
