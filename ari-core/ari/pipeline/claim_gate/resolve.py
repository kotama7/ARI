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
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SAFE_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResolvedOperand:
    value: float | None = None
    source: str = ""
    unit: str | None = None
    document_digest: str | None = None
    artifact_digests: tuple[str, ...] = ()
    error: str | None = None


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


def _node_dir(checkpoint_dir: Path, node_id: str) -> Path | None:
    if not _SAFE_NODE_ID.fullmatch(str(node_id)):
        return None
    workspace, run_id = workspace_run_id(checkpoint_dir)
    candidate = (workspace / "experiments" / run_id / node_id).resolve()
    root = (workspace / "experiments" / run_id).resolve()
    if candidate.parent != root:
        return None
    return candidate


def load_results_json(
    checkpoint_dir: Path, node_id: str, *, strict: bool = False
) -> dict:
    if not node_id:
        return {}
    workspace, run_id = workspace_run_id(checkpoint_dir)
    ckpt = Path(checkpoint_dir)
    canonical = _node_dir(checkpoint_dir, node_id)
    candidates = (() if canonical is None else (canonical / "results.json",))
    if not strict:
        candidates = (*candidates,
            workspace / "experiments" / node_id / "results.json",
            ckpt / "experiments" / node_id / "results.json",
        )
    for cand in candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text())
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def load_node_report(
    checkpoint_dir: Path, node_id: str, *, strict: bool = False
) -> dict:
    if not node_id:
        return {}
    workspace, run_id = workspace_run_id(checkpoint_dir)
    ckpt = Path(checkpoint_dir)
    canonical = _node_dir(checkpoint_dir, node_id)
    candidates = (() if canonical is None else (canonical / "node_report.json",))
    if not strict:
        candidates = (*candidates,
            workspace / "experiments" / node_id / "node_report.json",
            ckpt / "experiments" / node_id / "node_report.json",
        )
    for cand in candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text())
                if not isinstance(data, dict):
                    return {}
                if strict and data.get("node_id") != node_id:
                    return {}
                return data
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
    *,
    strict: bool = False,
) -> tuple["float | None", str]:
    """Resolve a scalar from (node_id, metric_path). Returns (value, source)."""
    resolved = resolve_operand_evidence(
        checkpoint_dir,
        node_by_id,
        node_id,
        metric_path,
        strict=strict,
    )
    return resolved.value, resolved.source


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _verified_measurement_document(
    checkpoint_dir: Path, node_id: str
) -> tuple[dict, str | None, str | None]:
    node_dir = _node_dir(checkpoint_dir, node_id)
    if node_dir is None:
        return {}, None, "invalid_node_id"
    path = node_dir / "results.json"
    try:
        payload = path.read_bytes()
        raw = json.loads(payload)
    except FileNotFoundError:
        return {}, None, "missing_results"
    except (OSError, json.JSONDecodeError):
        return {}, None, "invalid_results"
    try:
        from ari.execution import parse_measurement_document

        measurement_set = parse_measurement_document(raw, allow_legacy=False)
    except Exception:
        return {}, None, "invalid_measurement_contract"

    report = load_node_report(checkpoint_dir, node_id, strict=True)
    report_artifacts: dict[str, tuple[Path, str]] = {}
    for artifact in report.get("artifacts", []) if isinstance(report, dict) else ():
        if not isinstance(artifact, dict):
            continue
        filename = str(artifact.get("filename") or "")
        raw_digest = str(artifact.get("sha256") or "")
        digest = raw_digest if raw_digest.startswith("sha256:") else f"sha256:{raw_digest}"
        if (
            filename
            and Path(filename).name == filename
            and _SHA256.fullmatch(digest)
        ):
            report_artifacts[digest] = (node_dir / filename, filename)
    for digest in measurement_set.artifact_digests:
        binding = report_artifacts.get(digest)
        if binding is None:
            return {}, None, "artifact_not_bound"
        artifact_path, _ = binding
        try:
            if _sha256_file(artifact_path) != digest:
                return {}, None, "artifact_digest_mismatch"
        except OSError:
            return {}, None, "artifact_missing"
    projection = {
        "params": measurement_set.parameters,
        "measurements": {
            item.metric_id: item.value for item in measurement_set.measurements
        },
        "measurement_records": {
            item.metric_id: item for item in measurement_set.measurements
        },
        "predictions": measurement_set.predictions,
        "scores": measurement_set.scores,
        "artifact_digests": tuple(measurement_set.artifact_digests),
    }
    return projection, "sha256:" + hashlib.sha256(payload).hexdigest(), None


def _resolve_loaded_operand(
    rj: dict,
    node: dict,
    metric_path: str,
    *,
    strict: bool,
    document_digest: str | None,
) -> ResolvedOperand:
    root, _, rest = metric_path.partition(".")
    if root in ("measurements", "scores", "params", "predictions"):
        if strict and root != "measurements":
            return ResolvedOperand(error="untyped_nonmeasurement_operand")
        val = _dot_get(rj.get(root, {}), rest)
        if _is_number(val):
            record = (rj.get("measurement_records") or {}).get(rest)
            return ResolvedOperand(
                value=float(val),
                source=f"results.json:{metric_path}",
                unit=getattr(record, "unit", None),
                document_digest=document_digest,
                artifact_digests=tuple(getattr(record, "artifact_digests", ())),
            )

    if root == "metrics":
        val = _dot_get(node.get("metrics", {}), rest)
        if _is_number(val):
            if strict:
                return ResolvedOperand(error="untyped_tree_metric")
            return ResolvedOperand(value=float(val), source=f"tree.json:metrics.{rest}")

    key = rest or root
    for container in ("measurements", "scores", "predictions"):
        value = (rj.get(container) or {}).get(key)
        if not _is_number(value):
            continue
        if strict and container != "measurements":
            return ResolvedOperand(error="untyped_nonmeasurement_operand")
        record = (rj.get("measurement_records") or {}).get(key)
        return ResolvedOperand(
            value=float(value),
            source=f"results.json:{container}.{key}",
            unit=getattr(record, "unit", None),
            document_digest=document_digest,
            artifact_digests=tuple(getattr(record, "artifact_digests", ())),
        )
    metric_value = (node.get("metrics") or {}).get(key)
    if _is_number(metric_value):
        if strict:
            return ResolvedOperand(error="untyped_tree_metric")
        return ResolvedOperand(
            value=float(metric_value), source=f"tree.json:metrics.{key}"
        )
    return ResolvedOperand(error="metric_not_found")


def resolve_operand_evidence(
    checkpoint_dir: Path,
    node_by_id: dict[str, dict],
    node_id: str,
    metric_path: str,
    *,
    strict: bool = False,
) -> ResolvedOperand:
    """Resolve a scalar plus typed unit/artifact provenance."""

    if not node_id or not metric_path:
        return ResolvedOperand(error="missing_operand_binding")
    if not node_exists(node_by_id, node_id):
        return ResolvedOperand(error="cross_run_or_unknown_node")
    if strict and not node_executed(node_by_id, node_id):
        return ResolvedOperand(error="node_not_executed")
    document_digest = None
    if strict:
        rj, document_digest, error = _verified_measurement_document(
            checkpoint_dir, node_id
        )
        if error:
            return ResolvedOperand(error=error)
    else:
        rj = load_results_json(checkpoint_dir, node_id)

    node = node_by_id.get(str(node_id), {})
    return _resolve_loaded_operand(
        rj,
        node,
        metric_path,
        strict=strict,
        document_digest=document_digest,
    )


def env_signature(
    checkpoint_dir: Path, node_id: str, *, strict: bool = False
) -> dict:
    """Coarse environment signature for same-environment comparison checks."""
    rep = load_node_report(checkpoint_dir, node_id, strict=strict)
    cpu = rep.get("cpu_info") or {}
    return {
        "executor": rep.get("executor", ""),
        "cpu_model": cpu.get("model", ""),
        "arch": cpu.get("arch", ""),
    }


def verify_artifact(
    checkpoint_dir: Path,
    artifact: Any,
    *,
    strict: bool = False,
) -> tuple[bool, str]:
    """Verify a legacy path or a run/node/digest-bound artifact reference."""

    if strict:
        if not isinstance(artifact, dict):
            return False, "artifact_reference_untyped"
        workspace, run_id = workspace_run_id(checkpoint_dir)
        if artifact.get("run_id") != run_id:
            return False, "cross_run_artifact"
        node_id = str(artifact.get("node_id") or "")
        node_dir = _node_dir(checkpoint_dir, node_id)
        relative = str(artifact.get("relative_path") or "")
        digest = str(artifact.get("digest") or "")
        if (
            node_dir is None
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not _SHA256.fullmatch(digest)
        ):
            return False, "invalid_artifact_reference"
        path = (node_dir / relative).resolve()
        try:
            path.relative_to(node_dir)
            actual = _sha256_file(path)
        except FileNotFoundError:
            return False, "artifact_missing"
        except OSError:
            return False, "artifact_unreadable"
        if actual != digest:
            return False, "artifact_digest_mismatch"
        return True, ""
    rel_path = str(artifact or "")
    if not rel_path:
        return False, "artifact_missing"
    ckpt = Path(checkpoint_dir)
    if Path(rel_path).is_absolute():
        return Path(rel_path).exists(), "" if Path(rel_path).exists() else "artifact_missing"
    for base in (ckpt, ckpt / "ear_published", ckpt / "ear"):
        if (base / rel_path).exists():
            return True, ""
    return False, "artifact_missing"


def artifact_exists(checkpoint_dir: Path, rel_path: Any) -> bool:
    return verify_artifact(checkpoint_dir, rel_path)[0]
