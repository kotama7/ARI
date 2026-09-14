from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ari_skill_orchestrator.contracts import PrincipalV1, RunRequestV1
from ari_skill_orchestrator.registry import (
    IdempotencyConflictError,
    QuotaExceededError,
    RegistryError,
    RunAuthorizationError,
    RunRegistry,
    RunNotFoundError,
)
from ari_skill_orchestrator.service import (
    OrchestratorService,
    QuotaPolicy,
    ResourcePolicyError,
    ServiceConfig,
)


def principal(name: str = "alice", *roles: str) -> PrincipalV1:
    return PrincipalV1(principal_id=name, roles=roles, authentication="test")


def request(key: str, text: str = "science", **updates) -> RunRequestV1:
    values = {
        "experiment_md": text,
        "idempotency_key": key,
        "max_nodes": 1,
        "max_total_nodes": 10,
        "max_descendant_runs": 4,
        "max_cost_usd": 10.0,
    }
    values.update(updates)
    return RunRequestV1.from_parameters(**values)


def service(tmp_path: Path, *, quota: QuotaPolicy | None = None) -> OrchestratorService:
    return OrchestratorService(
        ServiceConfig(
            workspace=tmp_path,
            logs_root=tmp_path / "logs",
            ari_cli="unused",
            dry_run=True,
            quota=quota or QuotaPolicy(),
        )
    )


def test_idempotent_retry_reuses_exact_run(tmp_path: Path) -> None:
    control = service(tmp_path)
    first = control.submit(request("same"), principal())
    second = control.submit(request("same"), principal())
    assert first.run_id == second.run_id
    assert second.reused is True
    assert second.state == "succeeded"
    assert len(control.registry.list(principal())) == 1


def test_idempotency_key_conflict_fails_closed(tmp_path: Path) -> None:
    control = service(tmp_path)
    control.submit(request("same", "first"), principal())
    with pytest.raises(IdempotencyConflictError):
        control.submit(request("same", "different"), principal())


def test_parallel_retry_creates_one_row_and_checkpoint(tmp_path: Path) -> None:
    control = service(tmp_path)

    def submit_once(_index: int) -> str:
        return control.submit(request("parallel"), principal()).run_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        run_ids = list(pool.map(submit_once, range(24)))
    assert len(set(run_ids)) == 1
    assert len(control.registry.list(principal())) == 1
    checkpoints = [
        path for path in (tmp_path / "logs").iterdir() if path.name.startswith("run_")
    ]
    assert len(checkpoints) == 1


def test_owner_scope_and_admin_override(tmp_path: Path) -> None:
    control = service(tmp_path)
    handle = control.submit(request("owned"), principal("alice"))
    with pytest.raises(RunAuthorizationError):
        control.status(handle.run_id, principal("bob"))
    assert (
        control.status(handle.run_id, principal("root", "admin")).run_id
        == handle.run_id
    )
    assert control.list_runs(principal("bob")) == []


def test_run_id_lookup_is_exact(tmp_path: Path) -> None:
    control = service(tmp_path)
    handle = control.submit(request("exact"), principal())
    with pytest.raises(RunNotFoundError):
        control.status(handle.run_id[-16:], principal())


def test_depth_descendant_node_and_cost_budgets(tmp_path: Path) -> None:
    control = service(tmp_path)
    root = control.submit(
        request(
            "root",
            max_recursion_depth=1,
            max_total_nodes=2,
            max_descendant_runs=1,
            estimated_cost_usd=1.0,
            max_cost_usd=2.0,
        ),
        principal(),
    )
    child = control.submit(
        request(
            "child",
            parent_run_id=root.run_id,
            max_recursion_depth=4,
            estimated_cost_usd=1.0,
        ),
        principal(),
    )
    assert child.recursion_depth == 1
    assert child.max_recursion_depth == 1
    with pytest.raises(QuotaExceededError, match="recursion|descendant|node|cost"):
        control.submit(
            request("grandchild", parent_run_id=child.run_id, max_recursion_depth=4),
            principal(),
        )


def test_deployment_quota_rejected_before_checkpoint(tmp_path: Path) -> None:
    control = service(
        tmp_path,
        quota=QuotaPolicy(max_nodes_per_run=2, max_total_nodes=2),
    )
    with pytest.raises(ResourcePolicyError, match="max_nodes|max_total_nodes"):
        control.submit(
            request("too-large", max_nodes=3, max_total_nodes=3), principal()
        )
    assert not (tmp_path / "logs" / "run_").exists()
    assert control.registry.list(principal()) == []


def test_invalid_embedded_policy_values_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ResourcePolicyError, match="finite"):
        QuotaPolicy(max_cost_usd=float("nan"))
    with pytest.raises(ResourcePolicyError, match="integers"):
        QuotaPolicy(max_active_runs=1.5)  # type: ignore[arg-type]
    with pytest.raises(ResourcePolicyError, match="grace"):
        ServiceConfig(
            workspace=tmp_path,
            logs_root=tmp_path / "logs",
            ari_cli="unused",
            cancellation_grace_seconds=float("nan"),
        )


def test_symbolic_registry_database_is_refused(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    state = logs / ".ari-orchestrator"
    state.mkdir(parents=True)
    target = tmp_path / "outside.sqlite3"
    target.touch()
    (state / "runs.sqlite3").symlink_to(target)
    with pytest.raises(RegistryError, match="database cannot be symbolic"):
        RunRegistry(logs)


def test_terminal_transition_is_recorded_once(tmp_path: Path) -> None:
    control = service(tmp_path)
    handle = control.submit(request("events"), principal())
    for _ in range(3):
        assert control.status(handle.run_id, principal()).state == "succeeded"
    events = control.registry.events(handle.run_id)
    assert [event["to_state"] for event in events].count("succeeded") == 1


def test_legacy_scan_is_explicit_and_ambiguous_state_fails_closed(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    legacy = logs / "legacy-run"
    legacy.mkdir(parents=True)
    (legacy / "experiment.md").write_text("# legacy\nscience")
    (legacy / "results.json").write_text('{"nodes": {}}')
    (legacy / "meta.json").write_text('{"run_id":"legacy-run","status":"running"}')
    control = OrchestratorService(
        ServiceConfig(
            workspace=tmp_path,
            logs_root=logs,
            ari_cli="unused",
            dry_run=True,
        )
    )
    # Ordinary listing is database-only and does not infer the legacy run.
    assert control.list_runs(principal()) == []
    repaired = control.repair_legacy_registry(principal())
    assert repaired["imported"] == ["legacy-run"]
    assert control.status("legacy-run", principal()).state == "failed"
    assert control.repair_legacy_registry(principal())["already_present"] == [
        "legacy-run"
    ]


def test_legacy_success_requires_valid_results_object(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    legacy = logs / "legacy-corrupt"
    legacy.mkdir(parents=True)
    (legacy / "experiment.md").write_text("# legacy\nscience")
    (legacy / "results.json").write_text("[]")
    (legacy / "meta.json").write_text(
        '{"run_id":"legacy-corrupt","status":"succeeded"}'
    )
    control = OrchestratorService(
        ServiceConfig(
            workspace=tmp_path,
            logs_root=logs,
            ari_cli="unused",
            dry_run=True,
        )
    )
    control.repair_legacy_registry(principal())
    assert control.status("legacy-corrupt", principal()).state == "failed"


def test_legacy_repair_rejects_duplicate_and_cyclic_identity(tmp_path: Path) -> None:
    logs = tmp_path / "logs"

    def checkpoint(name: str, metadata: dict) -> None:
        path = logs / name
        path.mkdir(parents=True)
        (path / "experiment.md").write_text("# legacy\nscience")
        (path / "results.json").write_text("{}")
        (path / "meta.json").write_text(json.dumps(metadata))

    checkpoint("duplicate-a", {"run_id": "duplicate", "status": "succeeded"})
    checkpoint("duplicate-b", {"run_id": "duplicate", "status": "succeeded"})
    checkpoint("cycle-a", {"parent_run_id": "cycle-b"})
    checkpoint("cycle-b", {"parent_run_id": "cycle-a"})
    control = service(tmp_path)
    repaired = control.repair_legacy_registry(principal())
    assert repaired["imported"] == []
    skipped = {item["run_id"] for item in repaired["skipped"]}
    assert {"duplicate", "cycle-a", "cycle-b"} <= skipped
