"""Contract tests for canonical ARI Skill manifests and admission metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ari.config import SkillConfig, _discover_skills, load_config
from ari.mcp.client import (
    DEFAULT_TOOL_TIMEOUT,
    MCPClient,
    ToolNameCollisionError,
    _resolve_tool_timeout,
)
from ari.skill_manifest import (
    SkillManifestError,
    legacy_mcp_document,
    load_skill_manifest,
    manifest_digest,
)


def _manifest(
    *, name: str = "fixture-skill", package: str = "ari-skill-fixture"
) -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "package": package,
        "version": "1.2.3",
        "entrypoint": {
            "transport": "stdio",
            "command_kind": "python",
            "module": "src/server.py",
        },
        "tool_defaults": {
            "phases": ["bfts"],
            "side_effects": "read-only",
            "determinism": "deterministic",
            "timeout_class": "bounded",
            "permissions": ["workspace-read"],
            "result_schema": "ari.legacy-mcp-result/v1",
        },
        "tools": [
            {"name": "inspect", "capability_ref": "ari.fixture.inspect"},
            {
                "name": "mutate",
                "capability_ref": "ari.fixture.mutate",
                "side_effects": "workspace-write",
                "timeout_class": "slow",
            },
        ],
    }


def _write_package(root: Path, document: dict) -> Path:
    package = root / document["package"]
    (package / "src").mkdir(parents=True)
    (package / "src" / "server.py").write_text("# fixture\n", encoding="utf-8")
    manifest_path = package / "skill.yaml"
    manifest_path.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    return manifest_path


def test_manifest_loads_and_resolves_tool_defaults(tmp_path: Path):
    path = _write_package(tmp_path, _manifest())
    manifest = load_skill_manifest(path)

    inspect = manifest.tool("inspect")
    mutate = manifest.tool("mutate")
    assert inspect is not None and inspect.phases == ["bfts"]
    assert inspect.timeout_class == "bounded"
    assert mutate is not None and mutate.side_effects == "workspace-write"
    assert mutate.timeout_class == "slow"
    assert len(manifest_digest(manifest)) == 64
    assert legacy_mcp_document(manifest)["tools"] == ["inspect", "mutate"]


def test_manifest_rejects_duplicate_tools(tmp_path: Path):
    document = _manifest()
    document["tools"].append(document["tools"][0].copy())
    path = _write_package(tmp_path, document)
    with pytest.raises(SkillManifestError, match="duplicate tool"):
        load_skill_manifest(path)


def test_manifest_rejects_entrypoint_traversal(tmp_path: Path):
    document = _manifest()
    document["entrypoint"]["module"] = "../server.py"
    path = _write_package(tmp_path, document)
    with pytest.raises(SkillManifestError, match="safe POSIX-relative"):
        load_skill_manifest(path)


def test_legacy_manifest_requires_explicit_opt_in(tmp_path: Path):
    package = tmp_path / "ari-skill-legacy"
    package.mkdir()
    path = package / "skill.yaml"
    path.write_text(
        yaml.safe_dump(
            {"name": "legacy-skill", "version": "0.1.0", "tools": ["old_tool"]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError, match="schema_version"):
        load_skill_manifest(path)
    migrated = load_skill_manifest(path, allow_legacy=True)
    assert migrated.package == "ari-skill-legacy"
    assert [tool.name for tool in migrated.tools] == ["old_tool"]


def test_discovery_uses_manifest_identity_and_skips_default_off(tmp_path: Path):
    enabled = _manifest(name="enabled-skill", package="ari-skill-enabled")
    disabled = _manifest(name="disabled-skill", package="ari-skill-disabled")
    disabled["enabled_by_default"] = False
    _write_package(tmp_path, enabled)
    _write_package(tmp_path, disabled)

    skills = _discover_skills(tmp_path)
    assert [skill.name for skill in skills] == ["enabled-skill"]
    assert skills[0].package == "ari-skill-enabled"
    assert skills[0].entrypoint == "src/server.py"
    assert skills[0].tool_timeout_classes == {"inspect": "bounded", "mutate": "slow"}


def test_explicit_config_is_hydrated_from_manifest(tmp_path: Path):
    manifest_path = _write_package(tmp_path, _manifest())
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "skills": [
                    {
                        "name": "fixture-skill",
                        "path": str(manifest_path.parent),
                        "phase": "bfts",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    skill = load_config(str(config_path)).skills[0]
    assert skill.manifest_path == str(manifest_path)
    assert skill.version == "1.2.3"
    assert skill.tool_timeout_classes["mutate"] == "slow"


def test_manifest_timeout_class_precedes_legacy_name_table():
    # generate_ideas is legacy slow-tiered, but a canonical bounded declaration
    # must be authoritative during the transition.
    assert (
        _resolve_tool_timeout("generate_ideas", {}, timeout_class="bounded")
        == DEFAULT_TOOL_TIMEOUT
    )


class _FakeConnection:
    def __init__(self, skill: SkillConfig):
        self.skill = skill

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "shared",
                "description": "",
                "inputSchema": {},
                "skill_name": self.skill.name,
            }
        ]

    def close(self) -> None:
        pass


def test_tool_name_collision_fails_instead_of_last_writer_wins(monkeypatch):
    skills = [
        SkillConfig(name="one", path="/tmp/one"),
        SkillConfig(name="two", path="/tmp/two"),
    ]
    client = MCPClient(skills)
    monkeypatch.setattr(
        client, "_init_connection", lambda skill: _FakeConnection(skill)
    )

    with pytest.raises(ToolNameCollisionError, match="shared: one, two"):
        client.list_tools()
