"""On-disk identity and scientific-evidence verification for OpenROAD profiles."""

from __future__ import annotations

import json
import math
import platform
import re
from pathlib import Path
from typing import Any

import openroad_contracts
import openroad_identity
from models import sha256_digest
from openroad_contracts import OpenRoadExperimentV1
from openroad_hpc import verify_openroad_hpc_files
from openroad_identity import OPENROAD_SUPPORT_MATRIX, _file_sha256
from providers import ProviderProtocolError, PythonStdioLauncherV1


_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def verify_openroad_provider_package(
    launcher: PythonStdioLauncherV1,
    pin: dict[str, Any],
) -> None:
    if Path(launcher.package_root).name != "openroad_mcp":
        raise ProviderProtocolError(
            "OpenROAD MCP package_root must be the exact openroad_mcp source package"
        )
    root, _executable, _entrypoint = launcher.resolve()
    if root.name != "openroad_mcp":
        raise ProviderProtocolError(
            "OpenROAD MCP package_root must be the exact openroad_mcp source package"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        size = path.stat().st_size
        total_bytes += size
        if len(files) >= 10_000 or total_bytes > 100_000_000:
            raise ProviderProtocolError("OpenROAD MCP package exceeds reviewed bounds")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "digest": _file_sha256(path),
            }
        )
    actual = sha256_digest(files)
    if actual != pin.get("package_tree_digest"):
        raise ProviderProtocolError(
            "OpenROAD MCP package tree drift: "
            f"expected {pin.get('package_tree_digest')}, got {actual}"
        )


def _load_evidence_fixture(path_text: str, digest: str) -> dict[str, Any]:
    path = Path(path_text)
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(
            "OpenROAD evidence fixture must be a regular non-symlink file"
        )
    if path.stat().st_size > 20_000_000:
        raise ProviderProtocolError("OpenROAD evidence fixture exceeds 20 MB")
    if _file_sha256(path) != digest:
        raise ProviderProtocolError("OpenROAD evidence fixture digest drifted")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"OpenROAD evidence fixture is invalid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProviderProtocolError("OpenROAD evidence fixture must be an object")
    return document


def _verify_golden_fixture(experiment: OpenRoadExperimentV1) -> None:
    assert experiment.golden_fixture_path is not None
    assert experiment.golden_fixture_digest is not None
    golden = _load_evidence_fixture(
        experiment.golden_fixture_path, experiment.golden_fixture_digest
    )
    expected = {
        "schema_version": "ari.openroad-golden/v1",
        "profile_id": experiment.profile_id,
        "metrics": [
            {
                "metric_id": metric.metric_id,
                "unit": metric.unit,
                "corner": metric.corner,
                "mode": metric.mode,
                "stage": metric.stage,
                "expected_min": metric.expected_min,
                "expected_max": metric.expected_max,
            }
            for metric in experiment.metrics
        ],
    }
    if golden != expected:
        raise ProviderProtocolError(
            "OpenROAD golden fixture does not exactly match metric contracts"
        )


def _validated_replay_metrics(
    experiment: OpenRoadExperimentV1,
) -> list[dict[str, Any]]:
    assert experiment.replay_fixture_path is not None
    assert experiment.replay_fixture_digest is not None
    replay = _load_evidence_fixture(
        experiment.replay_fixture_path, experiment.replay_fixture_digest
    )
    expected_keys = {
        "schema_version",
        "profile_id",
        "experiment_digest",
        "arguments",
        "result",
    }
    if set(replay) != expected_keys or replay.get("schema_version") != (
        "ari.openroad-replay-fixture/v1"
    ):
        raise ProviderProtocolError("OpenROAD replay fixture contract is invalid")
    if (
        replay.get("profile_id") != experiment.profile_id
        or replay.get("experiment_digest") != experiment.experiment_digest
    ):
        raise ProviderProtocolError(
            "OpenROAD replay fixture is bound to a different experiment"
        )
    arguments = replay.get("arguments")
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"request_id"}
        or not isinstance(arguments.get("request_id"), str)
        or not _REQUEST_ID_RE.fullmatch(arguments["request_id"])
    ):
        raise ProviderProtocolError("OpenROAD replay arguments are invalid")
    result = replay.get("result")
    if not isinstance(result, dict) or set(result) != {
        "status",
        "experiment_digest",
        "metrics",
    }:
        raise ProviderProtocolError("OpenROAD replay result contract is invalid")
    if (
        result.get("status") != "completed"
        or result.get("experiment_digest") != experiment.experiment_digest
        or not isinstance(result.get("metrics"), list)
    ):
        raise ProviderProtocolError("OpenROAD replay result identity is invalid")
    return result["metrics"]


def _verify_replay_metric_contracts(
    experiment: OpenRoadExperimentV1, items: list[dict[str, Any]]
) -> None:
    expected = {metric.metric_id: metric for metric in experiment.metrics}
    actual: dict[str, dict[str, Any]] = {}
    metric_keys = {"metric_id", "value", "unit", "corner", "mode", "stage"}
    for item in items:
        if not isinstance(item, dict) or set(item) != metric_keys:
            raise ProviderProtocolError("OpenROAD replay metric is invalid")
        metric_id = item.get("metric_id")
        if not isinstance(metric_id, str) or metric_id in actual:
            raise ProviderProtocolError(
                "OpenROAD replay metric identifiers are invalid"
            )
        actual[metric_id] = item
    if set(actual) != set(expected):
        raise ProviderProtocolError("OpenROAD replay metrics are incomplete")
    for metric_id, contract in expected.items():
        item = actual[metric_id]
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProviderProtocolError("OpenROAD replay metric is not numeric")
        numeric = float(value)
        identity_matches = (
            item["unit"] == contract.unit
            and item["corner"] == contract.corner
            and item["mode"] == contract.mode
            and item["stage"] == contract.stage
        )
        in_range = (
            (contract.expected_min is None or numeric >= contract.expected_min)
            and (contract.expected_max is None or numeric <= contract.expected_max)
        )
        if not math.isfinite(numeric) or not identity_matches or not in_range:
            raise ProviderProtocolError(
                f"OpenROAD replay metric {metric_id!r} violates its contract"
            )


def _verify_openroad_evidence_fixtures(experiment: OpenRoadExperimentV1) -> None:
    if experiment.golden_fixture_path is not None:
        _verify_golden_fixture(experiment)
    if experiment.replay_fixture_path is not None:
        _verify_replay_metric_contracts(
            experiment, _validated_replay_metrics(experiment)
        )


def verify_openroad_experiment_files(experiment: OpenRoadExperimentV1) -> None:
    executable = Path(experiment.toolchain.executable_path)
    if experiment.execution.backend == "local-mcp":
        if executable.is_symlink() or not executable.is_file():
            raise ProviderProtocolError(
                "OpenROAD executable must be a regular non-symlink"
            )
        if _file_sha256(executable) != experiment.toolchain.executable_digest:
            raise ProviderProtocolError("OpenROAD executable digest drifted")
        if experiment.toolchain.architecture != platform.machine():
            raise ProviderProtocolError(
                "OpenROAD architecture mismatch: "
                f"expected {experiment.toolchain.architecture}, got {platform.machine()}"
            )
    else:
        verify_openroad_hpc_files(experiment.execution)

    root = Path(experiment.workspace.source_root)
    if root.is_symlink() or not root.is_dir():
        raise ProviderProtocolError(
            "OpenROAD source workspace must be a regular non-symlink directory"
        )
    declared = {
        artifact.relative_path: artifact
        for artifact in experiment.workspace.input_artifacts
    }
    actual_paths: set[str] = set()
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ProviderProtocolError(
                f"OpenROAD source workspace contains a symlink: {path}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        actual_paths.add(relative)
        artifact = declared.get(relative)
        if artifact is None:
            raise ProviderProtocolError(
                f"OpenROAD source workspace contains undeclared input {relative!r}"
            )
        total_bytes += path.stat().st_size
        if total_bytes > 2_000_000_000:
            raise ProviderProtocolError("OpenROAD source inputs exceed 2 GB")
        if _file_sha256(path) != artifact.digest:
            raise ProviderProtocolError(
                f"OpenROAD input artifact digest drifted: {relative}"
            )
    missing = sorted(set(declared) - actual_paths)
    if missing:
        raise ProviderProtocolError(f"OpenROAD input artifacts are missing: {missing}")
    _verify_openroad_evidence_fixtures(experiment)


def openroad_contracts_digest() -> str:
    return sha256_digest(
        {
            "contracts_source": _file_sha256(
                Path(openroad_contracts.__file__).resolve()
            ),
            "identity_source": _file_sha256(Path(openroad_identity.__file__).resolve()),
            "verification_source": _file_sha256(Path(__file__).resolve()),
            "support_matrix": _file_sha256(OPENROAD_SUPPORT_MATRIX),
        }
    )


__all__ = [
    "openroad_contracts_digest",
    "verify_openroad_experiment_files",
    "verify_openroad_provider_package",
]
