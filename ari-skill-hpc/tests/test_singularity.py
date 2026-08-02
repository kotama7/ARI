"""Container aliases must compile into the same digest-bound scheduler request."""

from __future__ import annotations

from pathlib import Path

import pytest

from ari_skill_hpc import singularity
from ari_skill_hpc.scheduler import CommandResult, SlurmScheduler, SubmissionLedger
from ari_skill_hpc.slurm import SlurmClient


class FakeRunner:
    def __init__(self, *responses: CommandResult):
        self.responses = list(responses)
        self.calls = []

    @property
    def identity(self):
        return {"transport": "fake", "cluster": "container-test"}

    async def run(self, argv, *, stdin=None, timeout=None):
        self.calls.append((list(argv), stdin))
        if not self.responses:
            raise AssertionError(f"unexpected call: {argv}")
        return self.responses.pop(0)

    def close(self):
        return None


def _client(tmp_path: Path, runner: FakeRunner) -> SlurmClient:
    client = SlurmClient(mode="local", ledger_path=tmp_path / "unused.json")
    client._scheduler = SlurmScheduler(
        runner=runner,
        ledger=SubmissionLedger(tmp_path / "state" / "jobs.json"),
    )
    return client


@pytest.mark.asyncio
async def test_build_materializes_definition_by_digest_without_heredoc(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(CommandResult("11111", "", 0))
    client = _client(tmp_path, runner)
    definition = (
        "Bootstrap: docker\nFrom: ubuntu:24.04\n%post\necho 'DEFEOF; touch /tmp/pwn'"
    )
    output = tmp_path / "image.sif"

    result = await singularity.build(
        client,
        {
            "definition_file": definition,
            "output_path": str(output),
            "partition": "build",
        },
    )

    assert result["job_id"] == "11111"
    script = runner.calls[0][1].decode()
    assert definition not in script
    assert "cat <<" not in script
    assert "singularity build" in script
    definitions = list((tmp_path / ".ari-hpc" / "definitions").glob("*.def"))
    assert len(definitions) == 1
    assert definitions[0].read_text() == definition
    assert oct(definitions[0].stat().st_mode & 0o777) == "0o600"


@pytest.mark.asyncio
async def test_container_run_pins_image_and_treats_shell_tokens_as_arguments(
    tmp_path: Path,
) -> None:
    image = tmp_path / "image.sif"
    image.write_bytes(b"SIF test image")
    runner = FakeRunner(CommandResult("33333", "", 0))
    client = _client(tmp_path, runner)

    result = await singularity.run(
        client,
        {
            "image_path": str(image),
            "command": "python train.py; touch /tmp/pwn",
            "work_dir": str(tmp_path),
            "partition": "gpu",
            "nodes": 2,
        },
    )

    assert result["job_id"] == "33333"
    script = runner.calls[0][1].decode()
    assert "singularity exec --containall --cleanenv" in script
    assert f"--bind {tmp_path}:{tmp_path}:rw" in script
    assert "'train.py;' touch /tmp/pwn" in script
    assert "train.py; touch" not in script
    assert "sha256sum" in script
    assert str(image) in script


@pytest.mark.asyncio
async def test_gpu_alias_declares_scheduler_and_container_gpu(
    tmp_path: Path,
) -> None:
    image = tmp_path / "gpu.sif"
    image.write_bytes(b"gpu image")
    runner = FakeRunner(CommandResult("44444", "", 0))
    client = _client(tmp_path, runner)

    result = await singularity.run_gpu(
        client,
        {
            "image_path": str(image),
            "command": "python train.py",
            "work_dir": str(tmp_path),
            "partition": "accelerator",
            "gres": "gpu:a100:2",
            "cpus_per_task": 16,
        },
    )

    assert result["status"] == "submitted"
    script = runner.calls[0][1].decode()
    assert "#SBATCH --gres=gpu:a100:2" in script
    assert "#SBATCH --cpus-per-task=16" in script
    assert "singularity exec --containall --cleanenv --nv" in script


@pytest.mark.asyncio
async def test_missing_or_symlink_image_fails_before_submission(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = _client(tmp_path, runner)
    missing = await singularity.run(
        client,
        {
            "image_path": str(tmp_path / "missing.sif"),
            "command": "true",
            "work_dir": str(tmp_path),
            "partition": "cpu",
        },
    )
    target = tmp_path / "real.sif"
    target.write_bytes(b"image")
    linked = tmp_path / "linked.sif"
    linked.symlink_to(target)
    symlink = await singularity.run(
        client,
        {
            "image_path": str(linked),
            "command": "true",
            "work_dir": str(tmp_path),
            "partition": "cpu",
        },
    )
    assert missing["status"] == "error"
    assert symlink["status"] == "error"
    assert runner.calls == []


@pytest.mark.asyncio
async def test_pull_source_is_validated_and_content_bound(tmp_path: Path) -> None:
    runner = FakeRunner(CommandResult("55555", "", 0))
    client = _client(tmp_path, runner)
    source = "docker://registry.example/ubuntu:24.04@sha256:abcdef"
    result = await singularity.pull(
        client,
        {
            "source": source,
            "output_path": str(tmp_path / "ubuntu.sif"),
            "partition": "build",
        },
    )
    assert result["job_id"] == "55555"
    script = runner.calls[0][1].decode()
    assert source in script

    rejected = await singularity.pull(
        client,
        {
            "source": "docker://ubuntu:24.04;touch-pwn",
            "output_path": str(tmp_path / "bad.sif"),
            "partition": "build",
        },
    )
    assert rejected["status"] == "error"
    assert len(runner.calls) == 1
