from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ari.public.skill_lock import SkillsLockV1, skills_lock_digest
from ari_skill_orchestrator.artifacts import ArtifactPolicyError, MAX_INLINE_BYTES
from ari_skill_orchestrator.contracts import PrincipalV1, RunRequestV1
from ari_skill_orchestrator.registry import RunAuthorizationError
from ari_skill_orchestrator.service import (
    OrchestratorService,
    ServiceConfig,
    ServiceError,
)


ALICE = PrincipalV1(principal_id="alice", authentication="test")
BOB = PrincipalV1(principal_id="bob", authentication="test")


def _control(tmp_path: Path) -> OrchestratorService:
    return OrchestratorService(
        ServiceConfig(
            workspace=tmp_path,
            logs_root=tmp_path / "logs",
            ari_cli="unused",
            dry_run=True,
        )
    )


def _run(control: OrchestratorService, key: str = "artifacts"):
    return control.submit(
        RunRequestV1.from_parameters(
            experiment_md="# artifact test\nscience",
            idempotency_key=key,
        ),
        ALICE,
    )


def _write_skills_lock(path: Path, run_id: str) -> None:
    raw = {
        "schema_version": "ari.skills-lock/v1",
        "run_id": run_id,
        "registry_digest": "",
        "skills": [
            {
                "name": "safe-skill",
                "package": "safe-package",
                "version": "1.2.3",
                "entrypoint": "/private/workspace/server.py",
                "manifest_digest": "private-manifest",
                "provider_digest": "provider-digest",
                "configured_phases": ["control"],
                "environment_policy": "complete",
                "required_env": ["SECRET_VALUE"],
                "optional_env": [],
                "credential_scopes": [],
                "tool_refs": ["tool:locked"],
            }
        ],
        "tools": [
            {
                "tool_ref": "tool:locked",
                "name": "locked",
                "skill_name": "safe-skill",
                "capability_ref": "safe.read",
                "input_schema": {"secretDefault": "not-returned"},
                "output_schema": {},
                "input_schema_digest": "input-digest",
                "output_schema_digest": "output-digest",
                "policy": {"phases": ["control"]},
            }
        ],
        "disabled_tools": [],
        "phase_active_tools": {"control": ["tool:locked"]},
    }
    provisional = SkillsLockV1.model_validate(raw)
    raw["registry_digest"] = skills_lock_digest(provisional)
    lock = SkillsLockV1.model_validate(raw)
    path.write_text(
        json.dumps(lock.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )


def test_artifact_api_exposes_digest_not_path(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control)
    record = control.registry.get(handle.run_id, ALICE)
    (record.checkpoint_dir / "private-notes.txt").write_text("must remain private")
    artifacts = control.list_artifacts(handle.run_id, ALICE)
    assert artifacts
    assert all("path" not in item and "checkpoint" not in item for item in artifacts)
    roles = {item["role"] for item in artifacts}
    assert {"experiment-spec", "execution-log"} <= roles
    assert all(item["artifact_id"] == item["digest"] for item in artifacts)
    experiment = next(item for item in artifacts if item["role"] == "experiment-spec")
    read = control.read_artifact(handle.run_id, experiment["artifact_id"], ALICE)
    assert read["encoding"] == "utf-8"
    assert "artifact test" in read["content"]
    private_digest = "sha256:" + hashlib.sha256(b"must remain private").hexdigest()
    with pytest.raises(ArtifactPolicyError, match="not admitted"):
        control.read_artifact(handle.run_id, private_digest, ALICE)


def test_symlinked_allowlisted_artifact_is_refused(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "symlink")
    record = control.registry.get(handle.run_id, ALICE)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (record.checkpoint_dir / "results.json").symlink_to(outside)
    with pytest.raises(ArtifactPolicyError, match="symbolic"):
        control.list_artifacts(handle.run_id, ALICE)


def test_secret_like_evidence_path_fails_closed(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "secret-index")
    record = control.registry.get(handle.run_id, ALICE)
    ear = record.checkpoint_dir / "ear"
    ear.mkdir()
    (ear / ".env").write_text("TOKEN=x")
    unsigned = {
        "schema_version": "ari.ear-evidence-index/v1",
        "records": [
            {
                "path": ".env",
                "digest": "sha256:" + hashlib.sha256(b"TOKEN=x").hexdigest(),
                "size_bytes": 7,
                "role": "ear-output",
            }
        ],
    }
    encoded = (json.dumps(unsigned, sort_keys=True, indent=2) + "\n").encode()
    document = {
        **unsigned,
        "index_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }
    (ear / "evidence.index.json").write_text(json.dumps(document))
    with pytest.raises(ArtifactPolicyError, match="unsafe path"):
        control.list_artifacts(handle.run_id, ALICE)


def test_large_artifact_can_be_listed_but_not_inlined(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "large")
    record = control.registry.get(handle.run_id, ALICE)
    payload = b"x" * (MAX_INLINE_BYTES + 1)
    (record.checkpoint_dir / "results.json").write_bytes(payload)
    ref = next(
        item
        for item in control.list_artifacts(handle.run_id, ALICE)
        if item["role"] == "execution-results"
    )
    with pytest.raises(ArtifactPolicyError, match="inline read limit"):
        control.read_artifact(handle.run_id, ref["artifact_id"], ALICE)


def test_non_object_evidence_index_fails_as_artifact_policy(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "bad-index-shape")
    record = control.registry.get(handle.run_id, ALICE)
    ear = record.checkpoint_dir / "ear"
    ear.mkdir()
    (ear / "evidence.index.json").write_text("[]")
    with pytest.raises(ArtifactPolicyError, match="must be an object"):
        control.list_artifacts(handle.run_id, ALICE)


def test_artifact_authorization_precedes_discovery(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "auth")
    with pytest.raises(RunAuthorizationError):
        control.list_artifacts(handle.run_id, BOB)


def test_locked_skill_and_workflow_views_are_sanitized(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "lock")
    record = control.registry.get(handle.run_id, ALICE)
    _write_skills_lock(record.checkpoint_dir / "SKILLS.lock", handle.run_id)
    skills = control.list_skills(handle.run_id, ALICE)
    workflow = control.workflow(handle.run_id, ALICE)
    rendered = json.dumps({"skills": skills, "workflow": workflow})
    assert "tool:locked" in rendered
    assert "SECRET_VALUE" not in rendered
    assert "private/workspace" not in rendered
    assert "secretDefault" not in rendered
    assert set(workflow) == {
        "run_id",
        "registry_digest",
        "phase_active_tools",
        "disabled_tools",
    }


def test_skill_view_requires_verified_lock(tmp_path: Path) -> None:
    control = _control(tmp_path)
    handle = _run(control, "missing-lock")
    with pytest.raises(ServiceError, match="SKILLS.lock"):
        control.list_skills(handle.run_id, ALICE)
