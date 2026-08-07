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
            # A binding whose subject is asynchronous is submitted through one
            # tool and completed through others. Admitting only the dispatch
            # tool authorizes starting work that can never be collected, so the
            # lifecycle tools the binding names inherit exactly its authority --
            # same phase, same context, same binding digest.
            for lifecycle_ref in item.lifecycle_tool_refs:
                by_tool.setdefault(lifecycle_ref, []).append(item)
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

    def decide(
        self,
        tool_ref: str,
        *,
        phase: str | None = None,
        context=None,
        arguments: dict | None = None,
    ):
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
        # A composite binding authorizes one dispatch tool to reach one reviewed
        # leaf. The leaf travels in the call's arguments, so admitting the
        # dispatch tool alone would let the first reviewed leaf's authorization
        # carry every other leaf the federated catalog holds -- including ones
        # whose capability this run forbids, and ones never reviewed at all.
        composite = tuple(item for item in compatible if item.subject_tool_ref)
        if composite:
            direct = tuple(item for item in compatible if not item.subject_tool_ref)
            allowed_subjects = {
                item.subject_tool_ref: item for item in composite
            }
            names = {item.subject_argument for item in composite if item.subject_argument}
            requested = None
            if isinstance(arguments, dict):
                for name in sorted(names):
                    if name in arguments:
                        requested = str(arguments.get(name) or "")
                        break
            if requested is None:
                # Arguments were not supplied to the decision. A composite must
                # not fall back to the dispatch tool's authority; only a direct
                # binding on the same ref can carry the call.
                if not direct:
                    return ToolAuthorizationDecision(False, "composite_subject_unknown")
                compatible = direct
            elif requested in allowed_subjects:
                compatible = (allowed_subjects[requested], *direct)
            elif direct:
                compatible = direct
            else:
                return ToolAuthorizationDecision(False, "composite_subject_unbound")
        return ToolAuthorizationDecision(
            True,
            "bound",
            binding_digest=canonical_digest(
                tuple(item.binding_digest for item in compatible)
            ),
        )

    def record_invocation(
        self,
        tool_ref: str,
        *,
        phase: str | None,
        context,
        arguments: dict | None = None,
    ) -> None:
        """Record an actual post-admission dispatch, never a visibility check.

        The arguments must be the ones the call carried: re-deciding without
        them would record ``composite_subject_unknown`` for a brokered call that
        the dispatch path had just admitted, and the governance record would
        disagree with the decision that actually let the call through.
        """

        node_id = str(getattr(context, "node_id", "") or "")
        if not node_id:
            return
        decision = self.decide(
            tool_ref, phase=phase, context=context, arguments=arguments
        )
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
