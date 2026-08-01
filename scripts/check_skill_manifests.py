#!/usr/bin/env python3
"""Check canonical Skill manifests against runtime, workflow, and package data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ari-core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ari.skill_manifest import (  # noqa: E402
    SkillManifestError,
    SkillManifestV1,
    legacy_mcp_document,
    load_skill_manifest,
    resolve_skill_entrypoint,
)
from snapshot_contracts import _scan_skill_tools  # noqa: E402


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def _project_version(pyproject: Path) -> str | None:
    """Read ``project.version`` without adding a TOML dependency on Python 3.9."""

    in_project = False
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project:
            match = re.fullmatch(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
            if match:
                return match.group(1)
    return None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check_repo(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    manifests = {}
    runtime_dirs = {
        path.parent.parent
        for path in repo_root.glob("ari-skill-*/src/server.py")
        if path.is_file()
    }

    for skill_dir in sorted(runtime_dirs):
        manifest_path = skill_dir / "skill.yaml"
        rel = _relative(manifest_path, repo_root)
        if not manifest_path.is_file():
            findings.append(
                Finding("manifest-missing", rel, "canonical skill.yaml is required")
            )
            continue
        try:
            manifest = load_skill_manifest(manifest_path)
            entrypoint = resolve_skill_entrypoint(skill_dir, manifest)
        except SkillManifestError as exc:
            findings.append(Finding("manifest-invalid", rel, str(exc)))
            continue
        manifests[manifest.package] = (manifest_path, manifest)

        if manifest.package != skill_dir.name:
            findings.append(
                Finding(
                    "package-mismatch",
                    rel,
                    f"package={manifest.package!r}, directory={skill_dir.name!r}",
                )
            )

        runtime_names = {tool["name"] for tool in _scan_skill_tools(entrypoint)}
        declared_names = {tool.name for tool in manifest.tools}
        if runtime_names != declared_names:
            findings.append(
                Finding(
                    "tool-drift",
                    rel,
                    f"runtime_only={sorted(runtime_names - declared_names)}, "
                    f"manifest_only={sorted(declared_names - runtime_names)}",
                )
            )

        pyproject = skill_dir / "pyproject.toml"
        if pyproject.is_file():
            project_version = _project_version(pyproject)
            if project_version != manifest.version:
                findings.append(
                    Finding(
                        "version-drift",
                        rel,
                        f"manifest={manifest.version!r}, pyproject={project_version!r}",
                    )
                )

        mcp_path = skill_dir / "mcp.json"
        try:
            mcp_document = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                Finding(
                    "compat-metadata-invalid", _relative(mcp_path, repo_root), str(exc)
                )
            )
        else:
            expected = legacy_mcp_document(manifest)
            if mcp_document != expected:
                findings.append(
                    Finding(
                        "compat-metadata-drift",
                        _relative(mcp_path, repo_root),
                        "mcp.json must be regenerated from skill.yaml",
                    )
                )

    manifest_paths = set(repo_root.glob("ari-skill-*/skill.yaml"))
    orphan_paths = manifest_paths - {path / "skill.yaml" for path in runtime_dirs}
    for path in sorted(orphan_paths):
        findings.append(
            Finding(
                "entrypoint-package-missing",
                _relative(path, repo_root),
                "no src/server.py package inventory entry",
            )
        )

    by_name: dict[str, list[str]] = defaultdict(list)
    default_tool_owners: dict[str, list[str]] = defaultdict(list)
    for package, (_, manifest) in manifests.items():
        by_name[manifest.name].append(package)
        if manifest.enabled_by_default:
            for tool in manifest.tools:
                default_tool_owners[tool.name].append(package)
    for name, packages in sorted(by_name.items()):
        if len(packages) > 1:
            findings.append(
                Finding(
                    "skill-name-collision", "skill.yaml", f"{name}: {sorted(packages)}"
                )
            )
    for name, packages in sorted(default_tool_owners.items()):
        if len(packages) > 1:
            findings.append(
                Finding(
                    "default-tool-collision",
                    "skill.yaml",
                    f"{name}: {sorted(packages)}",
                )
            )

    workflow_path = repo_root / "ari-core" / "config" / "workflow.yaml"
    try:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        findings.append(
            Finding("workflow-invalid", _relative(workflow_path, repo_root), str(exc))
        )
        workflow = {}

    workflow_skills: dict[str, tuple[str, object]] = {}
    for configured in workflow.get("skills") or []:
        alias = configured.get("name", "")
        directory = Path(str(configured.get("path", ""))).name
        pair = manifests.get(directory)
        if pair is None:
            findings.append(
                Finding(
                    "workflow-skill-missing",
                    _relative(workflow_path, repo_root),
                    f"{alias}: {directory}",
                )
            )
            continue
        manifest = pair[1]
        workflow_skills[alias] = (directory, manifest)
        if alias != manifest.name:
            findings.append(
                Finding(
                    "workflow-skill-name-drift",
                    _relative(workflow_path, repo_root),
                    f"configured={alias!r}, manifest={manifest.name!r}",
                )
            )

    for section in ("bfts_pipeline", "pipeline"):
        for stage in workflow.get(section) or []:
            tool_name = stage.get("tool", "")
            if not tool_name:
                continue
            alias = stage.get("skill", "")
            pair = workflow_skills.get(alias)
            if pair is None:
                findings.append(
                    Finding(
                        "workflow-tool-owner-missing",
                        _relative(workflow_path, repo_root),
                        f"{section}.{stage.get('stage')}: {alias}",
                    )
                )
                continue
            manifest = pair[1]
            tool = manifest.tool(tool_name)
            if tool is None:
                findings.append(
                    Finding(
                        "workflow-tool-missing",
                        _relative(workflow_path, repo_root),
                        f"{section}.{stage.get('stage')}: {alias}/{tool_name}",
                    )
                )
                continue
            phase = stage.get("phase")
            if phase and phase not in tool.phases and "all" not in tool.phases:
                findings.append(
                    Finding(
                        "workflow-phase-mismatch",
                        _relative(workflow_path, repo_root),
                        f"{alias}/{tool_name} does not admit phase {phase!r}",
                    )
                )

    schema_path = (
        repo_root / "ari-core" / "ari" / "schemas" / "skill_manifest_v1.schema.json"
    )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema.get("properties", {}).get("schema_version", {}).get("const") != 1:
            raise ValueError("schema_version const is not 1")
        schema_fields = set(schema.get("properties", {}))
        model_fields = set(SkillManifestV1.model_fields)
        if schema_fields != model_fields:
            raise ValueError(
                f"top-level schema drift: missing={sorted(model_fields - schema_fields)}, "
                f"extra={sorted(schema_fields - model_fields)}"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        findings.append(
            Finding("json-schema-invalid", _relative(schema_path, repo_root), str(exc))
        )

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable report"
    )
    args = parser.parse_args(argv)
    findings = check_repo()
    if args.json:
        print(
            json.dumps(
                {"ok": not findings, "findings": [asdict(item) for item in findings]},
                indent=2,
            )
        )
    elif findings:
        for item in findings:
            print(f"{item.code}: {item.path}: {item.message}")
        print(f"skill manifest conformance failed: {len(findings)} finding(s)")
    else:
        print("skill manifest conformance passed")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
