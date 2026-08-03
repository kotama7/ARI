"""ARI wrapper launch, receipt validation, and attach-race settlement."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .registry import TERMINAL_STATES, InvalidTransitionError, RunRecord, RunRegistry
from .runtime import (
    ServiceConfig,
    ServiceError,
    model_context_environment,
    model_credential_environment,
    process_matches,
    process_start_ticks,
    safe_json_file,
)


class ExecutionManager:
    def __init__(
        self,
        config: ServiceConfig,
        registry: RunRegistry,
        sync_meta: Callable[[RunRecord], None],
        reconcile: Callable[[str], RunRecord],
    ) -> None:
        self.config = config
        self.registry = registry
        self.sync_meta = sync_meta
        self.reconcile = reconcile

    def launch_environment(self, record: RunRecord) -> dict[str, str]:
        try:
            from ari.public.execution import build_minimal_environment
        except ImportError as exc:
            raise ServiceError(
                "ari-core execution environment helper is unavailable"
            ) from exc

        request = record.request
        runtime_home_root = self.registry.state_root / "runtime-home"
        runtime_home_root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(runtime_home_root, 0o700)
        local_home = runtime_home_root / record.run_id
        local_home.mkdir(mode=0o700, exist_ok=True)
        explicit = {
            "HOME": str(local_home),
            "ARI_CHECKPOINT_DIR": str(record.checkpoint_dir),
            "ARI_PARENT_RUN_ID": record.run_id,
            "ARI_RECURSION_DEPTH": str(record.recursion_depth + 1),
            "ARI_MAX_RECURSION_DEPTH": str(record.max_recursion_depth),
            "ARI_MAX_NODES": str(request.max_nodes),
            "ARI_CPUS": str(request.cpus),
            "ARI_TIMEOUT_MINUTES": str(request.timeout_minutes),
            "OMP_NUM_THREADS": str(request.cpus),
            "MKL_NUM_THREADS": str(request.cpus),
            "OPENBLAS_NUM_THREADS": str(request.cpus),
            "NUMEXPR_MAX_THREADS": str(request.cpus),
            "VECLIB_MAXIMUM_THREADS": str(request.cpus),
        }
        optional = {
            "ARI_MODEL": request.model,
            "ARI_BACKEND": request.llm_backend,
            "ARI_EXECUTOR": request.executor,
            "ARI_RETRIEVAL_BACKEND": request.retrieval_backend,
        }
        explicit.update({name: value for name, value in optional.items() if value})
        environment = build_minimal_environment(explicit)
        environment.update(model_credential_environment())
        environment.update(model_context_environment())
        return environment

    def launch(self, record: RunRecord) -> RunRecord:
        runner = Path(__file__).with_name("runner.py")
        command = [
            sys.executable,
            str(runner),
            "--receipt",
            str(record.runner_receipt),
            "--log",
            str(record.checkpoint_dir / "orchestrator.log"),
            "--run-id",
            record.run_id,
            "--request-digest",
            record.request_digest,
            "--cwd",
            str(self.config.workspace),
            "--timeout-seconds",
            str(record.request.timeout_minutes * 60),
            "--cpus",
            str(record.request.cpus),
            "--",
            self.config.ari_cli,
            "run",
            str(record.checkpoint_dir / "experiment.md"),
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self.config.workspace),
            env=self.launch_environment(record),
            start_new_session=True,
        )
        ticks = self._bind_start_ticks(record, process)
        try:
            attached = self.registry.attach_process(
                record.run_id, pid=process.pid, pid_start_ticks=ticks
            )
        except InvalidTransitionError:
            current = self.registry.get_system(record.run_id)
            if current.pid == process.pid and current.pid_start_ticks == ticks:
                return current
            self._terminate_unattached(record, process, ticks)
            if current.state in TERMINAL_STATES:
                return current
            raise
        self.sync_meta(attached)
        self._start_reaper(record, process)
        return attached

    def _bind_start_ticks(
        self, record: RunRecord, process: subprocess.Popen[bytes]
    ) -> int:
        ticks = process_start_ticks(process.pid)
        if ticks is not None:
            return ticks
        deadline = time.monotonic() + 2.0
        receipt: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            receipt = safe_json_file(record.runner_receipt, max_bytes=64 * 1024)
            if receipt is not None:
                break
            time.sleep(0.01)
        if (
            receipt is not None
            and receipt.get("run_id") == record.run_id
            and receipt.get("request_digest") == record.request_digest
            and receipt.get("wrapper_pid") == process.pid
            and isinstance(receipt.get("wrapper_start_ticks"), int)
        ):
            return int(receipt["wrapper_start_ticks"])
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise ServiceError("cannot bind runner process identity")

    def _start_reaper(
        self, record: RunRecord, process: subprocess.Popen[bytes]
    ) -> None:
        def reap() -> None:
            return_code = process.wait()
            try:
                current = self.reconcile(record.run_id)
                if current.state not in TERMINAL_STATES:
                    target = "cancelled" if current.cancel_requested else "failed"
                    current = self.registry.transition(
                        record.run_id,
                        target,
                        reason="runner exited without a terminal receipt",
                        exit_code=return_code,
                    )
                    self.sync_meta(current)
            except Exception:
                # The durable status path repeats reconciliation on next access.
                return

        threading.Thread(
            target=reap,
            name=f"ari-orchestrator-reap-{record.run_id}",
            daemon=True,
        ).start()

    def _terminate_unattached(
        self,
        record: RunRecord,
        process: subprocess.Popen[bytes],
        wrapper_ticks: int,
    ) -> None:
        """Settle a wrapper that lost the atomic attach/cancel race."""

        if process.poll() is None:
            try:
                os.kill(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + self.config.cancellation_grace_seconds
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        receipt = safe_json_file(record.runner_receipt, max_bytes=64 * 1024) or {}
        if (
            receipt.get("run_id") == record.run_id
            and receipt.get("request_digest") == record.request_digest
            and receipt.get("wrapper_pid") == process.pid
            and receipt.get("wrapper_start_ticks") == wrapper_ticks
        ):
            self._kill_receipt_child(receipt)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired as exc:
            raise ServiceError("unattached runner could not be reaped") from exc

    @staticmethod
    def _kill_receipt_child(receipt: dict[str, Any]) -> None:
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

    def receipt(self, record: RunRecord) -> dict[str, Any] | None:
        value = safe_json_file(record.runner_receipt, max_bytes=64 * 1024)
        if value is None or not self._valid_wrapper_fields(value, record):
            return None
        if not self._valid_child_fields(value):
            return None
        if value["state"] in TERMINAL_STATES and not self._valid_terminal_fields(value):
            return None
        return value

    @staticmethod
    def _valid_wrapper_fields(value: dict[str, Any], record: RunRecord) -> bool:
        state = value.get("state")
        wrapper_pid = value.get("wrapper_pid")
        wrapper_ticks = value.get("wrapper_start_ticks")
        structurally_valid = (
            value.get("schema_version") == "ari.orchestrator-runner-receipt/v1"
            and value.get("run_id") == record.run_id
            and value.get("request_digest") == record.request_digest
            and state in {"starting", "running", "succeeded", "failed", "cancelled"}
            and isinstance(wrapper_pid, int)
            and not isinstance(wrapper_pid, bool)
            and wrapper_pid >= 1
            and isinstance(wrapper_ticks, int)
            and not isinstance(wrapper_ticks, bool)
            and wrapper_ticks >= 0
        )
        if not structurally_valid:
            return False
        return record.pid is None or (
            wrapper_pid == record.pid and wrapper_ticks == record.pid_start_ticks
        )

    @staticmethod
    def _valid_child_fields(value: dict[str, Any]) -> bool:
        child_pid = value.get("child_pid")
        child_ticks = value.get("child_start_ticks")
        valid_pid = child_pid is None or (
            isinstance(child_pid, int)
            and not isinstance(child_pid, bool)
            and child_pid >= 1
        )
        valid_ticks = child_ticks is None or (
            isinstance(child_ticks, int)
            and not isinstance(child_ticks, bool)
            and child_ticks >= 0
        )
        return (
            valid_pid
            and valid_ticks
            and not (child_ticks is not None and child_pid is None)
        )

    @staticmethod
    def _valid_terminal_fields(value: dict[str, Any]) -> bool:
        exit_code = value.get("exit_code")
        error = value.get("error")
        return (
            isinstance(exit_code, int)
            and not isinstance(exit_code, bool)
            and (error is None or isinstance(error, str))
            and not (isinstance(error, str) and len(error) > 4096)
            and isinstance(value.get("completed_at"), str)
        )


__all__ = ["ExecutionManager"]
