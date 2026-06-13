"""Evidence resolution for the claim_evidence_hard_gate (Story2Proposal Phase B).

Resolves ``(node_id, metric_path)`` operands and existence checks against the
checkpoint's executed evidence: ``tree.json`` (node ids + metrics),
per-node ``results.json`` (typed measurements/scores/params), and per-node
``node_report.json`` (environment / executor). Best-effort and side-effect free.

Layout (mirrors ari-skill-transform):
  workspace = ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent
  run_id    = ckpt.name
  results   = {workspace}/experiments/{run_id}/{node_id}/results.json
              (fallback {workspace}/experiments/{node_id}/results.json,
                        {ckpt}/experiments/{node_id}/results.json)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def workspace_run_id(checkpoint_dir: Path) -> tuple[Path, str]:
    ckpt = Path(checkpoint_dir).expanduser().resolve()
    workspace = ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent
    return workspace, ckpt.name


def load_tree(checkpoint_dir: Path) -> dict:
    ckpt = Path(checkpoint_dir)
    for name in ("tree.json", "nodes_tree.json"):
        p = ckpt / name
        if p.is_file():
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if isinstance(data, dict) and "nodes" in data:
                return data
            if isinstance(data, list):
                return {"nodes": data}
    return {"nodes": []}


def index_nodes(tree: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in tree.get("nodes", []) or []:
        nid = n.get("id") or n.get("node_id")
        if nid:
            out[str(nid)] = n
    return out


def load_results_json(checkpoint_dir: Path, node_id: str) -> dict:
    if not node_id:
        return {}
    workspace, run_id = workspace_run_id(checkpoint_dir)
    ckpt = Path(checkpoint_dir)
    for cand in (
        workspace / "experiments" / run_id / node_id / "results.json",
        workspace / "experiments" / node_id / "results.json",
        ckpt / "experiments" / node_id / "results.json",
    ):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text())
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def load_node_report(checkpoint_dir: Path, node_id: str) -> dict:
    if not node_id:
        return {}
    workspace, run_id = workspace_run_id(checkpoint_dir)
    ckpt = Path(checkpoint_dir)
    for cand in (
        workspace / "experiments" / run_id / node_id / "node_report.json",
        workspace / "experiments" / node_id / "node_report.json",
        ckpt / "experiments" / node_id / "node_report.json",
    ):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text())
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def _dot_get(container: Any, dotted: str) -> Any:
    if not dotted:
        return container
    cur = container
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def node_exists(node_by_id: dict[str, dict], node_id: str) -> bool:
    return str(node_id) in node_by_id


def node_executed(node_by_id: dict[str, dict], node_id: str) -> bool:
    n = node_by_id.get(str(node_id))
    return bool(n and n.get("has_real_data"))


def resolve_operand(
    checkpoint_dir: Path,
    node_by_id: dict[str, dict],
    node_id: str,
    metric_path: str,
) -> tuple["float | None", str]:
    """Resolve a scalar from (node_id, metric_path). Returns (value, source)."""
    if not node_id or not metric_path:
        return None, ""
    root, _, rest = metric_path.partition(".")
    rj = load_results_json(checkpoint_dir, node_id)

    # results.json typed containers
    if root in ("measurements", "scores", "params", "predictions"):
        val = _dot_get(rj.get(root, {}), rest)
        if _is_number(val):
            return float(val), f"results.json:{metric_path}"

    # explicit node metrics path
    if root == "metrics":
        node = node_by_id.get(str(node_id), {})
        val = _dot_get(node.get("metrics", {}), rest)
        if _is_number(val):
            return float(val), f"tree.json:metrics.{rest}"

    # fallback: try by trailing key across containers
    key = rest or root
    for c in ("measurements", "scores", "predictions"):
        v = (rj.get(c) or {}).get(key)
        if _is_number(v):
            return float(v), f"results.json:{c}.{key}"
    node = node_by_id.get(str(node_id), {})
    mv = (node.get("metrics") or {}).get(key)
    if _is_number(mv):
        return float(mv), f"tree.json:metrics.{key}"
    return None, ""


def env_signature(checkpoint_dir: Path, node_id: str) -> dict:
    """Coarse environment signature for same-environment comparison checks."""
    rep = load_node_report(checkpoint_dir, node_id)
    cpu = rep.get("cpu_info") or {}
    return {
        "executor": rep.get("executor", ""),
        "cpu_model": cpu.get("model", ""),
        "arch": cpu.get("arch", ""),
    }


def artifact_exists(checkpoint_dir: Path, rel_path: str) -> bool:
    if not rel_path:
        return False
    ckpt = Path(checkpoint_dir)
    if Path(rel_path).is_absolute():
        return Path(rel_path).exists()
    for base in (ckpt, ckpt / "ear_published", ckpt / "ear"):
        if (base / rel_path).exists():
            return True
    return False
