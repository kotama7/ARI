"""Shared workspace/process/measurement contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from ari.public.execution import (
    ExecutionPolicyError,
    ExecutionRequestV1,
    MeasurementDocumentError,
    MeasurementRecordV1,
    MeasurementSetV1,
    WorkspaceRefV1,
    execute_local,
    parse_measurement_document,
)


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_workspace_rejects_traversal_absolute_escape_and_symlinks(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = Path(workspace.root) / "link.txt"
    link.symlink_to(outside)

    with pytest.raises(ExecutionPolicyError, match="traversal"):
        workspace.resolve("../outside.txt")
    with pytest.raises(ExecutionPolicyError, match="escapes"):
        workspace.resolve(str(outside))
    with pytest.raises(ExecutionPolicyError, match="symlink"):
        workspace.read_bytes("link.txt", max_bytes=100)
    with pytest.raises(ExecutionPolicyError, match="regular file"):
        workspace.atomic_write_text("link.txt", "replacement")
    assert outside.read_text(encoding="utf-8") == "secret"


def test_atomic_workspace_write_and_bounded_read(tmp_path: Path) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    path = workspace.atomic_write_text("nested/result.txt", "complete")
    assert path.read_text(encoding="utf-8") == "complete"
    assert workspace.read_bytes("nested/result.txt", max_bytes=100) == b"complete"
    with pytest.raises(ExecutionPolicyError, match="read limit"):
        workspace.read_bytes("nested/result.txt", max_bytes=2)


def test_execution_uses_minimal_env_and_content_addressed_full_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    secret = "must-not-reach-user-code"
    monkeypatch.setenv("ARI_UNDECLARED_SECRET", secret)
    code = (
        "import json,os;"
        "print(json.dumps({'secret':os.getenv('ARI_UNDECLARED_SECRET'),"
        "'declared':os.getenv('EXPERIMENT_MODE')}));"
        "print('x'*10000)"
    )
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=[os.sys.executable, "-c", code],
        environment={"EXPERIMENT_MODE": "validation"},
        request_id="minimal-env",
    )
    result = execute_local(request)

    assert result.status == "completed"
    assert result.exit_code == 0
    assert result.stdout_truncated is True
    assert len(result.stdout_preview) <= 4_000
    assert secret not in result.stdout_preview
    assert "validation" in result.stdout_preview
    assert "ARI_UNDECLARED_SECRET" not in result.environment_names
    assert result.execution_identity == request.execution_identity
    assert result.limit_report.substrate == "posix-kernel"
    assert result.network_report == "inherited"
    assert "output" in result.limit_report.enforced
    for artifact in result.artifacts:
        path = Path(workspace.root) / artifact.relative_path
        assert path.is_file()
        assert _digest(path) == artifact.digest
        assert path.stat().st_size == artifact.size_bytes
    stdout = next(item for item in result.artifacts if item.logical_role == "stdout")
    assert json.loads(
        (Path(workspace.root) / stdout.relative_path)
        .read_text(encoding="utf-8")
        .splitlines()[0]
    ) == {"secret": None, "declared": "validation"}


def test_timeout_reaps_process_group_and_retry_identity_is_stable(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    code = (
        "import pathlib,subprocess,time;"
        "p=subprocess.Popen(['sleep','60']);"
        "pathlib.Path('child.pid').write_text(str(p.pid));"
        "time.sleep(60)"
    )
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=[os.sys.executable, "-c", code],
        timeout_seconds=0.3,
        request_id="timeout-reap",
    )
    first = execute_local(request)
    second = execute_local(request)

    assert first.status == second.status == "timed_out"
    assert first.execution_identity == second.execution_identity
    assert first.attempt_id != second.attempt_id
    child_pid = int((Path(workspace.root) / "child.pid").read_text(encoding="utf-8"))
    for _ in range(50):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("timed-out grandchild process remained alive")


def test_execution_rejects_secret_env_and_unprovable_network_deny(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    with pytest.raises(ValidationError, match="unsafe entry"):
        ExecutionRequestV1(
            workspace=workspace,
            argv=["true"],
            environment={"API_TOKEN": "secret-value"},
        )
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=["true"],
        network="deny",
    )
    with pytest.raises(ExecutionPolicyError, match="cannot prove network denial"):
        execute_local(request)
    isolated = execute_local(request, network_isolation_verified=True)
    assert isolated.network_report == "isolated"


def test_execution_cancellation_reaps_process_group(tmp_path: Path) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    cancelled = threading.Event()
    cancelled.set()
    result = execute_local(
        ExecutionRequestV1(
            workspace=workspace,
            argv=[os.sys.executable, "-c", "import time; time.sleep(60)"],
        ),
        cancel_event=cancelled,
    )
    assert result.status == "cancelled"
    assert result.exit_code is None


def test_declared_script_is_digest_checked_and_executed_from_snapshot(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    source = Path(workspace.root) / "script.py"
    source.write_text(
        "from pathlib import Path\n"
        "Path('script.py').write_text(\"print('mutated')\")\n"
        "print('snapshot-ran')\n",
        encoding="utf-8",
    )
    digest = workspace.file_digest("script.py")
    request = ExecutionRequestV1(
        workspace=workspace,
        argv=[os.sys.executable, "script.py"],
        input_digests={"script.py": digest},
    )
    result = execute_local(request)
    assert result.status == "completed"
    assert result.stdout_preview == "snapshot-ran\n"
    assert result.input_bindings == {"script.py": "immutable-snapshot"}
    assert source.read_text(encoding="utf-8") == "print('mutated')"

    source.write_text("print('changed before launch')", encoding="utf-8")
    with pytest.raises(ExecutionPolicyError, match="digest changed"):
        execute_local(request)


def test_dirfd_read_rejects_parent_swap_to_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WorkspaceRefV1(root=str(tmp_path / "workspace"))
    nested = Path(workspace.root) / "nested"
    nested.mkdir()
    (nested / "value.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "value.txt").write_text("outside-secret", encoding="utf-8")

    import ari.execution as implementation

    original_open = implementation.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "nested" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            nested.rename(Path(workspace.root) / "nested-original")
            nested.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(implementation.os, "open", racing_open)
    with pytest.raises(ExecutionPolicyError, match="changed or contains a symlink"):
        workspace.read_bytes("nested/value.txt", max_bytes=100)


def test_measurement_contract_requires_disjoint_typed_records() -> None:
    measurement = MeasurementRecordV1(
        metric_id="latency",
        value=1.25,
        unit="ms",
        unit_status="declared",
        provenance="benchmark",
        parameters={"threads": 4},
    )
    value = MeasurementSetV1(
        parameters={"threads": 4},
        measurements=[measurement],
        predictions={"roofline": 10.0},
    )
    assert value.schema_version == "ari.measurement-set/v1"
    with pytest.raises(ValidationError, match="names overlap"):
        MeasurementSetV1(
            parameters={"latency": 4},
            measurements=[measurement],
        )
    with pytest.raises(ValidationError, match="status differs"):
        MeasurementRecordV1(
            metric_id="latency",
            value=1.25,
            unit=None,
            unit_status="declared",
        )
    with pytest.raises(ValidationError, match="parameters differ"):
        MeasurementSetV1(
            parameters={"threads": 8},
            measurements=[measurement],
        )


def test_measurement_document_cross_checks_typed_projection_and_migrates_v1() -> None:
    canonical = MeasurementSetV1(
        parameters={"threads": 4},
        measurements=[
            MeasurementRecordV1(
                metric_id="latency",
                value=1.25,
                unit="ms",
                unit_status="declared",
                provenance="benchmark",
                parameters={"threads": 4},
            )
        ],
    )
    document = {
        "schema_version": "1.0",
        "typed_schema_version": "ari.measurement-set/v1",
        "measurement_set": canonical.model_dump(mode="json"),
        "params": {"threads": 4},
        "measurements": {"latency": 1.25},
        "predictions": {},
        "scores": {},
        "measurement_records": [
            item.model_dump(mode="json") for item in canonical.measurements
        ],
        "_provenance": {"latency": "benchmark"},
    }
    assert parse_measurement_document(document) == canonical
    document["measurements"] = {"latency": 99.0}
    with pytest.raises(MeasurementDocumentError, match="projection differs"):
        parse_measurement_document(document)

    downgraded = dict(document)
    downgraded.pop("typed_schema_version")
    with pytest.raises(MeasurementDocumentError, match="require typed_schema_version"):
        parse_measurement_document(downgraded)

    unsupported_projection = dict(document)
    unsupported_projection["schema_version"] = "2.0"
    with pytest.raises(MeasurementDocumentError, match="projection is not v1"):
        parse_measurement_document(unsupported_projection)

    legacy = parse_measurement_document(
        {
            "schema_version": "1.0",
            "params": {"threads": 4},
            "measurements": {"latency": 2.0},
            "predictions": {},
            "scores": {},
        }
    )
    assert legacy.measurements[0].unit_status == "missing"
    assert legacy.measurements[0].execution_status == "unreported"
    with pytest.raises(ValidationError, match="finite number"):
        MeasurementRecordV1(
            metric_id="latency",
            value=float("nan"),
            unit="ms",
            unit_status="declared",
        )
