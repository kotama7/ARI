from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from ari.cli import app
from ari.knowledge.catalog import load_knowledge_catalog
from ari.knowledge.external_importer import (
    import_git_knowledge_skill,
    import_open_agent_skill,
    import_tooluniverse_knowledge_collection,
)
from ari.knowledge.external_models import (
    KnowledgeImportMaterialV1,
    KnowledgeSkillImportProfileV1,
    ToolUniverseKnowledgeCollectionProfileV1,
)
from ari.knowledge.git_source import KnowledgeGitSourceError
from ari.knowledge.importer import KnowledgeImportError
from ari.protocols.integrity import canonical_digest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def _commit(repo: Path) -> str:
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        _git(repo, "config", "user.name", "ARI Tests")
        _git(repo, "config", "user.email", "ari-tests@example.invalid")
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "fixture")
    return _git(repo, "rev-parse", "HEAD")


def _body(prefix: str = "") -> str:
    return (
        prefix
        + """# External procedure

## When to use
Use for the declared task.

## Preconditions
Inputs are immutable.

## Procedure
Use a compile capability and inspect the result.

## Decision points
Stop if evidence is missing.

## Failure conditions
Treat an invalid result as failure.

## Expected artifacts
Produce a report.

## Scientific cautions
Do not overclaim.

## Evaluation obligations
Run differential testing.
"""
    )


def _profile(
    skill_id: str = "external.procedure",
    *,
    body_license: str = "MIT",
) -> KnowledgeSkillImportProfileV1:
    return KnowledgeSkillImportProfileV1.model_validate(
        {
            "schema_version": 1,
            "id": skill_id,
            "version": "1.0.0",
            "title": "External Procedure",
            "description": "Human-reviewed semantics for an external procedure.",
            "license": {"body": body_license, "references": "CC-BY-4.0"},
            "applies_to": {
                "roles": ["generator"],
                "phases": ["bfts"],
                "task_tags": ["external"],
            },
            "requires": {
                "capabilities": [{"ref": "ari.execution.compile/v1", "required": True}]
            },
            "authority_ceiling": {"side_effects": ["read-only", "workspace-write"]},
            "forbidden_capabilities": ["ari.registry.write/v1"],
            "composition": {"slot": "domain-method", "priority": 100},
        }
    )


def _write_plain_skill(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(_body(), encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "guide.md").write_text("reference\n", encoding="utf-8")
    (root / "scripts").mkdir()
    script = root / "scripts" / "must-not-run.py"
    script.write_text("raise RuntimeError('executed')\n", encoding="utf-8")
    script.chmod(0o755)


def _write_open_agent_skill(
    root: Path,
    *,
    name: str | None = None,
    license_name: str = "Apache-2.0",
) -> None:
    root.mkdir(parents=True)
    skill_name = name or root.name
    frontmatter = (
        "---\n"
        f"name: {skill_name}\n"
        "description: Use this external scientific procedure for pinned tests.\n"
        f"license: {license_name}\n"
        "compatibility: Requires tools, but ARI treats this as a hint only.\n"
        "allowed-tools: Bash(git:*) Read\n"
        "metadata:\n"
        "  author: upstream\n"
        "  version: '1.0.0'\n"
        "---\n\n"
    )
    (root / "SKILL.md").write_text(_body(frontmatter), encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "method.md").write_text("method\n", encoding="utf-8")
    (root / "scripts").mkdir()
    script = root / "scripts" / "run.sh"
    script.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    script.chmod(0o755)
    (root / "assets").mkdir()
    (root / "assets" / "template.txt").write_text("template\n", encoding="utf-8")


def test_pinned_git_import_reads_only_exact_subtree_and_never_executes_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = tmp_path / "source"
    _write_plain_skill(repo / "skills" / "plain")
    (repo / "outside-secret.txt").write_text("not imported\n", encoding="utf-8")
    commit = _commit(repo)
    (repo / "skills" / "plain" / "SKILL.md").write_text(
        "mutable working tree must be ignored\n", encoding="utf-8"
    )
    marker = tmp_path / "executed"
    monkeypatch.chdir(tmp_path)
    imported = import_git_knowledge_skill(
        repository="source",
        commit=commit,
        subpath="skills/plain",
        profile=_profile(),
    )
    repeated = import_git_knowledge_skill(
        repository="source",
        commit=commit,
        subpath="skills/plain",
        profile=_profile(),
        source_kind="scientific-skill-repository",
    )

    assert imported.manifest.status == "candidate"
    assert imported.manifest.source.repository == str(repo.resolve())
    assert imported.manifest.source.commit == commit
    assert imported.manifest.source.path == "skills/plain"
    assert "mutable working tree" not in imported.body
    assert tuple(imported.references) == ("references/guide.md",)
    assert imported.attachments == ("scripts/must-not-run.py",)
    assert imported.attachment_records[0].executable_in_source is True
    assert imported.source_provenance.source_kind == "git"
    assert imported.source_provenance.commit == commit
    assert repeated.source_provenance.source_kind == "scientific-skill-repository"
    assert repeated.source_provenance.snapshot_digest == (
        imported.source_provenance.snapshot_digest
    )
    assert repeated.manifest == imported.manifest
    assert "outside-secret" not in json.dumps(imported.source_provenance.model_dump())
    assert not marker.exists()

    manifest = imported.manifest.model_dump(mode="json")
    source = dict(manifest["source"])
    expected = source.pop("manifest_sha256")
    manifest["source"] = source
    assert expected == canonical_digest(manifest)


def test_git_import_rejects_mutable_ref_unsafe_remote_and_symlink(tmp_path: Path):
    with pytest.raises(KnowledgeGitSourceError, match="full commit"):
        import_git_knowledge_skill(
            repository=str(tmp_path),
            commit="main",
            subpath="skills/x",
            profile=_profile(),
        )

    with pytest.raises(KnowledgeGitSourceError, match="scheme"):
        import_git_knowledge_skill(
            repository="ext::sh -c touch /tmp/ari-knowledge-import-pwned",
            commit="1" * 40,
            subpath="skills/x",
            profile=_profile(),
        )

    repo = tmp_path / "symlink-source"
    skill = repo / "skills" / "linked"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_body(), encoding="utf-8")
    os.symlink("SKILL.md", skill / "references-link")
    commit = _commit(repo)
    with pytest.raises(KnowledgeGitSourceError, match="POSIX-relative"):
        import_git_knowledge_skill(
            repository=str(repo),
            commit=commit,
            subpath="/absolute/path",
            profile=_profile(),
        )

    with pytest.raises(KnowledgeGitSourceError, match="symlink"):
        import_git_knowledge_skill(
            repository=str(repo),
            commit=commit,
            subpath="skills/linked",
            profile=_profile(),
        )


def test_open_agent_skills_frontmatter_is_validated_but_never_grants_authority(
    tmp_path: Path,
):
    repo = tmp_path / "open-source"
    _write_open_agent_skill(repo / "skills" / "open-procedure")
    commit = _commit(repo)
    imported = import_open_agent_skill(
        repository=str(repo),
        commit=commit,
        subpath="skills/open-procedure",
        profile=_profile("external.open-procedure", body_license="Apache-2.0"),
    )

    assert not imported.body.startswith("---")
    assert imported.manifest.status == "candidate"
    assert [item.ref for item in imported.manifest.requires.capabilities] == [
        "ari.execution.compile/v1"
    ]
    assert "Bash(git:*)" in imported.non_authoritative_hints
    assert "Read" in imported.non_authoritative_hints
    assert imported.attachments == (
        "assets/template.txt",
        "scripts/run.sh",
    )
    assert imported.source_provenance.source_kind == "open-agent-skills"
    assert imported.source_provenance.upstream_name == "open-procedure"
    assert imported.source_provenance.source_skill_md_sha256 != (
        imported.manifest.source.body_sha256
    )


def test_open_agent_skills_name_and_admin_license_must_match(tmp_path: Path):
    repo = tmp_path / "bad-open-source"
    _write_open_agent_skill(repo / "skills" / "directory-name", name="another-name")
    commit = _commit(repo)
    with pytest.raises(KnowledgeImportError, match="parent directory"):
        import_open_agent_skill(
            repository=str(repo),
            commit=commit,
            subpath="skills/directory-name",
            profile=_profile(body_license="Apache-2.0"),
        )

    repo2 = tmp_path / "license-source"
    _write_open_agent_skill(repo2 / "skills" / "licensed")
    commit2 = _commit(repo2)
    with pytest.raises(KnowledgeImportError, match="license differs"):
        import_open_agent_skill(
            repository=str(repo2),
            commit=commit2,
            subpath="skills/licensed",
            profile=_profile(body_license="MIT"),
        )


def test_open_agent_wrapper_admits_missing_ari_sections_as_quoted_candidate(
    tmp_path: Path,
):
    repo = tmp_path / "wrapped-open-source"
    skill = repo / "skills" / "wrapped-procedure"
    skill.mkdir(parents=True)
    source_body = "# Upstream workflow\n\nRun `sudo unsafe-command` when profiling.\n"
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: wrapped-procedure\n"
        "description: Upstream body without the ARI section contract.\n"
        "---\n\n" + source_body,
        encoding="utf-8",
    )
    commit = _commit(repo)

    with pytest.raises(KnowledgeImportError, match="missing required sections"):
        import_open_agent_skill(
            repository=str(repo),
            commit=commit,
            subpath="skills/wrapped-procedure",
            profile=_profile("external.wrapped-procedure"),
        )

    profile_document = _profile("external.wrapped-procedure").model_dump(mode="json")
    profile_document.update(
        {
            "body_normalization": "ari-wrapper-v1",
            "curation_notes": ["Never grant host administration authority."],
        }
    )
    imported = import_open_agent_skill(
        repository=str(repo),
        commit=commit,
        subpath="skills/wrapped-procedure",
        profile=KnowledgeSkillImportProfileV1.model_validate(profile_document),
    )

    assert imported.manifest.status == "candidate"
    assert imported.source_provenance.body_normalization == "ari-wrapper-v1"
    assert "## When to use" in imported.body
    assert "## Evaluation obligations" in imported.body
    assert "> Run `sudo unsafe-command` when profiling." in imported.body
    assert "Never grant host administration authority." in imported.body
    assert imported.source_provenance.source_skill_md_sha256 != (
        imported.manifest.source.body_sha256
    )


def test_tooluniverse_knowledge_collection_has_no_provider_activation(tmp_path: Path):
    repo = tmp_path / "tooluniverse-knowledge"
    _write_open_agent_skill(repo / "collections" / "science" / "method-one")
    _write_open_agent_skill(repo / "collections" / "science" / "method-two")
    commit = _commit(repo)
    profile = ToolUniverseKnowledgeCollectionProfileV1.model_validate(
        {
            "schema_version": 1,
            "kind": "tooluniverse-knowledge",
            "collection_id": "science.methods",
            "version": "1.0.0",
            "entries": [
                {
                    "subpath": "method-one",
                    "layout": "open-agent-skills",
                    "profile": _profile(
                        "tooluniverse.knowledge.method-one",
                        body_license="Apache-2.0",
                    ).model_dump(mode="json"),
                },
                {
                    "subpath": "method-two",
                    "layout": "open-agent-skills",
                    "profile": _profile(
                        "tooluniverse.knowledge.method-two",
                        body_license="Apache-2.0",
                    ).model_dump(mode="json"),
                },
            ],
        }
    )
    imported = import_tooluniverse_knowledge_collection(
        repository=str(repo),
        commit=commit,
        root_subpath="collections/science",
        profile=profile,
    )

    with pytest.raises(KnowledgeImportError, match="collection root"):
        import_tooluniverse_knowledge_collection(
            repository=str(repo),
            commit=commit,
            root_subpath="/collections/science",
            profile=profile,
        )

    assert imported.provenance.collection_uri == (
        "ari://knowledge-source/tooluniverse/science.methods@1.0.0"
    )
    assert len(imported.skills) == 2
    assert all(item.manifest.status == "candidate" for item in imported.skills)
    assert all(
        item.source_provenance.source_kind == "tooluniverse-knowledge"
        for item in imported.skills
    )
    assert all(
        item.source_provenance.collection_identity_digest
        == imported.provenance.collection_identity_digest
        for item in imported.skills
    )
    assert "provider" not in json.dumps(
        imported.provenance.model_dump(mode="json"), sort_keys=True
    )

    document = profile.model_dump(mode="json")
    document["provider_id"] = "tooluniverse"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolUniverseKnowledgeCollectionProfileV1.model_validate(document)


def test_external_import_cli_emits_candidate_material_without_catalog_write(
    tmp_path: Path,
):
    repo = tmp_path / "cli-source"
    _write_open_agent_skill(repo / "skills" / "cli-skill")
    commit = _commit(repo)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        yaml.safe_dump(
            _profile("external.cli-skill", body_license="Apache-2.0").model_dump(
                mode="json"
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "knowledge",
            "import",
            "--source-kind",
            "open-agent-skills",
            "--repository",
            str(repo),
            "--commit",
            commit,
            "--subpath",
            "skills/cli-skill",
            "--profile",
            str(profile_path),
        ],
    )
    assert result.exit_code == 0, result.output
    material = json.loads(result.output)
    parsed = KnowledgeImportMaterialV1.model_validate(material)
    assert material["decision"] == "candidate"
    assert material["authoritative"] is False
    assert material["body"] == parsed.body
    assert material["body_sha256"] == parsed.manifest.source.body_sha256
    assert material["source_provenance"]["source_kind"] == "open-agent-skills"
    assert material["attachments"][0]["authority"] == "none"
    assert not (tmp_path / "catalog.yaml").exists()


def test_checked_in_intel_performance_skills_are_distinct_pinned_entries():
    config_root = Path(__file__).resolve().parents[1] / "config" / "knowledge_skills"
    loaded = load_knowledge_catalog(config_root / "catalog.yaml")
    intel_entries = {
        entry.manifest.id: entry
        for entry in loaded.snapshot.entries
        if entry.manifest.id.startswith("intel.")
    }

    assert set(intel_entries) == {
        "intel.linux-perf",
        "intel.performance-patterns",
        "intel.phoronix-test-suite",
    }
    # Promoted on reviewed evidence; each promotion carries its own approval.
    assert all(entry.status == "verified" for entry in intel_entries.values())
    assert set(loaded.promotion_approvals) >= set(intel_entries)
    assert all(
        entry.importer_version == "ari.knowledge.external-importer/v1"
        for entry in intel_entries.values()
    )
    assert all(
        entry.manifest.source.repository
        == "https://github.com/intel/intel-performance-skills.git"
        and entry.manifest.source.commit == "e9d0b6410fb1ad7a50fb81e0868fd23ae886882c"
        for entry in intel_entries.values()
    )

    materials = {
        path.stem: KnowledgeImportMaterialV1.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        for path in (config_root / "imports").glob("intel_*.json")
    }
    assert len(materials) == 3
    assert all(
        material.source_provenance is not None
        and material.source_provenance.body_normalization == "ari-wrapper-v1"
        and material.authoritative is False
        for material in materials.values()
    )
    pattern_material = materials["intel_performance_patterns"]
    assert any(
        attachment.path.endswith("run-mutex-to-rwlock-bench.sh")
        and attachment.executable_in_source
        and attachment.authority == "none"
        for attachment in pattern_material.attachments
    )

    for entry in intel_entries.values():
        body = loaded.body_store.get_text(entry.body_store_key)
        assert "## Preconditions" in body
        assert "## Evaluation obligations" in body
        assert "non-authoritative procedural" in body
