"""MCP surface conformance for canonical and deprecated HPC tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ari_skill_hpc.contracts import JobRequestV1, ResourceRequestV1
from ari_skill_hpc.scheduler import CommandResult, SlurmScheduler, SubmissionLedger
from ari_skill_hpc.server import (
    _get_slurm_client,
    _public_error_message,
    call_tool,
    list_tools,
)
from ari_skill_hpc.slurm import SlurmClient


class FakeRunner:
    def __init__(self):
        self.calls = []

    @property
    def identity(self):
        return {"transport": "fake", "cluster": "server-test"}

    async def run(self, argv, *, stdin=None, timeout=None):
        self.calls.append((list(argv), stdin))
        return CommandResult("1234", "", 0)

    def close(self):
        return None


@pytest.mark.asyncio
async def test_tool_surface_has_canonical_lifecycle_and_no_run_bash() -> None:
    tools = await list_tools()
    names = {tool.name for tool in tools}
    assert {"job_submit", "job_status", "job_result", "job_logs", "job_cancel"} <= names
    assert "container_submit" in names
    assert "run_bash" not in names
    submit = next(tool for tool in tools if tool.name == "job_submit")
    assert "$defs" in submit.inputSchema
    assert submit.inputSchema["properties"]["request"]["$ref"].startswith("#/$defs/")


@pytest.mark.asyncio
async def test_canonical_submit_round_trip(tmp_path: Path) -> None:
    request = JobRequestV1(
        request_id="server-request",
        job_name="server-job",
        work_dir=str(tmp_path),
        argv=("/usr/bin/true",),
        resources=ResourceRequestV1(partition="cpu"),
    )
    runner = FakeRunner()
    client = SlurmClient(mode="local", ledger_path=tmp_path / "unused.json")
    client._scheduler = SlurmScheduler(
        runner=runner,
        ledger=SubmissionLedger(tmp_path / "state" / "jobs.json"),
    )
    with patch("ari_skill_hpc.server._get_slurm_client", return_value=client):
        content = await call_tool(
            "job_submit", {"request": request.model_dump(mode="json")}
        )
    payload = json.loads(content[0].text)
    assert payload["schema_version"] == "ari.hpc.job-handle/v1"
    assert payload["job_id"] == "1234"
    assert runner.calls[0][0] == ["sbatch", "--parsable", "--export=NIL"]


def test_remote_mode_requires_strict_configuration(monkeypatch) -> None:
    monkeypatch.setenv("SLURM_MODE", "remote")
    monkeypatch.delenv("SLURM_SSH_KNOWN_HOSTS", raising=False)
    monkeypatch.delenv("SLURM_SSH_KEY", raising=False)
    monkeypatch.delenv("SLURM_SSH_PASSWORD", raising=False)
    with pytest.raises(ValueError):
        _get_slurm_client()


def test_public_error_message_redacts_credentials() -> None:
    message = _public_error_message(
        RuntimeError("TOKEN=abc123 password: hunter2 safe diagnostic")
    )
    assert "abc123" not in message
    assert "hunter2" not in message
    assert "safe diagnostic" in message
