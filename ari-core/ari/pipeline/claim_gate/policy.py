"""claim_gate_policy loader (Story2Proposal Phase B3).

Resolution order (later overrides earlier):
  1. built-in defaults (MVP = warn)
  2. a policy passed in (dict, JSON string, or Python-repr string from
     ``{{claim_gate_policy}}`` template expansion)
  3. ``{checkpoint_dir}/claim_gate_policy.json`` when present
  4. env ``ARI_CLAIM_GATE_MODE`` (strict | warn | off) — the evaluation switch

``mode`` governs blocking: ``off`` never blocks; ``warn`` (MVP) reports
errors/warnings but never blocks finalize; ``strict`` (evaluation) blocks the
*final* gate when block_on errors exist, and makes uncovered result numbers in
strict sections blocking.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_POLICY: dict = {
    "mode": "warn",  # strict | warn | off
    # Injected research intent (P4): "any" (default; cross-environment comparison
    # is a transparency warning) | "same_environment" (cross-env comparison is a
    # blocking error — single-architecture optimization studies). env override:
    # ARI_COMPARISON_SCOPE.
    "comparison_scope": "any",
    "numeric_coverage": {
        "target_sections": {
            "strict": ["abstract", "results", "conclusion"],
            "warn": ["introduction", "discussion", "limitations"],
            "excluded": ["related_work", "references", "appendix", "equations"],
        },
    },
    "numeric_match": {"default_tolerance": {"absolute": 0.0, "relative": 0.02}},
    "blocking": {
        "block_on": ["numeric_mismatch", "operand_unresolved", "missing_evidence"],
        # Objective-falsehood findings: physically/logically impossible or
        # unverifiable results. Unlike block_on (which only blocks under strict),
        # these block the FINAL paper regardless of warn/strict — they are
        # deterministically false / unsound, not subjective review.
        #   invariant_violation     — a universal or declared invariant is false
        #   correctness_failed       — declared kernel-correctness check failed
        #   correctness_uncovered    — correctness required but not emitted
        #   placeholder_denominator  — a required ceiling is a constant, not measured
        #   recompute_mismatch       — reported metric not reproducible from raw inputs
        #   claim_evidence_missing   — a declared falsifiable claim has no supporting measurement
        #   ceiling_unmeasured       — idea requires a measured ceiling but none was emitted
        "always_block_on": [
            "invariant_violation", "correctness_failed", "correctness_uncovered",
            "placeholder_denominator", "recompute_mismatch", "claim_evidence_missing",
            "ceiling_unmeasured",
        ],
    },
}


def _coerce(obj: Any) -> dict:
    if not obj:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        s = obj.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            try:
                v = ast.literal_eval(s)  # handles {{...}} -> Python repr
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
    return {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_policy(checkpoint_dir: "str | Path | None" = None, policy: Any = None) -> dict:
    resolved = dict(DEFAULT_POLICY)
    resolved = _deep_merge(resolved, _coerce(policy))
    if checkpoint_dir:
        pf = Path(checkpoint_dir) / "claim_gate_policy.json"
        if pf.is_file():
            try:
                resolved = _deep_merge(resolved, json.loads(pf.read_text()))
            except Exception:
                pass
    env_mode = os.environ.get("ARI_CLAIM_GATE_MODE", "").strip().lower()
    if env_mode in ("strict", "warn", "off"):
        resolved["mode"] = env_mode
    env_scope = os.environ.get("ARI_COMPARISON_SCOPE", "").strip().lower()
    if env_scope in ("any", "same_environment"):
        resolved["comparison_scope"] = env_scope
    return resolved


def mode(policy: dict) -> str:
    m = str(policy.get("mode", "warn")).strip().lower()
    return m if m in ("strict", "warn", "off") else "warn"


def comparison_scope(policy: dict) -> str:
    s = str(policy.get("comparison_scope", "any")).strip().lower()
    return s if s in ("any", "same_environment") else "any"


def target_sections(policy: dict) -> dict:
    return (policy.get("numeric_coverage", {}) or {}).get("target_sections", {}) or {}


def default_tolerance(policy: dict) -> dict:
    return (policy.get("numeric_match", {}) or {}).get(
        "default_tolerance", {"absolute": 0.0, "relative": 0.02}
    )


def block_on(policy: dict) -> set:
    return set((policy.get("blocking", {}) or {}).get("block_on", []) or [])


def always_block_on(policy: dict) -> set:
    """Finding types that block the FINAL paper regardless of warn/strict mode
    (objective falsehoods, e.g. invariant_violation)."""
    return set((policy.get("blocking", {}) or {}).get("always_block_on", []) or [])
