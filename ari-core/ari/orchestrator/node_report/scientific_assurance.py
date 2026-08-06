"""Typed K/C/A node-report projection, absent on the legacy path."""

from __future__ import annotations

from typing import Any


def scientific_assurance_fields(node: Any) -> dict:
    values = {
        "knowledge_skill_refs": list(getattr(node, "knowledge_skill_refs", []) or []),
        "knowledge_skill_use_digest": str(
            getattr(node, "knowledge_skill_use_digest", "") or ""
        ),
        "instruction_identity_digest": str(
            getattr(node, "instruction_identity_digest", "") or ""
        ),
        "capability_binding_lock_digest": str(
            getattr(node, "capability_binding_lock_digest", "") or ""
        ),
        "bound_tool_refs": list(getattr(node, "bound_tool_refs", []) or []),
        "assurance_status": str(getattr(node, "assurance_status", "") or ""),
        "assurance_tier": str(getattr(node, "assurance_tier", "") or ""),
        "baseline_harness_lock_digest": str(
            getattr(node, "baseline_harness_lock_digest", "") or ""
        ),
        "active_harness_lock_digest": str(
            getattr(node, "active_harness_lock_digest", "") or ""
        ),
        "attestation_refs": list(getattr(node, "attestation_refs", []) or []),
        "verified_target_digest": str(
            getattr(node, "verified_target_digest", "") or ""
        ),
        "property_verdicts": dict(getattr(node, "property_verdicts", {}) or {}),
        "frontier_class": str(getattr(node, "frontier_class", "") or ""),
        "repair_request_id": str(getattr(node, "repair_request_id", "") or ""),
        "repair_requirement_ids": list(
            getattr(node, "repair_requirement_ids", []) or []
        ),
        "repair_context_digest": str(
            getattr(node, "repair_context_digest", "") or ""
        ),
        "repair_allowed_changes": list(
            getattr(node, "repair_allowed_changes", []) or []
        ),
    }
    return {
        key: value
        for key, value in values.items()
        if value not in ("", [], {})
    }


__all__ = ["scientific_assurance_fields"]
