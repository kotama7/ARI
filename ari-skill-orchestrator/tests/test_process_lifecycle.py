from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ari_skill_orchestrator.contracts import PrincipalV1, RunRequestV1
from ari_skill_orchestrator.service import OrchestratorService, ServiceConfig


ALICE = PrincipalV1(principal_id="alice", authentication="test")


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


def _request(key: str) -> RunRequestV1:
    return RunRequestV1.from_parameters(
        experiment_md="# process test\nrun",
        idempotency_key=key,
        timeout_minutes=1,
    )


def _service(tmp_path: Path, cli: Path, *, grace: float = 2.0) -> OrchestratorService:
    return OrchestratorService(
        ServiceConfig(
            workspace=tmp_path,
            logs_root=tmp_path / "logs",
            ari_cli=str(cli),
            cancellation_grace_seconds=grace,
        )
    )


def _wait_terminal(service: OrchestratorService, run_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.status(run_id, ALICE)
        if status.state in {"succeeded", "failed", "cancelled"}:
            return status
        time.sleep(0.05)
    raise AssertionError("run did not become terminal")


def test_restart_reconciles_verified_runner_receipt(tmp_path: Path) -> None:
    cli = _script(
        tmp_path / "fake-ari",
        'sleep 0.2\nprintf \'{"nodes":{}}\' > "$ARI_CHECKPOINT_DIR/results.json"\n',
    )
    first_service = _service(tmp_path, cli)
    handle = first_service.submit(_request("restart"), ALICE)
    assert handle.state == "running"
    restarted_service = _service(tmp_path, cli)
    status = _wait_terminal(restarted_service, handle.run_id)
    assert status.state == "succeeded"
    assert status.exit_code == 0
    assert len(restarted_service.registry.events(handle.run_id)) == 3


def test_stop_propagates_to_child_process_group(tmp_path: Path) -> None:
    cli = _script(
        tmp_path / "slow-ari",
        'printf \'%s\' "$$" > "$ARI_CHECKPOINT_DIR/fake_cli_pid"\nsleep 30\n',
    )
    control = _service(tmp_path, cli, grace=1.0)
    handle = control.submit(_request("cancel"), ALICE)
    record = control.registry.get(handle.run_id, ALICE)
    pid_file = record.checkpoint_dir / "fake_cli_pid"
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    status = control.stop(handle.run_id, ALICE)
    assert status.state == "cancelled"
    time.sleep(0.1)
    with __import__("pytest").raises(ProcessLookupError):
        os.kill(child_pid, 0)
    events = control.registry.events(handle.run_id)
    assert [event["to_state"] for event in events].count("cancelled") == 1


def test_child_environment_is_allowlisted_not_parent_copy(
    tmp_path: Path, monkeypatch
) -> None:
    cli = _script(
        tmp_path / "env-ari",
        'env | sort > "$ARI_CHECKPOINT_DIR/child.env"\n',
    )
    monkeypatch.setenv("UNDECLARED_SECRET", "must-not-cross")
    monkeypatch.setenv("OPENAI_API_KEY", "scoped-test-value")
    control = _service(tmp_path, cli)
    handle = control.submit(_request("environment"), ALICE)
    assert _wait_terminal(control, handle.run_id).state == "succeeded"
    record = control.registry.get(handle.run_id, ALICE)
    child_environment = (record.checkpoint_dir / "child.env").read_text()
    assert "UNDECLARED_SECRET" not in child_environment
    assert "must-not-cross" not in child_environment
    assert "OPENAI_API_KEY=scoped-test-value" in child_environment
    assert "OMP_NUM_THREADS=1" in child_environment
    assert "MKL_NUM_THREADS=1" in child_environment
    request_document = json.loads((record.checkpoint_dir / "request.json").read_text())
    assert "scoped-test-value" not in json.dumps(request_document)


def test_terminal_receipt_recovers_crash_before_process_attachment(
    tmp_path: Path,
) -> None:
    control = _service(tmp_path, tmp_path / "unused")
    record, reused = control.registry.claim(
        _request("pre-attach-recovery"), ALICE, max_active_runs=16
    )
    assert reused is False
    record.runner_receipt.write_text(
        json.dumps(
            {
                "schema_version": "ari.orchestrator-runner-receipt/v1",
                "run_id": record.run_id,
                "request_digest": record.request_digest,
                "wrapper_pid": os.getpid(),
                "wrapper_start_ticks": 7,
                "state": "succeeded",
                "started_at": record.created_at,
                "child_pid": None,
                "child_start_ticks": None,
                "exit_code": 0,
                "completed_at": record.created_at,
                "error": None,
            }
        )
    )
    recovered = control.reconcile(record.run_id)
    assert recovered.state == "succeeded"
    assert [event["to_state"] for event in control.registry.events(record.run_id)] == [
        "submitted",
        "running",
        "succeeded",
    ]


def test_receipt_must_match_attached_process_identity(tmp_path: Path) -> None:
    from ari_skill_orchestrator.runtime import process_start_ticks

    control = _service(tmp_path, tmp_path / "unused")
    record, _reused = control.registry.claim(
        _request("receipt-identity"), ALICE, max_active_runs=16
    )
    ticks = process_start_ticks(os.getpid())
    assert ticks is not None
    record = control.registry.attach_process(
        record.run_id, pid=os.getpid(), pid_start_ticks=ticks
    )
    record.runner_receipt.write_text(
        json.dumps(
            {
                "schema_version": "ari.orchestrator-runner-receipt/v1",
                "run_id": record.run_id,
                "request_digest": record.request_digest,
                "wrapper_pid": os.getpid(),
                "wrapper_start_ticks": ticks + 1,
                "state": "succeeded",
                "child_pid": None,
                "child_start_ticks": None,
                "exit_code": 0,
                "completed_at": record.created_at,
                "error": None,
            }
        )
    )
    assert control.reconcile(record.run_id).state == "running"


def test_cancellation_before_process_attachment_cannot_leave_orphan(
    tmp_path: Path, monkeypatch
) -> None:
    cli = _script(
        tmp_path / "attach-race-ari",
        'printf \'%s\' "$$" > "$ARI_CHECKPOINT_DIR/attach_race_pid"\nsleep 30\n',
    )
    control = _service(tmp_path, cli, grace=1.0)
    original_attach = control.registry.attach_process

    def cancel_then_attach(run_id: str, *, pid: int, pid_start_ticks: int):
        control.registry.request_cancellation(run_id, ALICE)
        return original_attach(run_id, pid=pid, pid_start_ticks=pid_start_ticks)

    monkeypatch.setattr(control.registry, "attach_process", cancel_then_attach)
    handle = control.submit(_request("attach-race"), ALICE)
    assert handle.state == "cancelled"
    record = control.registry.get(handle.run_id, ALICE)
    pid_file = record.checkpoint_dir / "attach_race_pid"
    if pid_file.is_file():
        child_pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
