"""Transport-neutral facade for durable ARI run orchestration."""

from __future__ import annotations

import os
import signal
import time
from datetime import datetime, timezone
from typing import Any, cast

from .artifacts import ArtifactPolicyError, inventory, read_inline
from .auth import AuthorizationError
from .contracts import (
    PrincipalV1,
    RunHandleV1,
    RunRequestV1,
    RunResultV1,
    RunState,
    RunStatusV1,
)
from .execution import ExecutionManager
from .migration import repair_legacy_registry
from .registry import (
    TERMINAL_STATES,
    InvalidTransitionError,
    RunRecord,
    RunRegistry,
)
from .runtime import (
    QuotaPolicy,
    ResourcePolicyError,
    ServiceConfig,
    ServiceError,
    atomic_json,
    atomic_text,
    process_matches,
)
from .views import locked_view, node_summary


class OrchestratorService:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.config.logs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.registry = RunRegistry(self.config.logs_root)
        self.execution = ExecutionManager(
            config,
            self.registry,
            self._sync_meta,
            self.reconcile,
        )

    def _validate_resources(self, request: RunRequestV1) -> None:
        policy = self.config.quota
        violations: list[str] = []
        if request.max_nodes > policy.max_nodes_per_run:
            violations.append("max_nodes")
        if request.max_total_nodes > policy.max_total_nodes:
            violations.append("max_total_nodes")
        if request.max_descendant_runs > policy.max_descendant_runs:
            violations.append("max_descendant_runs")
        if request.max_cost_usd > policy.max_cost_usd:
            violations.append("max_cost_usd")
        if request.cpus > policy.max_cpus:
            violations.append("cpus")
        if request.timeout_minutes > policy.max_timeout_minutes:
            violations.append("timeout_minutes")
        if violations:
            raise ResourcePolicyError(
                "request exceeds deployment quota: " + ", ".join(violations)
            )

    @staticmethod
    def _handle(record: RunRecord, *, reused: bool = False) -> RunHandleV1:
        return RunHandleV1(
            run_id=record.run_id,
            request_digest=record.request_digest,
            principal_id=record.principal_id,
            parent_run_id=record.parent_run_id,
            root_run_id=record.root_run_id,
            recursion_depth=record.recursion_depth,
            max_recursion_depth=record.max_recursion_depth,
            state=record.state,
            created_at=record.created_at,
            reused=reused,
        )

    def _sync_meta(self, record: RunRecord) -> None:
        """Write a compatibility/index mirror; SQLite remains the sole authority."""

        if not record.checkpoint_dir.is_dir() or record.checkpoint_dir.is_symlink():
            return
        atomic_json(
            record.checkpoint_dir / "meta.json",
            {
                "schema_version": "ari.orchestrator-run-meta/v1",
                "run_id": record.run_id,
                "request_digest": record.request_digest,
                "parent_run_id": record.parent_run_id,
                "root_run_id": record.root_run_id,
                "recursion_depth": record.recursion_depth,
                "max_recursion_depth": record.max_recursion_depth,
                "created_at": record.created_at,
                "started_at": record.started_at,
                "completed_at": record.completed_at,
                "status": record.state,
            },
        )

    def submit(self, request: RunRequestV1, principal: PrincipalV1) -> RunHandleV1:
        self._validate_resources(request)
        record, reused = self.registry.claim(
            request,
            principal,
            max_active_runs=self.config.quota.max_active_runs,
        )
        if reused:
            if record.state != "submitted":
                record = self.reconcile(record.run_id)
            return self._handle(record, reused=True)
        try:
            if record.checkpoint_dir.exists():
                raise ServiceError("new run checkpoint already exists")
            record.checkpoint_dir.mkdir(mode=0o700)
            atomic_text(record.checkpoint_dir / "experiment.md", request.experiment_md)
            atomic_json(
                record.checkpoint_dir / "request.json",
                request.model_dump(mode="json"),
            )
            self._sync_meta(record)
            if self.config.dry_run:
                record = self._complete_dry_run(record)
            else:
                record = self.execution.launch(record)
            return self._handle(record)
        except Exception as exc:
            current = self.registry.get_system(record.run_id)
            if current.state not in TERMINAL_STATES:
                try:
                    current = self.registry.transition(
                        record.run_id,
                        "failed",
                        reason="launch failed",
                        error=str(exc)[:4096],
                    )
                    self._sync_meta(current)
                except InvalidTransitionError:
                    pass
            raise

    def _complete_dry_run(self, record: RunRecord) -> RunRecord:
        atomic_text(
            record.checkpoint_dir / "orchestrator.log",
            "ARI orchestrator dry run: command was not executed.\n",
        )
        record = self.registry.transition(
            record.run_id, "running", reason="dry-run validation"
        )
        record = self.registry.transition(
            record.run_id,
            "succeeded",
            reason="dry-run validation completed",
            exit_code=0,
        )
        self._sync_meta(record)
        return record

    def reconcile(self, run_id: str) -> RunRecord:
        record = self.registry.get_system(run_id)
        if record.state in TERMINAL_STATES:
            return record
        receipt = self.execution.receipt(record)
        receipt_state = str((receipt or {}).get("state") or "")
        if receipt_state in TERMINAL_STATES and receipt is not None:
            return self._settle_terminal_receipt(record, receipt_state, receipt)
        if record.state == "submitted":
            return self._reconcile_submitted(record, receipt)
        if process_matches(record.pid, record.pid_start_ticks):
            return record
        target: RunState = "cancelled" if record.cancel_requested else "failed"
        record = self.registry.transition(
            run_id,
            target,
            reason="runner process disappeared without terminal receipt",
            error=None if target == "cancelled" else "runner process disappeared",
        )
        self._sync_meta(record)
        return record

    def _settle_terminal_receipt(
        self,
        record: RunRecord,
        receipt_state: str,
        receipt: dict[str, Any],
    ) -> RunRecord:
        if record.state == "submitted":
            try:
                record = self.registry.attach_process(
                    record.run_id,
                    pid=int(receipt["wrapper_pid"]),
                    pid_start_ticks=int(receipt["wrapper_start_ticks"]),
                )
            except InvalidTransitionError:
                record = self.registry.get_system(record.run_id)
        target = (
            "cancelled"
            if record.cancel_requested and receipt_state == "failed"
            else receipt_state
        )
        try:
            record = self.registry.transition(
                record.run_id,
                cast(RunState, target),
                reason="verified runner receipt",
                exit_code=receipt["exit_code"],
                error=receipt.get("error"),
            )
        except InvalidTransitionError:
            record = self.registry.get_system(record.run_id)
        self._sync_meta(record)
        return record

    def _reconcile_submitted(
        self, record: RunRecord, receipt: dict[str, Any] | None
    ) -> RunRecord:
        if receipt is not None and process_matches(
            receipt["wrapper_pid"], receipt["wrapper_start_ticks"]
        ):
            try:
                record = self.registry.attach_process(
                    record.run_id,
                    pid=receipt["wrapper_pid"],
                    pid_start_ticks=receipt["wrapper_start_ticks"],
                )
                self._sync_meta(record)
            except InvalidTransitionError:
                record = self.registry.get_system(record.run_id)
            return record
        try:
            created = datetime.fromisoformat(record.created_at)
            age = (datetime.now(timezone.utc) - created).total_seconds()
        except (TypeError, ValueError):
            age = 31.0
        if age <= 30.0:
            return record
        record = self.registry.transition(
            record.run_id,
            "failed",
            reason="launch authority disappeared before process attachment",
            error="run was submitted but no durable process identity was attached",
        )
        self._sync_meta(record)
        return record

    def status(self, run_id: str, principal: PrincipalV1) -> RunStatusV1:
        authorized = self.registry.get(run_id, principal)
        record = self.reconcile(authorized.run_id)
        if record.principal_id != principal.principal_id and not principal.is_admin:
            raise AuthorizationError("principal is not authorized for this run")
        total, successful, best_id, best_score = node_summary(record)
        return RunStatusV1(
            run_id=record.run_id,
            request_digest=record.request_digest,
            principal_id=record.principal_id,
            parent_run_id=record.parent_run_id,
            root_run_id=record.root_run_id,
            recursion_depth=record.recursion_depth,
            max_recursion_depth=record.max_recursion_depth,
            state=record.state,
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            exit_code=record.exit_code,
            error=record.error,
            cancel_requested=record.cancel_requested,
            total_nodes=total,
            successful_nodes=successful,
            best_node_id=best_id,
            best_score=best_score,
            budget=self.registry.lineage_usage(record.root_run_id),
        )

    def list_runs(self, principal: PrincipalV1) -> list[RunHandleV1]:
        return [
            self._handle(self.reconcile(record.run_id))
            for record in self.registry.list(principal)
        ]

    def list_children(
        self, parent_run_id: str, principal: PrincipalV1
    ) -> list[RunHandleV1]:
        self.registry.get(parent_run_id, principal)
        return [
            self._handle(self.reconcile(record.run_id))
            for record in self.registry.list(principal, parent_run_id=parent_run_id)
        ]

    def stop(self, run_id: str, principal: PrincipalV1) -> RunStatusV1:
        record = self.registry.request_cancellation(run_id, principal)
        self._sync_meta(record)
        if record.state in TERMINAL_STATES:
            return self.status(run_id, principal)
        if not process_matches(record.pid, record.pid_start_ticks):
            record = self.registry.transition(
                run_id,
                "cancelled",
                reason="runner already absent at cancellation",
            )
            self._sync_meta(record)
            return self.status(run_id, principal)
        assert record.pid is not None
        try:
            os.kill(record.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + self.config.cancellation_grace_seconds
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if self.reconcile(run_id).state in TERMINAL_STATES:
                return self.status(run_id, principal)
        self._escalate_cancellation(record)
        try:
            record = self.registry.transition(
                run_id,
                "cancelled",
                reason="cancellation escalated after grace period",
            )
        except InvalidTransitionError:
            record = self.registry.get_system(run_id)
        self._sync_meta(record)
        return self.status(run_id, principal)

    def _escalate_cancellation(self, record: RunRecord) -> None:
        receipt = self.execution.receipt(record) or {}
        child_pid = receipt.get("child_pid")
        child_ticks = receipt.get("child_start_ticks")
        if (
            isinstance(child_pid, int)
            and not isinstance(child_pid, bool)
            and isinstance(child_ticks, int)
            and not isinstance(child_ticks, bool)
            and process_matches(child_pid, child_ticks)
        ):
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process_matches(record.pid, record.pid_start_ticks):
            assert record.pid is not None
            try:
                os.killpg(record.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def list_artifacts(
        self, run_id: str, principal: PrincipalV1
    ) -> list[dict[str, Any]]:
        record = self.registry.get(run_id, principal)
        return [
            item.reference.model_dump(mode="json")
            for item in inventory(record.run_id, record.checkpoint_dir)
        ]

    def read_artifact(
        self, run_id: str, artifact_id: str, principal: PrincipalV1
    ) -> dict[str, Any]:
        record = self.registry.get(run_id, principal)
        return read_inline(record.checkpoint_dir, record.run_id, artifact_id)

    def result(self, run_id: str, principal: PrincipalV1) -> RunResultV1:
        status = self.status(run_id, principal)
        record = self.registry.get(run_id, principal)
        refs = tuple(
            item.reference for item in inventory(record.run_id, record.checkpoint_dir)
        )
        return RunResultV1(
            run_id=record.run_id,
            request_digest=record.request_digest,
            state=status.state,
            exit_code=status.exit_code,
            error=status.error,
            artifacts=refs,
        )

    def paper(self, run_id: str, principal: PrincipalV1) -> dict[str, Any]:
        record = self.registry.get(run_id, principal)
        selected = [
            item.reference.model_dump(mode="json")
            for item in inventory(record.run_id, record.checkpoint_dir)
            if item.reference.role in {"paper-tex", "paper-pdf"}
            or item.reference.media_type in {"application/pdf", "text/x-tex"}
        ]
        return {"run_id": run_id, "artifacts": selected}

    def ear(self, run_id: str, principal: PrincipalV1) -> dict[str, Any]:
        ear_roles = {
            "ear-manifest",
            "ear-output",
            "evidence-index",
            "skills-lock",
            "catalog-lock",
            "cassette",
            "admission",
            "science-contract",
            "result-envelope-artifact",
        }
        selected = [
            item
            for item in self.list_artifacts(run_id, principal)
            if item["role"] in ear_roles
        ]
        return {"run_id": run_id, "artifacts": selected}

    def list_skills(self, run_id: str, principal: PrincipalV1) -> dict[str, Any]:
        view = locked_view(self.registry, run_id, principal)
        return {
            "run_id": run_id,
            "registry_digest": view["registry_digest"],
            "skills": view["skills"],
            "tools": view["tools"],
        }

    def workflow(self, run_id: str, principal: PrincipalV1) -> dict[str, Any]:
        view = locked_view(self.registry, run_id, principal)
        return {
            "run_id": run_id,
            "registry_digest": view["registry_digest"],
            "phase_active_tools": view["phase_active_tools"],
            "disabled_tools": view["disabled_tools"],
        }

    def repair_legacy_registry(self, principal: PrincipalV1) -> dict[str, Any]:
        return repair_legacy_registry(self.config, self.registry, principal)


__all__ = [
    "ArtifactPolicyError",
    "OrchestratorService",
    "QuotaPolicy",
    "ResourcePolicyError",
    "ServiceConfig",
    "ServiceError",
]
