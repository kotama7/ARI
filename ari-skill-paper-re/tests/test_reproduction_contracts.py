from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from contracts import ReproductionContractError, ReproductionRunV1  # noqa: E402
from sandbox import (  # noqa: E402
    begin_attempt,
    classify_failure,
    execute_container_attempt,
    execute_local_attempt,
    finalize_attempt,
    load_run,
    prepare_reproduction,
    resolve_latest_run,
)


def _workspace(tmp_path: Path, script: str) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    reproduce = workspace / "reproduce.sh"
    reproduce.write_text("#!/usr/bin/env bash\nset -u\n" + script)
    reproduce.chmod(0o755)
    (workspace / "input.txt").write_text("immutable input\n")
    return workspace


def _prepare(workspace: Path, **overrides):
    values = {
        "source_workspace": str(workspace),
        "rubric_schema_version": "ari.replication-rubric/v2",
        "rubric_sha256": "a" * 64,
        "sandbox_kind": "local",
        "container_image": "",
        "timeout_seconds": 10,
        "expected_artifacts": ["result.txt"],
        "network_policy": "inherit",
        "network_isolation_attested": False,
        "resources": {},
    }
    values.update(overrides)
    return prepare_reproduction(**values)


def test_local_default_network_denial_requires_enforcement(tmp_path: Path):
    workspace = _workspace(tmp_path, "echo result > result.txt\n")
    with pytest.raises(ReproductionContractError, match="cannot prove network denial"):
        _prepare(workspace, network_policy="deny")


def test_mutable_container_reference_is_rejected(tmp_path: Path):
    workspace = _workspace(tmp_path, "echo result > result.txt\n")
    with pytest.raises(ReproductionContractError, match="sha256"):
        _prepare(
            workspace,
            sandbox_kind="docker",
            container_image="ubuntu:latest",
        )


def test_full_local_docker_image_id_is_accepted(tmp_path: Path):
    workspace = _workspace(tmp_path, "echo result > result.txt\n")
    prepared = _prepare(
        workspace,
        sandbox_kind="docker",
        container_image="sha256:" + "c" * 64,
    )
    assert prepared.plan.image is not None
    assert prepared.plan.image.digest == "sha256:" + "c" * 64


@pytest.mark.asyncio
async def test_private_attempt_is_content_bound_secret_free_and_resolvable(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("TOP_SECRET_TOKEN", "must-not-leak")
    workspace = _workspace(
        tmp_path,
        "env > environment.txt\ncp input.txt result.txt\n",
    )
    prepared = _prepare(workspace)
    attempt = begin_attempt(prepared, None)
    execution = await execute_local_attempt(prepared, attempt)
    run, pointer = finalize_attempt(prepared, attempt, execution, None)

    assert run.status == "succeeded"
    assert run.selected_attempt_id == attempt.attempt_id
    assert run.attempts[0].execution_identity
    identity = run.attempts[0].environment["identity"]
    assert identity["machine"]
    assert identity["kernel"]
    assert "gcc" in identity["compilers"]
    assert "logical_count" in identity["cpu"]
    assert ReproductionRunV1.model_validate_json(prepared.run_path.read_text()) == run
    assert pointer.is_file()
    assert not (workspace / "result.txt").exists()
    assert (attempt.work_dir / "result.txt").read_text() == "immutable input\n"
    environment = (attempt.work_dir / "environment.txt").read_text()
    assert "TOP_SECRET_TOKEN" not in environment
    assert "must-not-leak" not in environment
    assert oct((prepared.input_dir / "input.txt").stat().st_mode & 0o777) == "0o444"

    resolved = resolve_latest_run(workspace)
    assert resolved is not None
    resolved_run, executed_workspace = resolved
    assert resolved_run.run_digest == run.run_digest
    assert executed_workspace == attempt.work_dir
    assert load_run(prepared) == run


@pytest.mark.asyncio
async def test_missing_expected_artifact_is_a_failed_attempt_not_success(
    tmp_path: Path,
):
    workspace = _workspace(tmp_path, "echo completed without output\n")
    prepared = _prepare(workspace)
    attempt = begin_attempt(prepared, None)
    execution = await execute_local_attempt(prepared, attempt)
    run, _ = finalize_attempt(prepared, attempt, execution, None)
    assert run.status == "failed"
    assert run.selected_attempt_id is None
    assert run.attempts[0].expected_missing == ("result.txt",)
    assert run.attempts[0].failure.kind == "filesystem-policy"


@pytest.mark.asyncio
async def test_timeout_terminates_descendant_and_records_partial_attempt(
    tmp_path: Path,
):
    workspace = _workspace(
        tmp_path,
        "sleep 60 &\necho $! > child.pid\nwait\n",
    )
    prepared = _prepare(
        workspace,
        timeout_seconds=1,
        expected_artifacts=[],
    )
    attempt = begin_attempt(prepared, None)
    execution = await execute_local_attempt(prepared, attempt)
    run, _ = finalize_attempt(prepared, attempt, execution, None)
    assert run.status == "timed_out"
    assert run.attempts[0].failure.kind == "timeout"
    child_pid = int((attempt.work_dir / "child.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, signal.SIGCONT)


@pytest.mark.asyncio
async def test_container_cancel_terminates_launcher_descendants(
    tmp_path: Path, monkeypatch
):
    workspace = _workspace(tmp_path, "echo unused > result.txt\n")
    prepared = _prepare(
        workspace,
        sandbox_kind="docker",
        container_image="example.invalid/repro@sha256:" + "b" * 64,
        expected_artifacts=[],
    )
    attempt = begin_attempt(prepared, None)
    child_path = attempt.work_dir / "container-child.pid"
    monkeypatch.setattr(
        "sandbox._external_command",
        lambda _prepared, _attempt: (
            [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                f"sleep 60 & echo $! > {child_path}; wait",
            ],
            None,
        ),
    )

    task = asyncio.create_task(execute_container_attempt(prepared, attempt))
    for _ in range(200):
        if child_path.is_file():
            break
        await asyncio.sleep(0.01)
    assert child_path.is_file()
    task.cancel()
    execution = await task

    assert execution["status"] == "cancelled"
    child_pid = int(child_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, signal.SIGCONT)


def test_input_symlink_is_rejected(tmp_path: Path):
    workspace = _workspace(tmp_path, "echo result > result.txt\n")
    (workspace / "escape").symlink_to("/etc/passwd")
    with pytest.raises(ReproductionContractError, match="contains a symlink"):
        _prepare(workspace)


def test_symlink_workspace_root_is_rejected(tmp_path: Path):
    workspace = _workspace(tmp_path, "echo result > result.txt\n")
    linked = tmp_path / "linked-repo"
    linked.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(ReproductionContractError, match="real directory"):
        _prepare(linked)


@pytest.mark.asyncio
async def test_malicious_outputs_are_removed_and_fail_the_attempt(tmp_path: Path):
    workspace = _workspace(
        tmp_path,
        "ln -s /etc/passwd result.txt\nmkfifo pipe.out\n",
    )
    prepared = _prepare(workspace)
    attempt = begin_attempt(prepared, None)
    execution = await execute_local_attempt(prepared, attempt)
    run, _ = finalize_attempt(prepared, attempt, execution, None)

    assert run.status == "failed"
    assert run.attempts[0].failure.kind == "filesystem-policy"
    assert "symlink" in run.attempts[0].failure.message
    assert not (attempt.work_dir / "result.txt").exists()
    assert not (attempt.work_dir / "pipe.out").exists()


@pytest.mark.parametrize(
    "status,exit_code,log_text,expected",
    [
        ("failed", 137, "killed", "oom"),
        ("failed", 1, "python: No module named scipy", "missing-dependency"),
        ("failed", 1, "CUDA driver not available", "gpu-mismatch"),
        ("failed", 1, "Read-only file system", "filesystem-policy"),
        ("cancelled", None, "", "cancelled"),
    ],
)
def test_failure_corpus_is_typed(status, exit_code, log_text, expected):
    assert classify_failure(status, exit_code, log_text).kind == expected


def test_checked_in_reproduction_schemas_have_no_drift():
    result = subprocess.run(
        [sys.executable, str(SRC.parent / "scripts" / "sync_contracts.py")],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
