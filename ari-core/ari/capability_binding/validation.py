"""Validation helpers kept separate from deterministic selection."""

from __future__ import annotations

import threading

from ari.capability_binding.models import (
    CapabilityBindingLockV1,
    CapabilityOntologySnapshotV1,
)
from ari.protocols.integrity import canonical_digest
from ari.protocols.mcp import ToolAuthorizationDecision


class BoundToolAuthorizationView:
    """Frozen Binding Lock projection consumed by the existing MCP client."""

    def __init__(self, lock: CapabilityBindingLockV1, *, mode: str) -> None:
        if mode not in {"audit", "enforce"}:
            raise ValueError("authorization view requires audit or enforce mode")
        self._lock = lock
        self._mode = mode
        by_tool: dict[str, list] = {}
        for item in lock.bindings:
            by_tool.setdefault(item.tool_ref, []).append(item)
        self._by_tool = {
            tool_ref: tuple(sorted(items, key=lambda value: value.capability_ref))
            for tool_ref, items in by_tool.items()
        }
        self._record_lock = threading.Lock()
        self._invocations_by_node: dict[str, list[tuple[str, str, str | None]]] = {}

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def lock_digest(self) -> str:
        return self._lock.lock_digest

    def decide(self, tool_ref: str, *, phase: str | None = None, context=None):
        bindings = self._by_tool.get(tool_ref)
        if bindings is None:
            return ToolAuthorizationDecision(
                allowed=self._mode == "audit",
                reason_code="unbound_tool",
                audit_only=self._mode == "audit",
            )
        effective_phase = phase or getattr(context, "phase", None)
        if effective_phase and not any(
            effective_phase == binding.phase for binding in bindings
        ):
            return ToolAuthorizationDecision(False, "binding_phase_mismatch")
        compatible = tuple(
            binding
            for binding in bindings
            if context is None or context.satisfies(binding.call_context)
        )
        if not compatible:
            return ToolAuthorizationDecision(False, "binding_context_mismatch")
        return ToolAuthorizationDecision(
            True,
            "bound",
            binding_digest=canonical_digest(
                tuple(item.binding_digest for item in compatible)
            ),
        )

    def record_invocation(self, tool_ref: str, *, phase: str | None, context) -> None:
        """Record an actual post-admission dispatch, never a visibility check."""

        node_id = str(getattr(context, "node_id", "") or "")
        if not node_id:
            return
        decision = self.decide(tool_ref, phase=phase, context=context)
        item = (str(tool_ref), decision.reason_code, decision.binding_digest)
        with self._record_lock:
            self._invocations_by_node.setdefault(node_id, []).append(item)

    def invocation_records(self, node_id: str) -> tuple[tuple[str, str, str | None], ...]:
        with self._record_lock:
            return tuple(self._invocations_by_node.get(str(node_id), ()))


def validate_lock_ontology(
    lock: CapabilityBindingLockV1, ontology: CapabilityOntologySnapshotV1
) -> None:
    if lock.ontology_snapshot_digest != ontology.snapshot_digest:
        raise ValueError("binding lock uses a different ontology snapshot")
    contracts = {item.capability_ref: item.contract_digest for item in ontology.contracts}
    for requirement in lock.requirements:
        if contracts.get(requirement.capability_ref) != requirement.capability_contract_digest:
            raise ValueError("binding requirement does not match ontology contract")


__all__ = ["BoundToolAuthorizationView", "validate_lock_ontology"]
