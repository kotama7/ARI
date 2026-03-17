"""Tests for SlurmClient in local (subprocess) mode."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.slurm import SlurmClient


@pytest.fixture
def client() -> SlurmClient:
    return SlurmClient(mode="local")


class TestSubmitLocal:
    @pytest.mark.asyncio
    async def test_submit_success(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 12345\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.submit(
                script="echo hello",
                job_name="test_job",
                partition="gpu",
                nodes=2,
                walltime="02:00:00",
            )

        assert result["job_id"] == "12345"
        assert result["status"] == "submitted"
        assert "12345" in result["message"]

    @pytest.mark.asyncio
    async def test_submit_with_account(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Submitted batch job 99999\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc) as mock_shell:
            result = await client.submit(
                script="echo hello",
                job_name="test_job",
                partition="gpu",
                account="myaccount",
            )

        assert result["job_id"] == "99999"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_failure(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"sbatch: error: invalid partition")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.submit(
                script="echo hello",
                job_name="test_job",
                partition="nonexistent",
            )

        assert result["status"] == "error"
        assert "sbatch failed" in result["message"]


class TestStatusLocal:
    @pytest.mark.asyncio
    async def test_status_running(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"12345|RUNNING|0:0|2024-01-01T00:00:00|Unknown\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.status("12345")

        assert result["job_id"] == "12345"
        assert result["status"] == "RUNNING"
        assert result["exit_code"] == 0
        assert result["start_time"] == "2024-01-01T00:00:00"
        assert result["end_time"] is None

    @pytest.mark.asyncio
    async def test_status_completed_with_output(self, client: SlurmClient) -> None:
        call_count = 0

        async def mock_shell(cmd, **kwargs):
            nonlocal call_count
            mock = AsyncMock()
            if "sacct" in cmd:
                mock.communicate.return_value = (
                    b"12345|COMPLETED|0:0|2024-01-01T00:00:00|2024-01-01T01:00:00\n",
                    b"",
                )
                mock.returncode = 0
            elif "slurm-12345.out" in cmd:
                mock.communicate.return_value = (b"job output here", b"")
                mock.returncode = 0
            elif "slurm-12345.err" in cmd:
                mock.communicate.return_value = (b"", b"")
                mock.returncode = 1  # no stderr file
            else:
                mock.communicate.return_value = (b"", b"")
                mock.returncode = 0
            return mock

        with patch("asyncio.create_subprocess_shell", side_effect=mock_shell):
            result = await client.status("12345")

        assert result["status"] == "COMPLETED"
        assert result["exit_code"] == 0
        assert result["stdout"] == "job output here"

    @pytest.mark.asyncio
    async def test_status_fallback_to_squeue(self, client: SlurmClient) -> None:
        call_count = 0

        async def mock_shell(cmd, **kwargs):
            nonlocal call_count
            mock = AsyncMock()
            if "sacct" in cmd:
                mock.communicate.return_value = (b"", b"")
                mock.returncode = 1
            elif "squeue" in cmd:
                mock.communicate.return_value = (b"PENDING\n", b"")
                mock.returncode = 0
            else:
                mock.communicate.return_value = (b"", b"")
                mock.returncode = 0
            return mock

        with patch("asyncio.create_subprocess_shell", side_effect=mock_shell):
            result = await client.status("12345")

        assert result["status"] == "PENDING"


class TestCancelLocal:
    @pytest.mark.asyncio
    async def test_cancel_success(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.cancel("12345")

        assert result["success"] is True
        assert "12345" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_failure(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"",
            b"scancel: error: Invalid job id 99999",
        )
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.cancel("99999")

        assert result["success"] is False
        assert "scancel failed" in result["message"]


class TestGetOutputLocal:
    @pytest.mark.asyncio
    async def test_get_stdout(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello world\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.get_stdout("12345")

        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_get_stdout_no_file(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"cat: no such file")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.get_stdout("12345")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_stderr(self, client: SlurmClient) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"error output", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.get_stderr("12345")

        assert result == "error output"
