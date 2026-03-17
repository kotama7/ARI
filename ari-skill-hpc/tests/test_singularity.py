"""Tests for Singularity operations (build and run via SLURM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.slurm import SlurmClient
from src import singularity


@pytest.fixture
def client() -> SlurmClient:
    return SlurmClient(mode="local")


class TestSingularityBuild:
    @pytest.mark.asyncio
    async def test_build_success(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 11111\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.build(
                client,
                {
                    "definition_file": "Bootstrap: docker\nFrom: ubuntu:22.04",
                    "output_path": "/scratch/myimage.sif",
                    "partition": "build",
                },
            )

        assert result["job_id"] == "11111"
        assert result["output_path"] == "/scratch/myimage.sif"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_build_failure(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"sbatch: error")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.build(
                client,
                {
                    "definition_file": "Bootstrap: docker\nFrom: ubuntu:22.04",
                    "output_path": "/scratch/myimage.sif",
                    "partition": "build",
                },
            )

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_build_default_partition(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 22222\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.build(
                client,
                {
                    "definition_file": "Bootstrap: docker\nFrom: centos:7",
                    "output_path": "/scratch/centos.sif",
                },
            )

        assert result["job_id"] == "22222"
        assert result["status"] == "submitted"


class TestSingularityRun:
    @pytest.mark.asyncio
    async def test_run_success(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 33333\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.run(
                client,
                {
                    "image_path": "/scratch/myimage.sif",
                    "command": "python train.py",
                    "work_dir": "/home/user/project",
                    "partition": "gpu",
                    "nodes": 4,
                    "walltime": "08:00:00",
                },
            )

        assert result["job_id"] == "33333"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_run_with_defaults(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 44444\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.run(
                client,
                {
                    "image_path": "/scratch/myimage.sif",
                    "command": "hostname",
                    "work_dir": "/tmp",
                    "partition": "default",
                },
            )

        assert result["job_id"] == "44444"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_run_failure(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"sbatch: error")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await singularity.run(
                client,
                {
                    "image_path": "/scratch/myimage.sif",
                    "command": "python train.py",
                    "work_dir": "/home/user/project",
                    "partition": "gpu",
                },
            )

        assert result["status"] == "error"
