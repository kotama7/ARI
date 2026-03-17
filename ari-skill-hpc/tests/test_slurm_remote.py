"""Tests for SlurmClient in remote (SSH/paramiko) mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.slurm import SlurmClient, RemoteConfig


@pytest.fixture
def remote_config() -> RemoteConfig:
    return RemoteConfig(
        hostname="hpc.example.com",
        username="testuser",
        port=22,
        key_filename="/home/testuser/.ssh/id_rsa",
    )


@pytest.fixture
def client(remote_config: RemoteConfig) -> SlurmClient:
    return SlurmClient(mode="remote", remote_config=remote_config)


def _make_ssh_mock(stdout_text: str, stderr_text: str, exit_status: int) -> MagicMock:
    """Create a mock paramiko SSHClient with exec_command returning expected values."""
    mock_client = MagicMock()

    mock_stdout = MagicMock()
    mock_stdout.read.return_value = stdout_text.encode()
    mock_stdout.channel.recv_exit_status.return_value = exit_status

    mock_stderr = MagicMock()
    mock_stderr.read.return_value = stderr_text.encode()

    mock_stdin = MagicMock()

    mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)
    return mock_client


class TestRemoteInit:
    def test_remote_requires_config(self) -> None:
        with pytest.raises(ValueError, match="remote_config is required"):
            SlurmClient(mode="remote")

    def test_remote_with_config(self, remote_config: RemoteConfig) -> None:
        client = SlurmClient(mode="remote", remote_config=remote_config)
        assert client.mode == "remote"
        assert client.remote_config.hostname == "hpc.example.com"


class TestSubmitRemote:
    @pytest.mark.asyncio
    async def test_submit_success(self, client: SlurmClient) -> None:
        mock_ssh = _make_ssh_mock("Submitted batch job 67890", "", 0)

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.submit(
                script="echo hello",
                job_name="remote_test",
                partition="gpu",
            )

        assert result["job_id"] == "67890"
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_failure(self, client: SlurmClient) -> None:
        mock_ssh = _make_ssh_mock("", "sbatch: error: invalid partition", 1)

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.submit(
                script="echo hello",
                job_name="remote_test",
                partition="nonexistent",
            )

        assert result["status"] == "error"
        assert "sbatch failed" in result["message"]


class TestStatusRemote:
    @pytest.mark.asyncio
    async def test_status_running(self, client: SlurmClient) -> None:
        mock_ssh = _make_ssh_mock(
            "67890|RUNNING|0:0|2024-01-01T00:00:00|Unknown", "", 0
        )

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.status("67890")

        assert result["job_id"] == "67890"
        assert result["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_status_fallback_to_squeue(self, client: SlurmClient) -> None:
        call_count = 0

        def mock_exec(cmd):
            nonlocal call_count
            call_count += 1
            mock_stdin = MagicMock()
            mock_stdout = MagicMock()
            mock_stderr = MagicMock()

            if "sacct" in cmd:
                mock_stdout.read.return_value = b""
                mock_stdout.channel.recv_exit_status.return_value = 1
                mock_stderr.read.return_value = b""
            elif "squeue" in cmd:
                mock_stdout.read.return_value = b"PENDING\n"
                mock_stdout.channel.recv_exit_status.return_value = 0
                mock_stderr.read.return_value = b""
            else:
                mock_stdout.read.return_value = b""
                mock_stdout.channel.recv_exit_status.return_value = 0
                mock_stderr.read.return_value = b""

            return mock_stdin, mock_stdout, mock_stderr

        mock_ssh = MagicMock()
        mock_ssh.exec_command.side_effect = mock_exec

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.status("67890")

        assert result["status"] == "PENDING"


class TestCancelRemote:
    @pytest.mark.asyncio
    async def test_cancel_success(self, client: SlurmClient) -> None:
        mock_ssh = _make_ssh_mock("", "", 0)

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.cancel("67890")

        assert result["success"] is True
        assert "67890" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_failure(self, client: SlurmClient) -> None:
        mock_ssh = _make_ssh_mock("", "scancel: error: Invalid job id", 1)

        with patch("paramiko.SSHClient", return_value=mock_ssh):
            result = await client.cancel("99999")

        assert result["success"] is False


class TestClose:
    def test_close_with_connection(self, client: SlurmClient) -> None:
        mock_ssh = MagicMock()
        client._ssh_client = mock_ssh
        client.close()
        mock_ssh.close.assert_called_once()
        assert client._ssh_client is None

    def test_close_without_connection(self, client: SlurmClient) -> None:
        client.close()  # should not raise
        assert client._ssh_client is None
