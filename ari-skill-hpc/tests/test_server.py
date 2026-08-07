"""MCP surface conformance for canonical HPC tools."""

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
    assert "slurm_submit" in names
    assert "run_bash" not in names
    assert not names & {
        "singularity_build",
        "singularity_build_fakeroot",
        "singularity_pull",
        "singularity_run",
        "singularity_run_gpu",
    }
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
        content, structured = await call_tool(
            "job_submit", {"request": request.model_dump(mode="json")}
        )
    payload = json.loads(content[0].text)
    # Both halves must agree: the text is what ARI digests, the structured copy
    # is what a declared outputSchema is validated against.
    assert structured == payload
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


@pytest.mark.asyncio
async def test_every_declared_output_schema_admits_the_error_envelope() -> None:
    """Declaring an outputSchema obliges the handler to return structured
    content, and the library refuses the call if it does not conform.

    Every handler here funnels failures into ``{"error": {...}}``. A schema that
    described only success would turn a scheduler failure into an output
    validation error and throw away the message saying what went wrong -- the
    failure would be reported as a schema problem. This is asserted rather than
    reproduced because provoking each tool's own failure at runtime is
    unreliable, and a schema that admits it is what actually matters.
    """

    import jsonschema

    from ari_skill_hpc.server import list_tools

    envelope = {
        "error": {
            "kind": "scheduler",
            "message": "sbatch refused the submission",
            "retryable": False,
        }
    }
    declared = [t for t in await list_tools() if t.outputSchema]
    assert {t.name for t in declared} == {
        "container_submit",
        "counter_support",
        "job_submit",
        "measure_counters",
        "slurm_submit",
    }
    for tool in declared:
        jsonschema.validate(instance=envelope, schema=tool.outputSchema)


@pytest.mark.asyncio
async def test_a_declared_schema_accepts_its_own_tool_result() -> None:
    """The other half: the success shape must validate too, or the tool is
    unusable the moment it works."""

    import jsonschema

    from ari_skill_hpc import counters
    from ari_skill_hpc.server import list_tools

    schemas = {t.name: t.outputSchema for t in await list_tools() if t.outputSchema}
    jsonschema.validate(
        instance=counters.counter_support(), schema=schemas["counter_support"]
    )
