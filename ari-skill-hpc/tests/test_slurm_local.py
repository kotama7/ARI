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

    @pytest.mark.asyncio
    async def test_submit_failure_includes_partition_and_exit_code(self, client: SlurmClient) -> None:
        """Error response must include partition name and exit code for diagnosis."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"sbatch: error: invalid partition specified: (null)")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
            result = await client.submit(
                script="echo hello",
                job_name="test_job",
                partition="fx700",
            )

        assert result["status"] == "error"
        assert "exit=1" in result["message"]
        assert "partition" in result  # partition key present for diagnosis

    @pytest.mark.asyncio
    async def test_submit_strips_partition_from_script_body(self, client: SlurmClient) -> None:
        """LLM-generated #SBATCH --partition= in script body must be stripped.

        The correct partition is set only via header_lines to avoid the bug
        where _fix_partition wrote an empty partition when env vars were unset.
        """
        captured_script = None

        async def mock_shell(cmd, **kwargs):
            nonlocal captured_script
            # cmd is "sbatch /tmp/xxx.sh" — read the temp file
            import re
            m = re.search(r"sbatch\s+(\S+)", cmd)
            if m:
                try:
                    captured_script = open(m.group(1)).read()
                except Exception:
                    pass
            mock = AsyncMock()
            mock.communicate.return_value = (b"Submitted batch job 77777\n", b"")
            mock.returncode = 0
            return mock

        script_with_partition = (
            "#!/bin/bash\n"
            "#SBATCH --partition=wrong_partition\n"
            "#SBATCH --cpus-per-task=32\n"
            "echo hello\n"
        )

        with patch("asyncio.create_subprocess_shell", side_effect=mock_shell), \
             patch.dict("os.environ", {"SLURM_VALID_PARTITIONS": "", "SLURM_DEFAULT_PARTITION": ""}, clear=False):
            result = await client.submit(
                script=script_with_partition,
                job_name="test_job",
                partition="fx700",
            )

        assert result["job_id"] == "77777"
        # The final script must have exactly ONE --partition line, and it must be fx700
        if captured_script:
            import re
            partitions = re.findall(r"#SBATCH\s+--partition=(\S+)", captured_script)
            assert len(partitions) == 1, f"Expected 1 partition directive, got {len(partitions)}: {partitions}"
            assert partitions[0] == "fx700", f"Expected fx700, got {partitions[0]}"

    @pytest.mark.asyncio
    async def test_submit_no_empty_partition_when_env_unset(self, client: SlurmClient) -> None:
        """Without SLURM_VALID_PARTITIONS / SLURM_DEFAULT_PARTITION, the kwarg
        partition must be used as-is — never replaced with an empty string."""
        captured_script = None

        async def mock_shell(cmd, **kwargs):
            nonlocal captured_script
            import re
            m = re.search(r"sbatch\s+(\S+)", cmd)
            if m:
                try:
                    captured_script = open(m.group(1)).read()
                except Exception:
                    pass
            mock = AsyncMock()
            mock.communicate.return_value = (b"Submitted batch job 88888\n", b"")
            mock.returncode = 0
            return mock

        with patch("asyncio.create_subprocess_shell", side_effect=mock_shell), \
             patch.dict("os.environ", {"SLURM_VALID_PARTITIONS": "", "SLURM_DEFAULT_PARTITION": ""}, clear=False):
            result = await client.submit(
                script="#!/bin/bash\n#SBATCH --partition=fx700\necho hi",
                job_name="test",
                partition="fx700",
            )

        assert result["status"] == "submitted"
        if captured_script:
            assert "#SBATCH --partition=\n" not in captured_script, \
                "Script must NOT contain empty --partition= directive"
            assert "#SBATCH --partition=fx700" in captured_script


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
