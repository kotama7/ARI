"""Run-level immutable MCP Skill snapshot contract tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ari.config import SkillConfig
from ari.mcp.client import MCPClient
from ari.skill_lock import (
    SKILLS_LOCK_FILENAME,
    SkillLockCorruptError,
    SkillLockMismatchError,
    SkillLockMissingError,
    SkillProviderAdmissionError,
    build_skills_lock,
    load_skills_lock,
    verify_skills_lock_subset,
    write_or_verify_skills_lock,
)


def _skill(*, manifest_digest: str = "a" * 64) -> SkillConfig:
    return SkillConfig(
        name="fixture-skill",
        package="ari-skill-fixture",
        version="1.0.0",
        path="/fixture",
        phase=["bfts", "paper"],
        manifest_digest=manifest_digest,
        environment_policy="complete",
        required_env=["FIXTURE_TOKEN"],
        tool_refs={"inspect": "declared"},
        tool_capabilities={"inspect": "ari.fixture.inspect"},
        tool_policies={
            "inspect": {
                "phases": ["bfts"],
                "side_effects": "read-only",
                "determinism": "deterministic",
                "timeout_class": "bounded",
                "permissions": ["workspace-read"],
                "result_schema": "ari.result-envelope/v1",
            }
        },
    )


def _tool(
    skill: SkillConfig,
    *,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> dict:
    schema = input_schema or {"type": "object"}
    output = output_schema or {"type": "object"}
    # A fixture tool_ref must change along with either live schema, just as the
    # production registry's runtime_tool_ref does.
    from ari.mcp.dispatch_support import runtime_tool_ref

    raw = {
        "name": "inspect",
        "skill_name": skill.name,
        "inputSchema": schema,
        "outputSchema": output,
    }
    raw["tool_ref"] = runtime_tool_ref(skill, raw)
    raw["capability_ref"] = skill.tool_capabilities["inspect"]
    raw["policy"] = skill.tool_policies["inspect"]
    return raw


class _Connection:
    def __init__(self, skill: SkillConfig, input_schema: dict | None = None):
        self.skill = skill
        self.input_schema = input_schema or {"type": "object"}

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "inspect",
                "description": "fixture",
                "inputSchema": self.input_schema,
                "outputSchema": {"type": "object"},
                "skill_name": self.skill.name,
            }
        ]

    def close(self) -> None:
        pass


def test_lock_binds_provider_live_schemas_and_phase_active_set(tmp_path: Path):
    skill = _skill()
    lock = build_skills_lock(
        run_id="run-1",
        skills=[skill],
        tools=[_tool(skill)],
        disabled_tools=[],
    )

    assert lock.run_id == "run-1"
    assert lock.skills[0].manifest_digest == "a" * 64
    assert lock.skills[0].provider_digest
    assert lock.tools[0].input_schema_digest
    assert lock.phase_active_tools["bfts"] == [lock.tools[0].tool_ref]
    assert lock.phase_active_tools["paper"] == []

    path = tmp_path / SKILLS_LOCK_FILENAME
    assert write_or_verify_skills_lock(path, lock) == lock
    assert load_skills_lock(path) == lock


def test_atomic_concurrent_create_is_deterministic(tmp_path: Path):
    skill = _skill()
    lock = build_skills_lock(run_id="run-1", skills=[skill], tools=[_tool(skill)])
    path = tmp_path / SKILLS_LOCK_FILENAME

    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(
            pool.map(lambda _: write_or_verify_skills_lock(path, lock), range(8))
        )

    assert snapshots == [lock] * 8
    assert load_skills_lock(path) == lock


def test_existing_lock_rejects_manifest_or_schema_drift(tmp_path: Path):
    original_skill = _skill()
    original = build_skills_lock(
        run_id="run-1", skills=[original_skill], tools=[_tool(original_skill)]
    )
    path = tmp_path / SKILLS_LOCK_FILENAME
    write_or_verify_skills_lock(path, original)

    changed_skill = _skill(manifest_digest="b" * 64)
    changed = build_skills_lock(
        run_id="run-1",
        skills=[changed_skill],
        tools=[_tool(changed_skill, input_schema={"type": "string"})],
    )
    with pytest.raises(SkillLockMismatchError, match="does not match immutable"):
        write_or_verify_skills_lock(path, changed)


def test_subset_worker_verifies_provider_without_replacing_full_lock(tmp_path: Path):
    first = _skill()
    second = SkillConfig(
        name="other-skill",
        package="ari-skill-other",
        path="/other",
        phase="paper",
        manifest_digest="c" * 64,
        environment_policy="complete",
    )
    second_raw = {
        "name": "other",
        "skill_name": second.name,
        "inputSchema": {},
        "outputSchema": {},
    }
    from ari.mcp.dispatch_support import runtime_tool_ref

    second_raw["tool_ref"] = runtime_tool_ref(second, second_raw)
    full = build_skills_lock(
        run_id="run-1",
        skills=[first, second],
        tools=[_tool(first), second_raw],
    )
    path = tmp_path / SKILLS_LOCK_FILENAME
    write_or_verify_skills_lock(path, full)
    subset = build_skills_lock(
        run_id="run-1", skills=[first], tools=[_tool(first)]
    )

    assert verify_skills_lock_subset(path, subset) == full
    assert load_skills_lock(path) == full


def test_subset_worker_cannot_create_authoritative_lock(tmp_path: Path):
    skill = _skill()
    subset = build_skills_lock(run_id="run-1", skills=[skill], tools=[_tool(skill)])
    with pytest.raises(SkillLockMissingError, match="requires existing"):
        verify_skills_lock_subset(tmp_path / SKILLS_LOCK_FILENAME, subset)


def test_subset_worker_cannot_validate_an_empty_registry(tmp_path: Path):
    skill = _skill()
    full = build_skills_lock(run_id="run-1", skills=[skill], tools=[_tool(skill)])
    path = tmp_path / SKILLS_LOCK_FILENAME
    write_or_verify_skills_lock(path, full)
    empty = build_skills_lock(run_id="run-1", skills=[], tools=[])
    with pytest.raises(SkillLockMismatchError, match="no configured provider"):
        verify_skills_lock_subset(path, empty)


def test_lock_reader_refuses_symbolic_links(tmp_path: Path):
    skill = _skill()
    real = tmp_path / "real.lock"
    write_or_verify_skills_lock(
        real,
        build_skills_lock(run_id="run-1", skills=[skill], tools=[_tool(skill)]),
    )
    linked = tmp_path / SKILLS_LOCK_FILENAME
    linked.symlink_to(real.name)
    with pytest.raises(SkillLockCorruptError, match="symbolic links"):
        load_skills_lock(linked)


def test_corrupt_or_manually_edited_lock_is_rejected(tmp_path: Path):
    skill = _skill()
    lock = build_skills_lock(run_id="run-1", skills=[skill], tools=[_tool(skill)])
    path = tmp_path / SKILLS_LOCK_FILENAME
    write_or_verify_skills_lock(path, lock)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["tools"][0]["name"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SkillLockCorruptError, match="recomputed"):
        load_skills_lock(path)


def test_mcp_client_keeps_active_snapshot_and_new_client_rejects_drift(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / SKILLS_LOCK_FILENAME
    skill = _skill()
    manifest_path = tmp_path / "skill.yaml"
    manifest_path.write_text("version: original\n", encoding="utf-8")
    skill.manifest_path = str(manifest_path)
    first_connection = _Connection(skill)
    client = MCPClient([skill], skill_lock_path=path)
    monkeypatch.setattr(client, "_init_connection", lambda _skill: first_connection)

    first_tools = client.list_tools()
    first_lock = path.read_bytes()
    manifest_path.write_text("version: modified\n", encoding="utf-8")

    # No rediscovery happens inside the active run client.
    assert client.list_tools() == first_tools
    assert path.read_bytes() == first_lock

    changed = _skill(manifest_digest="b" * 64)
    second_connection = _Connection(changed, {"type": "string"})
    resumed = MCPClient([changed], skill_lock_path=path)
    monkeypatch.setattr(resumed, "_init_connection", lambda _skill: second_connection)
    with pytest.raises(SkillLockMismatchError):
        resumed.list_tools()
    assert resumed.skills_lock is None
    assert resumed._tools_cache is None


def test_locked_run_fails_closed_when_required_provider_cannot_start(
    tmp_path: Path, monkeypatch
):
    client = MCPClient([_skill()], skill_lock_path=tmp_path / SKILLS_LOCK_FILENAME)

    def _fail(_skill):
        raise OSError("provider unavailable")

    monkeypatch.setattr(client, "_init_connection", _fail)
    with pytest.raises(SkillProviderAdmissionError, match="failed live discovery"):
        client.list_tools()
