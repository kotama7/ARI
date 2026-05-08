"""Rubric manifest: sha256 freezing + provenance + PaperBench format conversion."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

VERSION = "3"


def compute_paper_sha256(paper_text: str) -> str:
    """sha256 over the UTF-8 encoded paper text."""
    return hashlib.sha256(paper_text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_rubric_sha256(rubric: dict) -> str:
    """sha256 of canonical-JSON rubric, excluding self-referential fields.

    Excluded: rubric_sha256 (self), audit (mutated by auditor after freeze).
    """
    snapshot = copy.deepcopy(rubric)
    snapshot.pop("rubric_sha256", None)
    snapshot.pop("audit", None)
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
) -> dict:
    """Attach generator metadata + sha256 to the rubric envelope.

    Mutates a *copy* of ``rubric`` and returns the frozen dict. The input is
    expected to already conform to ``replication_rubric.schema.json`` apart
    from the fields this function fills in (paper_sha256, generator,
    rubric_sha256, version).
    """
    out = copy.deepcopy(rubric)
    out["version"] = VERSION
    out["paper_sha256"] = compute_paper_sha256(paper_text)
    gen = {
        "model": generator_model,
        "prompt_sha256": compute_prompt_sha256(prompt),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temperature": float(temperature),
    }
    if seed is not None:
        gen["seed"] = int(seed)
    if snapshot is not None:
        gen["snapshot"] = snapshot
    out["generator"] = gen
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


def add_audit_metadata(
    rubric: dict,
    *,
    auditor_model: str,
    flags_count: int,
) -> dict:
    """Attach audit metadata in-place; does not change rubric_sha256."""
    rubric["audit"] = {
        "auditor_model": auditor_model,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "flags_count": int(flags_count),
    }
    return rubric
