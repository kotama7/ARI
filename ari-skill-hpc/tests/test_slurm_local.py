"""Conformance tests for the local, provider-neutral SLURM adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari_skill_hpc.contracts import (
    ArtifactPinV1,
    ContainerRequestV1,
    EnvironmentPolicyV1,
    JobRequestV1,
    OutputDeclarationV1,
    ResourceRequestV1,
    file_digest,
    sha256_digest,
)
from ari_skill_hpc.scheduler import (
    CommandResult,
    LocalCommandRunner,
    SchedulerProtocolError,
    SchedulerTransportError,
    SchedulerValidationError,
    SlurmScheduler,
    SubmissionLedger,
    SubmissionUncertainError,
)


class FakeRunner:
    def __init__(self, *responses: CommandResult | Exception):
        self.responses = list(responses)
        self.calls: list[tuple[list[str], bytes | None]] = []
        self.closed = False

    @property
    def identity(self):
        return {"transport": "fake", "cluster": "test-cluster"}

    async def run(self, argv, *, stdin=None, timeout=None):
        self.calls.append((list(argv), stdin))
        if not self.responses:
            raise AssertionError(f"unexpected scheduler command: {argv}")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


def _input_pin(path: Path, logical_name: str = "design-input") -> ArtifactPinV1:
    return ArtifactPinV1(
        logical_name=logical_name,
        path=str(path),
        digest=file_digest(path),
        size_bytes=path.stat().st_size,
        media_type="text/plain",
    )


def _request(work_dir: Path, *, modules: tuple[str, ...] = ()) -> JobRequestV1:
    source = work_dir / "input.txt"
    if not source.exists():
        source.write_text("scientific input\n", encoding="utf-8")
    return JobRequestV1(
        request_id="experiment-001",
        job_name="openroad-flow",
        work_dir=str(work_dir),
        argv=("python3", "worker.py", "argument;not-shell"),
        resources=ResourceRequestV1(
            partition="compute-a64fx",
            nodes=2,
            tasks=4,
            cpus_per_task=8,
            memory_mb_per_node=65536,
            walltime="02:00:00",
        ),
        environment=EnvironmentPolicyV1(
            variables={"OMP_NUM_THREADS": "8", "EXPERIMENT_MODE": "golden"},
            modules=modules,
        ),
        inputs=(_input_pin(source),),
        outputs=(
            OutputDeclarationV1(
                logical_name="metrics-json",
                path=str(work_dir / "metrics.json"),
                media_type="application/json",
            ),
        ),
        metadata={"domain": "eda", "profile": "nangate45"},
    )


def _scheduler(tmp_path: Path, runner: FakeRunner) -> SlurmScheduler:
    return SlurmScheduler(
        runner=runner,
        ledger=SubmissionLedger(tmp_path / "state" / "jobs.json"),
    )


@pytest.mark.asyncio
async def test_submit_is_prompt_clean_and_idempotent(tmp_path: Path) -> None:
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path, modules=("gcc/13.2", "openroad/2.0"))

    first = await scheduler.submit(request)
    second = await scheduler.submit(request)

    assert first == second
    assert first.job_id == "12345"
    assert first.request_digest == request.request_digest
    assert len(runner.calls) == 1
    argv, raw_script = runner.calls[0]
    assert argv == ["sbatch", "--parsable", "--export=NIL"]
    script = raw_script.decode()
    assert "#SBATCH --export=NIL" in script
    assert "#SBATCH --partition=compute-a64fx" in script
    assert "#SBATCH --nodes=2" in script
    assert "export SLURM_EXPORT_ENV=ALL" in script
    assert "module load gcc/13.2" in script
    assert "cpu_model=" in script
    assert "cpu_logical_count=" in script
    assert "gcc=" in script
    assert "mpicc=" in script
    assert "nvcc=" in script
    assert "gpu=" in script
    assert "source " not in script
    assert ".env" not in script
    assert "ARI_ENV_FILE" not in script
    assert "'argument;not-shell'" in script
    assert "worker.py argument;not-shell" not in script
    assert request.inputs[0].digest.removeprefix("sha256:") in script
    submission = Path(first.artifact_scope) / "submission-v1.json"
    assert submission.is_file()
    assert oct(submission.stat().st_mode & 0o777) == "0o600"


@pytest.mark.asyncio
async def test_container_can_enforce_network_none_without_shell(tmp_path: Path) -> None:
    image = tmp_path / "openroad.sif"
    image.write_bytes(b"pinned image\n")
    runner = FakeRunner(CommandResult("12347\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    base = _request(tmp_path)
    request = base.model_copy(
        update={
            "container": ContainerRequestV1(
                image=ArtifactPinV1(
                    logical_name="openroad-image",
                    path=str(image),
                    digest=file_digest(image),
                    size_bytes=image.stat().st_size,
                ),
                network="none",
            )
        }
    )

    await scheduler.submit(request)

    script = runner.calls[0][1].decode()
    assert "apptainer exec --containall --cleanenv --net --network none" in script


@pytest.mark.asyncio
async def test_submit_renders_extended_resources_without_escape_hatch(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(CommandResult("12346\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    base = _request(tmp_path)
    request = JobRequestV1.model_validate(
        {
            **base.model_dump(mode="json"),
            "resources": {
                "partition": "compute",
                "nodes": 4,
                "tasks": 32,
                "tasks_per_node": 8,
                "cpus_per_task": 2,
                "memory_mb_per_cpu": 4096,
                "gpus_per_task": 1,
                "gpu_type": "v100",
                "walltime": "02:00:00",
                "nodelist": "node[01-04]",
                "exclude_nodes": "node03",
                "exclusive": True,
                "constraint": "skylake|haswell",
                "hint": "nomultithread",
                "account": "projX",
                "qos": "normal",
                "reservation": "paperbench",
            },
        }
    )

    await scheduler.submit(request)

    script = runner.calls[0][1].decode()
    for directive in (
        "#SBATCH --ntasks-per-node=8",
        "#SBATCH --nodelist=node[01-04]",
        "#SBATCH --exclude=node03",
        "#SBATCH --mem-per-cpu=4096M",
        "#SBATCH --gpus-per-task=v100:1",
        "#SBATCH --constraint=skylake|haswell",
        "#SBATCH --hint=nomultithread",
        "#SBATCH --account=projX",
        "#SBATCH --qos=normal",
        "#SBATCH --reservation=paperbench",
    ):
        assert directive in script
    assert "extra_sbatch_args" not in script


@pytest.mark.asyncio
async def test_definite_rejection_releases_claim_for_retry(tmp_path: Path) -> None:
    runner = FakeRunner(
        CommandResult("", "invalid partition", 1),
        CommandResult("222", "", 0),
    )
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path)
    with pytest.raises(SchedulerProtocolError, match="invalid partition"):
        await scheduler.submit(request)
    handle = await scheduler.submit(request)
    assert handle.job_id == "222"
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_uncertain_transport_failure_never_duplicates_job(tmp_path: Path) -> None:
    runner = FakeRunner(RuntimeError("connection dropped after stdin"))
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path)
    with pytest.raises(RuntimeError, match="connection dropped"):
        await scheduler.submit(request)
    with pytest.raises(SubmissionUncertainError, match="refusing to duplicate"):
        await scheduler.submit(request)
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_committed_handle_survives_scheduler_restart(tmp_path: Path) -> None:
    ledger_path = tmp_path / "state" / "jobs.json"
    first_runner = FakeRunner(CommandResult("333", "", 0))
    first = SlurmScheduler(runner=first_runner, ledger=SubmissionLedger(ledger_path))
    request = _request(tmp_path)
    handle = await first.submit(request)

    restarted_runner = FakeRunner()
    restarted = SlurmScheduler(
        runner=restarted_runner, ledger=SubmissionLedger(ledger_path)
    )
    recovered = await restarted.submit(request)

    assert recovered == handle
    assert restarted_runner.calls == []


@pytest.mark.asyncio
async def test_status_normalizes_sacct_and_squeue_states(tmp_path: Path) -> None:
    runner = FakeRunner(
        CommandResult(
            "91|COMPLETED|0:0|2026-08-02T01:00:00|2026-08-02T01:02:00|None\n",
            "",
            0,
        ),
        CommandResult("", "accounting delayed", 1),
        CommandResult("PENDING|Resources\n", "", 0),
    )
    scheduler = _scheduler(tmp_path, runner)
    completed = await scheduler.status("91")
    pending = await scheduler.status("92")
    assert completed.state == "succeeded"
    assert completed.scheduler_state == "COMPLETED"
    assert completed.exit_code == 0
    assert pending.state == "submitted"
    assert pending.reason == "Resources"


@pytest.mark.asyncio
async def test_cancel_rejects_job_id_injection_before_transport(tmp_path: Path) -> None:
    runner = FakeRunner()
    scheduler = _scheduler(tmp_path, runner)
    with pytest.raises(SchedulerValidationError, match="invalid job handle"):
        await scheduler.cancel("123; touch /tmp/pwn")
    assert runner.calls == []


@pytest.mark.asyncio
async def test_output_cannot_escape_through_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    linked = tmp_path / "linked-output"
    linked.symlink_to(outside, target_is_directory=True)
    payload = _request(tmp_path).model_dump(mode="json")
    payload["outputs"] = [
        {
            "logical_name": "escaped-output",
            "path": str(linked / "result.json"),
        }
    ]
    request = JobRequestV1.model_validate(payload)
    runner = FakeRunner()
    scheduler = _scheduler(tmp_path, runner)
    with pytest.raises(SchedulerValidationError, match="parent is missing or unsafe"):
        await scheduler.submit(request)
    assert runner.calls == []


@pytest.mark.asyncio
async def test_terminal_result_rehashes_outputs_logs_and_provenance(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        CommandResult("7001", "", 0),
        CommandResult(
            "7001|COMPLETED|0:0|2026-08-02T01:00:00|2026-08-02T01:02:00|None",
            "",
            0,
        ),
    )
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path, modules=("openroad/2.0",))
    handle = await scheduler.submit(request)
    Path(request.outputs[0].path).write_text('{"wns": 0.1}\n', encoding="utf-8")
    scope = Path(handle.artifact_scope)
    (scope / "slurm-7001.out").write_text("flow complete\n", encoding="utf-8")
    (scope / "slurm-7001.err").write_text("", encoding="utf-8")
    (scope / "module-list.txt").write_text("openroad/2.0\n", encoding="utf-8")
    (scope / "exit-code.txt").write_text("0\n", encoding="utf-8")

    result = await scheduler.result(handle.handle_id)

    assert result.status.state == "succeeded"
    assert result.error is None
    assert result.outputs[0].digest == file_digest(Path(request.outputs[0].path))
    assert result.module_snapshot_digest == file_digest(scope / "module-list.txt")
    assert {item.logical_name for item in result.provenance} == {
        "submission-record",
        "module-snapshot",
        "exit-code",
    }
    assert result.logs[0].digest == file_digest(scope / "slurm-7001.out")
    payload = result.model_dump(mode="json")
    declared = payload.pop("result_digest")
    assert declared == sha256_digest(payload)
    assert (scope / "result-v1.json").is_file()


@pytest.mark.asyncio
async def test_result_detects_input_drift(tmp_path: Path) -> None:
    runner = FakeRunner(
        CommandResult("8001", "", 0),
        CommandResult(
            "8001|COMPLETED|0:0|2026-08-02T01:00:00|2026-08-02T01:02:00|None",
            "",
            0,
        ),
    )
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path)
    handle = await scheduler.submit(request)
    Path(request.inputs[0].path).write_text("mutated\n", encoding="utf-8")
    Path(request.outputs[0].path).write_text("{}\n", encoding="utf-8")
    result = await scheduler.result(handle.handle_id)
    assert result.error is not None
    assert result.error.kind == "artifact"
    assert "drift" in result.error.message


@pytest.mark.asyncio
async def test_script_bridge_cannot_override_generated_directives(tmp_path: Path) -> None:
    runner = FakeRunner(CommandResult("9001", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    handle = await scheduler.submit_script_bridge(
        script="#SBATCH --partition=wrong\necho explicit-compute-body",
        job_name="bridge-job",
        partition="right",
        work_dir=str(tmp_path),
    )
    assert handle.job_id == "9001"
    script = runner.calls[0][1].decode()
    assert script.index("set -euo pipefail") < script.index("#SBATCH --partition=wrong")
    assert script.count("#SBATCH --partition=right") == 1
    assert "--export=NIL" in script
    assert "ARI_ENV_FILE" not in script


@pytest.mark.asyncio
async def test_local_runner_uses_exec_with_minimal_environment() -> None:
    process = AsyncMock()
    process.communicate.return_value = (b"123\n", b"")
    process.returncode = 0
    with patch(
        "asyncio.create_subprocess_exec", return_value=process
    ) as create_process:
        result = await LocalCommandRunner().run(
            ["sbatch", "--parsable"], stdin=b"#!/bin/bash\n"
        )
    assert result.stdout == "123"
    args, kwargs = create_process.call_args
    assert args == ("sbatch", "--parsable")
    assert kwargs["env"] == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    process.communicate.assert_awaited_once_with(input=b"#!/bin/bash\n")


@pytest.mark.asyncio
async def test_local_runner_reaps_timed_out_control_process() -> None:
    process = AsyncMock()
    process.communicate.side_effect = TimeoutError
    process.returncode = None
    process.kill = MagicMock()
    process.wait = AsyncMock()
    with patch("asyncio.create_subprocess_exec", return_value=process):
        with pytest.raises(SchedulerTransportError, match="timed out"):
            await LocalCommandRunner(command_timeout=0.01).run(["sacct", "-j", "1"])
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_runner_reports_missing_scheduler_without_shell_fallback() -> None:
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        with pytest.raises(SchedulerTransportError, match="unavailable"):
            await LocalCommandRunner().run(["sbatch", "--parsable"])


def test_submission_script_changes_when_argv_changes(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = FakeRunner()
    scheduler = _scheduler(tmp_path, runner)
    scope = scheduler._ensure_artifact_scope(str(tmp_path), request.request_digest)
    first = scheduler._render_script(request, scope)
    changed = request.model_copy(update={"argv": ("python3", "different.py")})
    second = scheduler._render_script(changed, scope)
    assert sha256_digest(first) != sha256_digest(second)
