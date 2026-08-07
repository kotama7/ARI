"""Rubric manifest: sha256 freezing + provenance + PaperBench format conversion."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

VERSION = "3"
SCHEMA_VERSION = "ari.replication-rubric/v2"


def compute_paper_sha256(paper_text: str) -> str:
    """sha256 over the UTF-8 encoded paper text."""
    return hashlib.sha256(paper_text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_rubric_sha256(rubric: dict) -> str:
    """sha256 of canonical-JSON rubric, excluding self-referential fields.

    Excluded: rubric_sha256 (self). Audits are separate immutable reports in
    V2 and therefore never mutate this document.
    """
    snapshot = copy.deepcopy(rubric)
    snapshot.pop("rubric_sha256", None)
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def compute_prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def freeze(
    rubric: dict,
    *,
    generator_model: str,
    prompt: str,
    paper_text: str,
    temperature: float = 0.0,
    seed: int | None = None,
    snapshot: dict | None = None,
    provider: str = "unknown",
    model_revision: str | None = None,
    strategy: str = "hierarchical-v2",
    quality_profile: str = "calibrated",
    max_model_calls: int = 64,
    subtree_concurrency: int = 4,
    calls: list[dict] | None = None,
    partial_failures: list[str] | None = None,
    repair_ledger: dict | None = None,
    source_artifact: dict | None = None,
) -> dict:
    """Attach generator metadata + sha256 to the rubric envelope.

    Mutates a *copy* of ``rubric`` and returns the frozen dict. The input is
    expected to already conform to ``replication_rubric.schema.json`` apart
    from the fields this function fills in (paper_sha256, generator,
    rubric_sha256, version).
    """
    out = copy.deepcopy(rubric)
    out["schema_version"] = SCHEMA_VERSION
    out["version"] = VERSION
    out["paper_sha256"] = compute_paper_sha256(paper_text)
    gen = {
        "model": generator_model,
        "model_revision": model_revision,
        "provider": provider,
        "prompt_sha256": compute_prompt_sha256(prompt),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temperature": float(temperature),
        "strategy": strategy,
        "quality_profile": quality_profile,
        "max_model_calls": int(max_model_calls),
        "subtree_concurrency": int(subtree_concurrency),
        "calls": list(calls or []),
        "partial_failures": list(partial_failures or []),
    }
    if seed is not None:
        gen["seed"] = int(seed)
    if snapshot is not None:
        gen["snapshot"] = snapshot
    if source_artifact is not None:
        gen["source_artifact"] = copy.deepcopy(source_artifact)
    out["generator"] = gen
    out["repair_ledger"] = copy.deepcopy(
        repair_ledger or {"actions": [], "dropped_artifacts": []}
    )
    out.pop("rubric_sha256", None)
    out["rubric_sha256"] = compute_rubric_sha256(out)
    return out


def verify(rubric: dict) -> bool:
    """Verify that ``rubric_sha256`` matches the recomputed value."""
    stored = rubric.get("rubric_sha256")
    if not stored:
        return False
    return stored == compute_rubric_sha256(rubric)


# ─── PaperBench TaskNode conversion ─────────────────────────────────────

_PAPERBENCH_NODE_KEYS = {
    "id",
    "requirements",
    "weight",
    "sub_tasks",
    "task_category",
    "finegrained_task_category",
}


def _strip_node(node: dict) -> dict:
    """Recursively strip our metadata wrappers; coerce weight to int."""
    out: dict = {}
    for k, v in node.items():
        if k not in _PAPERBENCH_NODE_KEYS:
            continue
        out[k] = v
    out["weight"] = int(node.get("weight", 1))
    children = node.get("sub_tasks") or []
    out["sub_tasks"] = [_strip_node(c) for c in children]
    return out


def to_paperbench_format(our_rubric: dict) -> dict:
    """Strip our metadata wrappers and return raw TaskNode tree.

    The result is consumable by PaperBench's ``SimpleJudge`` directly.
    Defensive coercion: ``weight`` is forced to ``int`` (PaperBench
    ``TaskNode`` requires ``int``); generator output validation should
    already reject non-integer weights but we coerce anyway.
    """
    rubric_root = our_rubric.get("rubric")
    if not isinstance(rubric_root, dict):
        raise ValueError("Rubric envelope missing 'rubric' root TaskNode")
    return _strip_node(rubric_root)
