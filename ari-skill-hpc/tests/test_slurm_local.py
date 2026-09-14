"""Conformance tests for the local, provider-neutral SLURM adapter."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ari_skill_hpc.contracts import (
    AcceleratorDeviceIdentityV1,
    ArtifactPinV1,
    ContainerRequestV1,
    EnvironmentPolicyV1,
    ExclusiveNodeAcceleratorV1,
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


def _write_wrapper_completion(
    handle,
    raw_script: bytes,
    *,
    exit_code: int = 0,
    nonce: str | None = None,
) -> str:
    script = raw_script.decode("utf-8")
    match = re.search(r'completion_nonce":"([0-9a-f]{64})', script)
    assert match is not None
    expected_nonce = match.group(1)
    value = {
        "schema_version": "ari.hpc.wrapper-completion/v1",
        "request_digest": handle.request_digest,
        "cluster_identity": handle.cluster_identity,
        "job_id": handle.job_id,
        "exit_code": exit_code,
        "completion_nonce": nonce or expected_nonce,
    }
    (Path(handle.artifact_scope) / "wrapper-completion-v1.json").write_text(
        json.dumps(value), encoding="utf-8"
    )
    return expected_nonce


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
async def test_no_gres_gpu_uses_exclusive_node_and_frozen_inventory(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "nvidia-smi"
    probe.write_bytes(b"pinned nvidia-smi fixture\n")
    base = _request(tmp_path)
    request = base.model_copy(
        update={
            "resources": ResourceRequestV1(
                partition="gpu-private",
                nodes=1,
                tasks=1,
                cpus_per_task=1,
                walltime="00:05:00",
                nodelist="gpu-node-a",
                exclusive=True,
            ),
            "accelerator_allocation": ExclusiveNodeAcceleratorV1(
                partition="gpu-private",
                node_name="gpu-node-a",
                inventory_probe=ArtifactPinV1(
                    logical_name="nvidia-smi-inventory-probe",
                    path=str(probe),
                    digest=file_digest(probe),
                    size_bytes=probe.stat().st_size,
                ),
                devices=(
                    AcceleratorDeviceIdentityV1(
                        uuid="GPU-27714578-959a-9314-ad8a-21773f5e5649",
                        name="Tesla V100-SXM2-16GB",
                        driver_version="575.64.03",
                        memory_mb=16384,
                        compute_capability="7.0",
                    ),
                ),
            ),
        }
    )
    runner = FakeRunner(CommandResult("12348\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit(request)

    script = runner.calls[0][1].decode()
    assert "#SBATCH --nodelist=gpu-node-a" in script
    assert "#SBATCH --exclusive" in script
    assert "#SBATCH --gres" not in script
    assert "#SBATCH --gpus" not in script
    assert "accelerator-inventory.expected.csv" in script
    assert "accelerator-inventory.observed.csv" in script
    assert "--query-gpu=uuid,name,driver_version,memory.total,compute_cap" in script
    assert "exclusive-node accelerator inventory mismatch" in script
    assert probe.as_posix() in script
    assert file_digest(probe).removeprefix("sha256:") in script


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
async def test_fixed_wrapper_marker_closes_terminal_state_without_accounting(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        CommandResult("7301", "", 0),
        CommandResult("", "accounting storage is disabled", 1),
        CommandResult("", "", 0),
    )
    scheduler = SlurmScheduler(
        runner=runner,
        ledger=SubmissionLedger(tmp_path / "state/jobs.json"),
        terminal_evidence_policy="fixed-wrapper-marker",
    )
    handle = await scheduler.submit(_request(tmp_path))
    raw_script = runner.calls[0][1]
    assert raw_script is not None
    nonce = _write_wrapper_completion(handle, raw_script)

    status = await scheduler.status(handle.handle_id)

    assert status.state == "succeeded"
    assert status.scheduler_state == "COMPLETED"
    assert status.exit_code == 0
    assert status.reason == "fixed-wrapper-completion-v1"
    submission = json.loads(
        (Path(handle.artifact_scope) / "submission-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert submission["terminal_evidence_policy"] == "fixed-wrapper-marker"
    assert submission["completion_nonce_sha256"] == hashlib.sha256(
        nonce.encode("ascii")
    ).hexdigest()
    assert nonce not in json.dumps(submission)


@pytest.mark.asyncio
async def test_fixed_wrapper_marker_with_wrong_nonce_remains_unknown(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(
        CommandResult("7302", "", 0),
        CommandResult("", "accounting storage is disabled", 1),
        CommandResult("", "", 0),
    )
    scheduler = SlurmScheduler(
        runner=runner,
        ledger=SubmissionLedger(tmp_path / "state/jobs.json"),
        terminal_evidence_policy="fixed-wrapper-marker",
    )
    handle = await scheduler.submit(_request(tmp_path))
    raw_script = runner.calls[0][1]
    assert raw_script is not None
    _write_wrapper_completion(handle, raw_script, nonce="0" * 64)

    status = await scheduler.status(handle.handle_id)

    assert status.state == "unknown"
    assert status.scheduler_state == "UNKNOWN"


def test_fixed_wrapper_marker_requires_shared_filesystem(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires a shared filesystem"):
        SlurmScheduler(
            runner=FakeRunner(),
            ledger=SubmissionLedger(tmp_path / "state/jobs.json"),
            shared_filesystem=False,
            terminal_evidence_policy="fixed-wrapper-marker",
        )


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


@pytest.mark.asyncio
async def test_module_init_is_sourced_on_the_node(tmp_path: Path) -> None:
    """A module request must not fall straight through to exit 86.

    `module` is a SHELL FUNCTION from the module system's profile script. The
    job runs under --export=NIL with a non-login `#!/bin/bash`, so nothing is
    inherited from the submitting shell and no profile is read — the function
    was always undefined and every module request failed, on a cluster where
    the toolchain is reachable only through modules.

    The init is sourced ON THE NODE, so --export=NIL keeps its meaning: the
    login node's state still cannot leak into a measurement.
    """
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    request = _request(tmp_path, modules=("gcc/13.2",))

    await scheduler.submit(request)
    script = runner.calls[0][1].decode()

    # Nothing is inherited: the isolation the fix must not weaken.
    assert "--export=NIL" in script
    # The init attempt precedes the availability check, or the check can only
    # ever fail.
    init_at = script.index("_ari_module_init")
    assert init_at < script.index("exit 86")
    # Standard install paths of the module SOFTWARE, not any one site's.
    assert "/etc/profile.d/modules.sh" in script
    assert "/etc/profile.d/lmod.sh" in script
    # A profile script is not written for `set -euo pipefail`; sourcing it
    # under -u would abort an otherwise valid job.
    assert "set +eu +o pipefail" in script
    assert "set -eu -o pipefail" in script
    # The honest failure survives for a node with no module system at all.
    assert "exit 86" in script
    assert "module load gcc/13.2" in script


@pytest.mark.asyncio
async def test_no_module_request_leaves_the_script_untouched(tmp_path: Path) -> None:
    # A job that never asked for modules must not gain a module preamble.
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit(_request(tmp_path))
    script = runner.calls[0][1].decode()

    assert "_ari_module_init" not in script
    assert "exit 86" not in script


@pytest.mark.asyncio
async def test_script_bridge_can_use_module(tmp_path: Path) -> None:
    """A raw bridge script must be able to `module load`.

    The bridge hands the agent a script and nothing else, so on a cluster
    whose toolchain is reachable only through modules the first line it writes
    is `module load`. Under --export=NIL with a non-login shell that died with
    a bare "module: command not found" (exit 127) and no explanation — correct
    HPC code failing for a reason the agent could neither see nor fix. Unlike
    the declared-modules path there is not even an exit-86 diagnostic here.
    """
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit_script_bridge(
        script="module load compiler/1.0\nmake bench",
        job_name="bridge", partition="compute-a64fx", nodes=1,
        walltime="00:10:00", work_dir=str(tmp_path),
    )
    script = runner.calls[0][1].decode()

    assert "--export=NIL" in script          # isolation is not weakened
    # The init must precede the agent's body, or its `module load` still dies.
    assert script.index("_ari_module_init") < script.index("module load compiler/1.0")
    assert "/etc/profile.d/modules.sh" in script


@pytest.mark.asyncio
async def test_both_submit_paths_share_one_module_init(tmp_path: Path) -> None:
    # The two paths reached the same defect independently; they must not drift
    # apart while being fixed.
    runner_a = FakeRunner(CommandResult("1;c\n", "", 0))
    await _scheduler(tmp_path / "a", runner_a).submit(
        _request(_mk(tmp_path / "a"), modules=("gcc/13.2",)))
    runner_b = FakeRunner(CommandResult("2;c\n", "", 0))
    await _scheduler(tmp_path / "b", runner_b).submit_script_bridge(
        script="module load gcc/13.2", job_name="b", partition="p",
        nodes=1, walltime="00:05:00", work_dir=str(_mk(tmp_path / "b")))

    # Compare against the helper's own output rather than a hand-counted
    # window, so the test cannot drift as the block grows or shrinks.
    from ari_skill_hpc.scheduler import SlurmScheduler

    block = "\n".join(SlurmScheduler._module_init_lines())
    assert block in runner_a.calls[0][1].decode()
    assert block in runner_b.calls[0][1].decode()


def _mk(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.asyncio
async def test_bridge_records_what_it_actually_ran_under(tmp_path: Path) -> None:
    """The bridge was the one execution path recording nothing.

    The declared-modules path snapshots `module -t list` right after its own
    loads, so it captures what the SCHEDULER asked for. The bridge has no
    declaration: the agent loads whatever it likes inside its own script, so
    the only truthful record is the state left when that script ends — which
    is why this is a trap and not a line appended after the body.
    """
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit_script_bridge(
        script="module load compiler/1.0\nmake bench",
        job_name="bridge", partition="compute-a64fx", nodes=1,
        walltime="00:10:00", work_dir=str(tmp_path),
    )
    script = runner.calls[0][1].decode()

    # Both files the artifact collector already looks for.
    assert "execution-environment.txt" in script
    assert "module-list.txt" in script
    # Armed before the body, so it fires however that body ends and observes
    # the state the body leaves behind.
    assert script.index("trap __ari_bridge_provenance EXIT") < script.index("make bench")
    # A recording gap must not become a job failure.
    assert "set +eu +o pipefail" in script
    # `module -t list` is meaningless without a module system.
    assert "command -v module >/dev/null 2>&1 && module -t list" in script


def test_snapshot_without_a_command_omits_command_path(tmp_path: Path) -> None:
    # The bridge has no single argv to resolve; the shared snapshot helper must
    # not emit an empty command_path for it.
    from ari_skill_hpc.scheduler import SlurmScheduler

    with_cmd = "\n".join(SlurmScheduler._environment_snapshot_lines(tmp_path, "python3"))
    without = "\n".join(SlurmScheduler._environment_snapshot_lines(tmp_path))
    assert "command_path=" in with_cmd
    assert "command_path=" not in without
    # Both record the resolution order a module load produced.
    for text in (with_cmd, without):
        assert "loaded_modules=" in text
        assert "path=" in text


@pytest.mark.asyncio
async def test_bridge_accepts_declared_modules(tmp_path: Path) -> None:
    """`slurm_submit` can declare modules, not only load them by hand.

    Writing `module load` inside the script works, but gets neither the purge
    (so the toolchain is the one asked for rather than whatever the node
    defaulted to) nor the availability check (so a node that cannot provide it
    builds with something else instead of failing).
    """
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit_script_bridge(
        script="make bench", job_name="b", partition="p", nodes=1,
        walltime="00:10:00", work_dir=str(tmp_path),
        modules=("compiler/1.0", "mpi/2.0"),
    )
    script = runner.calls[0][1].decode()

    assert "module --force purge" in script
    assert "module load compiler/1.0" in script
    assert "module load mpi/2.0" in script
    assert "exit 86" in script
    # Loaded before the body, or the body cannot use them.
    assert script.index("module load mpi/2.0") < script.index("make bench")


@pytest.mark.asyncio
async def test_bridge_without_modules_gains_no_module_block(tmp_path: Path) -> None:
    runner = FakeRunner(CommandResult("12345;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    await scheduler.submit_script_bridge(
        script="make bench", job_name="b", partition="p", nodes=1,
        walltime="00:10:00", work_dir=str(tmp_path),
    )
    script = runner.calls[0][1].decode()

    assert "module --force purge" not in script
    assert "exit 86" not in script


@pytest.mark.asyncio
async def test_modules_are_part_of_the_claim_identity(tmp_path: Path) -> None:
    # The same script built against a different toolchain is a DIFFERENT job.
    # If modules were outside the claim digest the second submission would be
    # deduplicated onto the first and return a result measured elsewhere.
    runner = FakeRunner(
        CommandResult("111;cluster\n", "", 0), CommandResult("222;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    common = dict(script="make bench", job_name="b", partition="p", nodes=1,
                  walltime="00:10:00", work_dir=str(tmp_path))

    first = await scheduler.submit_script_bridge(**common, modules=("compiler/1.0",))
    second = await scheduler.submit_script_bridge(**common, modules=("compiler/2.0",))

    assert first.request_digest != second.request_digest
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_identical_modules_still_deduplicate(tmp_path: Path) -> None:
    runner = FakeRunner(CommandResult("111;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)
    common = dict(script="make bench", job_name="b", partition="p", nodes=1,
                  walltime="00:10:00", work_dir=str(tmp_path),
                  modules=("compiler/1.0",))

    first = await scheduler.submit_script_bridge(**common)
    second = await scheduler.submit_script_bridge(**common)

    assert first == second
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_bridge_modules_go_through_the_typed_policy(tmp_path: Path) -> None:
    # The bridge must not be a way around the validation the typed path gets.
    runner = FakeRunner(CommandResult("111;cluster\n", "", 0))
    scheduler = _scheduler(tmp_path, runner)

    with pytest.raises(Exception):
        await scheduler.submit_script_bridge(
            script="make bench", job_name="b", partition="p", nodes=1,
            walltime="00:10:00", work_dir=str(tmp_path),
            modules=("bad name; rm -rf /",),
        )


def test_exclusive_allocation_witness_compares_the_job_not_the_step(
    tmp_path: Path,
) -> None:
    """SLURM_CPUS_ON_NODE is the step's cpus, not the job's.

    Measured on a real exclusive allocation: the step reported 4 while the job
    held 20. A witness built on it reports a false negative on exactly the
    allocation it exists to confirm, so the comparison must be
    SLURM_JOB_CPUS_PER_NODE against the node's CPUTot.
    """

    lines = SlurmScheduler._exclusive_allocation_check(None, tmp_path)
    script = "\n".join(lines)
    assert "SLURM_JOB_CPUS_PER_NODE" in script
    assert "SLURM_CPUS_ON_NODE" not in script
    assert "CPUTot" in script and "CPUAlloc" in script


def test_exclusive_allocation_witness_records_oversubscribe_without_trusting_it(
    tmp_path: Path,
) -> None:
    """Measured on one sharing partition: an --exclusive job and a shared job
    both report OverSubscribe=YES, so the field discriminates nothing. It is
    recorded as evidence and no branch reads it."""

    lines = SlurmScheduler._exclusive_allocation_check(None, tmp_path)
    script = "\n".join(lines)
    assert "job_oversubscribe=" in script
    branches = [
        line
        for line in lines
        if line.lstrip().startswith(("if ", "  if ", "elif "))
        and "oversubscribe" in line.lower()
    ]
    assert branches == []


def test_exclusive_allocation_witness_refuses_rather_than_guesses(
    tmp_path: Path,
) -> None:
    lines = SlurmScheduler._exclusive_allocation_check(None, tmp_path)
    script = "\n".join(lines)
    # Unparseable fields, a missing scontrol, and the multi-node range form of
    # SLURM_JOB_CPUS_PER_NODE all end in refusal, never in an assumption.
    assert "ari_verdict=refused" in script
    assert "unparsed-allocation-fields" in script
    assert "exit 88" in script
    assert 'case "$ari_job_cpus" in ""|*[!0-9]*)' in script
    # The witness is written before the refusal: a denied job still yields it.
    assert script.index("exclusive-allocation-witness.txt") < script.rindex("exit 88")


def test_exclusive_allocation_witness_runs_before_the_device_probe(
    tmp_path: Path,
) -> None:
    """Cheapest guard first: a shared grant is refused before nvidia-smi runs.

    Asserted on the generators directly. An earlier version of this test joined
    _render_script's return value, which is a str, so the join interleaved a
    newline between every character and no multi-character substring could ever
    match -- it passed for every possible implementation, including one that
    emitted the checks in the wrong order or not at all.
    """

    scheduler = _scheduler(tmp_path, FakeRunner())
    rendered = scheduler._render_script(_request(tmp_path), tmp_path)
    assert isinstance(rendered, str)
    # Without an accelerator allocation neither check is emitted at all.
    assert "exclusive-allocation-witness" not in rendered

    witness = "\n".join(SlurmScheduler._exclusive_allocation_check(None, tmp_path))
    inventory_marker = "accelerator-inventory.observed.csv"
    assert inventory_marker not in witness
    # _render_script emits the witness first, then the device probe; the order
    # is asserted on the source of the branch that emits them.
    import inspect

    source = inspect.getsource(SlurmScheduler._render_script)
    assert source.index("_exclusive_allocation_check") < source.index(
        "_accelerator_inventory_check"
    )


def test_witness_is_retained_as_job_provenance() -> None:
    import inspect

    source = inspect.getsource(SlurmScheduler._collect_provenance)
    assert "exclusive-allocation-witness" in source
    assert source.index("exclusive-allocation-witness") < source.index(
        "expected-accelerator-inventory"
    )
