"""Contract tests for paper-re's canonical SLURM consumer."""

from __future__ import annotations

import importlib.util
import hashlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from rubric_contract import bind_rubric_digest  # noqa: E402
from ari.public.execution import ExecutionRequestV1, WorkspaceRefV1  # noqa: E402

_spec = importlib.util.spec_from_file_location("paper_re_server_slurm", SRC / "server.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_server_slurm"] = S
_spec.loader.exec_module(S)


class FakeScheduler:
    def __init__(self, *, state: str = "succeeded", exit_code: int | None = 0):
        self.state = state
        self.exit_code = exit_code
        self.request = None
        self.cancelled = False

    async def submit(self, request):
        self.request = request
        return SimpleNamespace(
            handle_id="slurm-test-handle",
            job_id="1234",
            request_digest=request.request_digest,
        )

    async def status(self, handle_id):
        assert handle_id == "slurm-test-handle"
        scheduler_state = {
            "succeeded": "COMPLETED",
            "failed": "FAILED",
            "cancelled": "CANCELLED",
        }.get(self.state, "RUNNING")
        return SimpleNamespace(
            state=self.state,
            scheduler_state=scheduler_state,
            exit_code=self.exit_code,
        )

    async def logs(self, handle_id):
        assert handle_id == "slurm-test-handle"
        return (
            SimpleNamespace(stream="stdout", text="metric=0.42\n"),
            SimpleNamespace(stream="stderr", text=""),
        )

    async def cancel(self, handle_id):
        assert handle_id == "slurm-test-handle"
        self.cancelled = True

    async def result(self, handle_id):
        assert handle_id == "slurm-test-handle"
        return SimpleNamespace(
            result_digest="sha256:" + "d" * 64,
            environment_digest="sha256:" + "e" * 64,
            module_snapshot_digest="sha256:" + "f" * 64,
            provenance=(),
        )


def _setup_slurm(tmp_path: Path, *, with_partition: bool = True) -> Path:
    repo = tmp_path / "repro_sandbox"
    repo.mkdir(parents=True)
    (repo / "reproduce.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\necho metric=0.42\n",
        encoding="utf-8",
    )
    if with_partition:
        (tmp_path / "launch_config.json").write_text(
            json.dumps({"partition": "sx40"}), encoding="utf-8"
        )
    return repo


def _execution(repo: Path, timeout: int = 60) -> ExecutionRequestV1:
    script = (repo / "reproduce.sh").read_bytes()
    return ExecutionRequestV1(
        workspace=WorkspaceRefV1(root=str(repo)),
        argv=["/bin/bash", "reproduce.sh"],
        timeout_seconds=timeout,
        network="inherit",
        input_digests={
            "reproduce.sh": "sha256:" + hashlib.sha256(script).hexdigest()
        },
    )


def test_auto_picks_slurm_only_with_binary_and_partition(monkeypatch):
    monkeypatch.setenv("ARI_SLURM_PARTITION", "sx40")
    monkeypatch.delenv("ARI_PHASE1_SANDBOX", raising=False)
    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        assert S._phase1_sandbox_kind() == "slurm"

    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    with patch.object(S, "_has_bin", lambda name: False):
        with patch.object(S, "_docker_works", lambda: False):
            assert S._phase1_sandbox_kind() == "local"


def test_partition_resolution_precedence(monkeypatch, tmp_path):
    repo = _setup_slurm(tmp_path)
    monkeypatch.setenv("ARI_SLURM_PARTITION", "from-env")
    assert S._resolve_partition_for_repo(repo, "from-arg") == "from-arg"
    assert S._resolve_partition_for_repo(repo) == "from-env"
    monkeypatch.delenv("ARI_SLURM_PARTITION")
    monkeypatch.delenv("SLURM_PARTITION", raising=False)
    assert S._resolve_partition_for_repo(repo) == "sx40"


def test_walltime_is_bounded_to_at_least_one_minute():
    assert S._walltime_str(0) == "00:01:00"
    assert S._walltime_str(90) == "00:01:30"
    assert S._walltime_str(3600) == "01:00:00"


@pytest.mark.asyncio
async def test_slurm_consumer_builds_typed_request_and_materializes_log(
    tmp_path, monkeypatch
):
    repo = _setup_slurm(tmp_path)
    scheduler = FakeScheduler()
    monkeypatch.setenv("ARI_SLURM_CPUS", "16")
    monkeypatch.setattr(S, "_paper_re_scheduler", lambda _repo: scheduler)

    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        result = await S._execute_reproduction_slurm(
            _execution(repo, 600),
            repo / "reproduce.log",
            nodes=4,
            ntasks=32,
            ntasks_per_node=8,
            nodelist="node[01-04]",
            exclude_nodes="node03",
            exclusive=True,
            gpus_per_task=1,
            gpu_type="v100",
            memory_gb_per_node=256,
            constraint="skylake|haswell",
            hint="nomultithread",
            account="projX",
            qos="normal",
            reservation="paperbench",
            module_loads=("cuda/12.4", "openmpi/4.1"),
        )

    assert result["executed"] is True
    assert result["exit_code"] == 0
    assert result["handle_id"] == "slurm-test-handle"
    assert result["job_id"] == "1234"
    assert (repo / "reproduce.log").read_text(encoding="utf-8") == "metric=0.42\n"

    request = scheduler.request
    assert request.schema_version == "ari.hpc.job-request/v1"
    assert request.argv[0] == "/bin/bash"
    assert request.argv[1] != str((repo / "reproduce.sh").resolve())
    assert Path(request.argv[1]).is_file()
    assert request.environment.export_mode == "NIL"
    assert request.environment.modules == ("cuda/12.4", "openmpi/4.1")
    assert request.inputs[0].digest.startswith("sha256:")
    assert result["execution_identity"] == _execution(repo, 600).execution_identity
    assert result["handoff_digest"].startswith("sha256:")
    resources = request.resources
    assert resources.nodes == 4
    assert resources.tasks == 32
    assert resources.tasks_per_node == 8
    assert resources.cpus_per_task == 16
    assert resources.gpus_per_task == 1
    assert resources.gpu_type == "v100"
    assert resources.memory_mb_per_node == 256 * 1024
    assert resources.account == "projX"
    assert resources.reservation == "paperbench"


@pytest.mark.asyncio
async def test_run_reproduce_resolves_execution_profile_into_typed_request(
    tmp_path, monkeypatch
):
    repo = _setup_slurm(tmp_path)
    scheduler = FakeScheduler()
    monkeypatch.setattr(S, "_paper_re_scheduler", lambda _repo: scheduler)
    rubric = tmp_path / "rubric.json"
    document = {
        "version": "3",
        "paper_sha256": "a" * 64,
        "generator": {"model": "legacy/fixture"},
        "reproduce_contract": {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 600,
            "execution_profile": {
                "requested_nodes": 2,
                "min_ranks": 8,
                "ntasks_per_node": 4,
                "requested_gpus_per_node": 2,
                "gpu_type": "a100",
                "memory_gb_per_node": 128,
                "module_loads": ["cuda/12.4"],
                "account": "science",
            },
        },
        "rubric": {
            "id": "fixture-root",
            "requirements": "Replicate the fixture benchmark results.",
            "weight": 1,
            "sub_tasks": [
                {
                    "id": "fixture-leaf",
                    "requirements": "Produce the fixture benchmark output.",
                    "weight": 1,
                    "sub_tasks": [],
                    "task_category": "Code Execution",
                }
            ],
        },
    }
    rubric.write_text(
        json.dumps(bind_rubric_digest(document, legacy=True)),
        encoding="utf-8",
    )

    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        result = await S.run_reproduce(
            rubric_path=str(rubric),
                repo_dir=str(repo),
                sandbox_kind="slurm",
                partition="sx40",
                network_policy="inherit",
            )

    assert result["executed"] is True
    assert result["sandbox_kind"] == "slurm"
    assert result["handle_id"] == "slurm-test-handle"
    assert ".ari-hpc" not in result["artifacts"]
    assert scheduler.request.resources.nodes == 2
    assert scheduler.request.resources.tasks == 8
    assert scheduler.request.resources.gpus_per_node == 2
    assert scheduler.request.environment.modules == ("cuda/12.4",)


@pytest.mark.asyncio
async def test_failed_scheduler_state_is_not_reported_as_success(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path)
    scheduler = FakeScheduler(state="failed", exit_code=7)
    monkeypatch.setattr(S, "_paper_re_scheduler", lambda _repo: scheduler)

    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        result = await S._execute_reproduction_slurm(
            _execution(repo), repo / "reproduce.log", partition="sx40"
        )

    assert result["executed"] is True
    assert result["exit_code"] == 7
    assert "FAILED" in result["error"]


@pytest.mark.asyncio
async def test_missing_sbatch_cannot_be_downgraded_to_local(
    tmp_path, monkeypatch
):
    repo = _setup_slurm(tmp_path)
    with patch.object(S, "_has_bin", lambda _name: False):
        with pytest.raises(RuntimeError, match="sbatch is not on PATH"):
            await S._execute_reproduction_slurm(
                _execution(repo, 10), repo / "reproduce.log", partition="sx40"
            )


@pytest.mark.asyncio
async def test_unresolved_partition_fails_loudly(tmp_path, monkeypatch):
    repo = _setup_slurm(tmp_path, with_partition=False)
    monkeypatch.delenv("ARI_SLURM_PARTITION", raising=False)
    monkeypatch.delenv("SLURM_PARTITION", raising=False)
    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        with pytest.raises(RuntimeError, match="no partition"):
            await S._execute_reproduction_slurm(
                _execution(repo, 10), repo / "reproduce.log"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"gpus_per_node": 1, "gpus_per_task": 1}, "mutually exclusive"),
        (
            {"memory_gb_per_node": 8, "memory_gb_per_cpu": 2},
            "mutually exclusive",
        ),
        ({"cpu_bind": "cores"}, "srun job-step"),
    ],
)
async def test_contradictory_or_nonportable_resources_fail_closed(
    tmp_path, monkeypatch, kwargs, message
):
    repo = _setup_slurm(tmp_path)
    scheduler = FakeScheduler()
    monkeypatch.setattr(S, "_paper_re_scheduler", lambda _repo: scheduler)
    with patch.object(S, "_has_bin", lambda name: name == "sbatch"):
        if "cpu_bind" in kwargs:
            with pytest.raises(ValueError, match=message):
                await S._execute_reproduction_slurm(
                    _execution(repo),
                    repo / "reproduce.log",
                    partition="sx40",
                    **kwargs,
                )
        else:
            result = await S._execute_reproduction_slurm(
                _execution(repo),
                repo / "reproduce.log",
                partition="sx40",
                **kwargs,
            )
            assert result["executed"] is False
            assert message in result["error"]
    assert scheduler.request is None


def test_deprecated_escape_hatch_is_typed_and_fail_closed():
    assert S._parse_deprecated_sbatch_args(
        ["--account=projX", "--reservation=res1", "--hint=nomultithread"]
    ) == {
        "account": "projX",
        "reservation": "res1",
        "hint": "nomultithread",
    }
    with pytest.raises(ValueError, match="unsupported"):
        S._parse_deprecated_sbatch_args(["--dependency=afterok:123"])
    with pytest.raises(ValueError, match="duplicate"):
        S._parse_deprecated_sbatch_args(["--qos=normal", "--qos=debug"])


def test_paper_re_contains_no_direct_sbatch_submission():
    source = inspect.getsource(S._execute_reproduction_slurm)
    assert "subprocess.run" not in source
    assert "--export" not in source
    assert "handoff_execution_to_slurm" in source
    assert "scheduler.submit" in source
