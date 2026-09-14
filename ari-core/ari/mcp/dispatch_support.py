"""Pure identity, phase, timeout, and tracing policy for MCP dispatch."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from ari.async_tools import TimeoutBudgetV1
from ari.config import SkillConfig
from ari.result import ToolCallContextV1


class ToolNameCollisionError(RuntimeError):
    """Raised when more than one admitted Skill owns the same bare tool name."""


def runtime_tool_ref(skill: SkillConfig, tool: dict) -> str:
    """Bind declared identity to the schemas returned by ``tools/list``."""

    name = str(tool.get("name") or "unknown")
    provider = skill.package or skill.name
    declared = skill.tool_refs.get(name)
    if not declared:
        declared = {
            "package": provider,
            "version": skill.version,
            "entrypoint": skill.entrypoint,
            "tool": name,
        }
    payload = json.dumps(
        {
            "declared": declared,
            "input_schema": tool.get("inputSchema") or {},
            "output_schema": tool.get("outputSchema") or {},
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{provider}/{name}@sha256:{digest}"


def unresolved_tool_ref(tool_name: str) -> str:
    """Return a deterministic identity for a rejected unresolved request."""

    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()
    return f"unresolved/{tool_name}@sha256:{digest}"


def resolve_registration(
    requested: str,
    *,
    tool_ref_registry: dict[str, str],
    tool_name_by_ref: dict[str, str],
    tool_registry: dict[str, str],
    tool_ref_by_name: dict[str, str],
) -> tuple[str, str, str | None, str]:
    """Resolve an immutable reference or the migration-only unique bare alias."""

    if requested in tool_ref_registry:
        return (
            tool_name_by_ref[requested],
            requested,
            tool_ref_registry[requested],
            "immutable-tool-ref",
        )
    skill_name = tool_registry.get(requested)
    return (
        requested,
        tool_ref_by_name.get(requested, unresolved_tool_ref(requested)),
        skill_name,
        "unique-bare-alias" if skill_name else "unresolved",
    )


def normalize_phases(phase: str | list[str] | None) -> list[str]:
    """Coerce SkillConfig.phase into a flat list of phase strings."""

    if phase is None:
        return ["all"]
    if isinstance(phase, str):
        return [phase]
    return [str(item) for item in phase]


def phase_matches(skill_phase: str | list[str], want: str) -> bool:
    """Return whether a declared phase admits ``want``."""

    phases = normalize_phases(skill_phase)
    return want in phases or "all" in phases


def phase_is_disabled(skill_phase: str | list[str]) -> bool:
    """Return whether a Skill is fully disabled by its phase declaration."""

    phases = [phase for phase in normalize_phases(skill_phase) if phase]
    return phases == ["none"]


MAX_RETRIES = 3
RETRY_DELAY = 0.5
DEFAULT_TOOL_TIMEOUT = 300
SLOW_TOOL_TIMEOUT = 3_600
VERY_SLOW_TOOL_TIMEOUT = 13 * 3_600

_TIMEOUT_CLASS_SECONDS = {
    "default": DEFAULT_TOOL_TIMEOUT,
    "bounded": DEFAULT_TOOL_TIMEOUT,
    "slow": SLOW_TOOL_TIMEOUT,
    "very-slow": VERY_SLOW_TOOL_TIMEOUT,
    "async": DEFAULT_TOOL_TIMEOUT,
}


def resolve_tool_timeout(
    args: dict,
    *,
    timeout_class: str | None = None,
    timeout_budget: TimeoutBudgetV1 | dict | None = None,
) -> int:
    """Resolve a manifest class and an explicitly declared per-call budget."""

    if timeout_budget is not None:
        budget = (
            timeout_budget
            if isinstance(timeout_budget, TimeoutBudgetV1)
            else TimeoutBudgetV1.model_validate(timeout_budget)
        )
        requested = budget.requested_seconds(args)
        if requested is not None:
            return requested
    return _TIMEOUT_CLASS_SECONDS.get(timeout_class or "default", DEFAULT_TOOL_TIMEOUT)


def log_tool_call(log: logging.Logger, tool_name: str, args: dict) -> None:
    """Emit bounded argument diagnostics for selected propagation-sensitive tools."""

    if tool_name not in {"make_metric_spec", "generate_ideas", "survey"}:
        log.debug("[mcp] call_tool %s: args_keys=%s", tool_name, list(args))
        return
    rendered = json.dumps(args, ensure_ascii=False)
    log.info(
        "[mcp] call_tool %s: args_len=%d args=%s",
        tool_name,
        len(rendered),
        rendered[:500],
    )


def default_call_context(node_id: str | None = None) -> ToolCallContextV1:
    """Derive compatibility context from the scoped checkpoint environment."""

    checkpoint_dir = os.environ.get("ARI_CHECKPOINT_DIR", "").strip()
    run_id = Path(checkpoint_dir.rstrip(os.sep)).name if checkpoint_dir else ""
    return ToolCallContextV1(
        run_id=run_id,
        node_id=node_id,
    )


def enrich_call_context(
    context: ToolCallContextV1,
    *,
    selection_reason: str,
    skill: SkillConfig | None,
) -> ToolCallContextV1:
    """Attach core-owned selection and value-free credential authority metadata."""

    updates: dict[str, object] = {}
    if not context.selection_reason:
        updates["selection_reason"] = selection_reason
    if not context.credential_scope_ids and skill is not None:
        updates["credential_scope_ids"] = sorted(
            str(identity.get("scope_id"))
            for identity in skill.credential_scope_identities
            if identity.get("scope_id") and identity.get("present_env")
        )
    return context.model_copy(update=updates) if updates else context


__all__ = [
    "DEFAULT_TOOL_TIMEOUT",
    "MAX_RETRIES",
    "RETRY_DELAY",
    "SLOW_TOOL_TIMEOUT",
    "ToolNameCollisionError",
    "VERY_SLOW_TOOL_TIMEOUT",
    "default_call_context",
    "enrich_call_context",
    "log_tool_call",
    "normalize_phases",
    "phase_is_disabled",
    "phase_matches",
    "resolve_registration",
    "resolve_tool_timeout",
    "runtime_tool_ref",
    "unresolved_tool_ref",
]
