"""On-disk circuit, evidence, and normalized-count verification for Qiskit."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import qiskit_contracts
import qiskit_identity
from models import sha256_digest
from providers import ProviderProtocolError
from qiskit_contracts import QiskitExperimentV1
from qiskit_identity import QISKIT_SUPPORT_MATRIX, _file_sha256


_REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def validate_qiskit_counts(
    experiment: QiskitExperimentV1,
    counts: dict[str, Any],
) -> dict[str, int]:
    """Return canonical counts only when every statistical contract holds."""

    normalized: dict[str, int] = {}
    for bitstring, raw in counts.items():
        if (
            not isinstance(bitstring, str)
            or not re.fullmatch(r"[01]+", bitstring)
            or len(bitstring) != experiment.circuit.num_clbits
            or isinstance(raw, bool)
            or not isinstance(raw, int)
            or raw < 0
        ):
            raise ProviderProtocolError("Qiskit result contains invalid counts")
        normalized[bitstring] = raw
    if sum(normalized.values()) != experiment.shots:
        raise ProviderProtocolError("Qiskit result shot count differs from the profile")
    expected = {item.bitstring: item for item in experiment.expected_outcomes}
    for bitstring, contract in expected.items():
        probability = normalized.get(bitstring, 0) / experiment.shots
        if not contract.probability_min <= probability <= contract.probability_max:
            raise ProviderProtocolError(
                f"Qiskit outcome {bitstring!r} is outside its probability range"
            )
    unlisted = sum(
        count for bitstring, count in normalized.items() if bitstring not in expected
    )
    if unlisted / experiment.shots > experiment.max_unlisted_probability:
        raise ProviderProtocolError("Qiskit unlisted outcome mass exceeds its limit")
    return dict(sorted(normalized.items()))


def _load_fixture(path_text: str, digest: str) -> dict[str, Any]:
    path = Path(path_text)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise ProviderProtocolError("Qiskit evidence fixture is missing or unsafe")
    if _file_sha256(path) != digest:
        raise ProviderProtocolError("Qiskit evidence fixture digest drifted")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"Qiskit evidence fixture is invalid: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ProviderProtocolError("Qiskit evidence fixture must be an object")
    return value


def _verify_golden_fixture(experiment: QiskitExperimentV1) -> None:
    assert experiment.golden_fixture_path is not None
    assert experiment.golden_fixture_digest is not None
    value = _load_fixture(
        experiment.golden_fixture_path, experiment.golden_fixture_digest
    )
    if (
        set(value)
        != {
            "schema_version",
            "profile_id",
            "experiment_digest",
            "counts",
        }
        or value.get("schema_version") != "ari.qiskit-golden/v1"
    ):
        raise ProviderProtocolError("Qiskit golden fixture shape is invalid")
    if (
        value.get("profile_id") != experiment.profile_id
        or value.get("experiment_digest") != experiment.experiment_digest
    ):
        raise ProviderProtocolError("Qiskit golden fixture identity differs")
    counts = value.get("counts")
    if not isinstance(counts, dict):
        raise ProviderProtocolError("Qiskit golden fixture omitted counts")
    validate_qiskit_counts(experiment, counts)


def _verify_replay_fixture(experiment: QiskitExperimentV1) -> None:
    assert experiment.replay_fixture_path is not None
    assert experiment.replay_fixture_digest is not None
    value = _load_fixture(
        experiment.replay_fixture_path, experiment.replay_fixture_digest
    )
    if set(value) != {"schema_version", "profile_id", "arguments", "result"} or (
        value.get("schema_version") != "ari.qiskit-replay-fixture/v1"
        or value.get("profile_id") != experiment.profile_id
    ):
        raise ProviderProtocolError("Qiskit replay fixture identity is invalid")
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"request_id"}
        or not isinstance(arguments.get("request_id"), str)
        or not _REQUEST_ID_RE.fullmatch(arguments["request_id"])
    ):
        raise ProviderProtocolError("Qiskit replay fixture arguments are invalid")
    result = value.get("result")
    if not isinstance(result, dict) or set(result) != {
        "status",
        "experiment_digest",
        "method_digest",
        "counts",
        "shots",
    }:
        raise ProviderProtocolError("Qiskit replay result shape is invalid")
    if (
        result.get("status") != "completed"
        or result.get("experiment_digest") != experiment.experiment_digest
        or result.get("method_digest") != experiment.method_digest
        or result.get("shots") != experiment.shots
        or not isinstance(result.get("counts"), dict)
    ):
        raise ProviderProtocolError("Qiskit replay result identity is invalid")
    validate_qiskit_counts(experiment, result["counts"])


def verify_qiskit_experiment_files(experiment: QiskitExperimentV1) -> None:
    path = Path(experiment.circuit.qpy_path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size < 10
        or path.stat().st_size > 100_000_000
    ):
        raise ProviderProtocolError("Qiskit QPY circuit is missing or unsafe")
    if _file_sha256(path) != experiment.circuit.qpy_digest:
        raise ProviderProtocolError("Qiskit QPY circuit digest drifted")
    try:
        header = path.read_bytes()[:10]
    except OSError as exc:
        raise ProviderProtocolError(f"cannot read Qiskit QPY header: {exc}") from exc
    if header[:6] != b"QISKIT" or header[6] != experiment.circuit.qpy_version:
        raise ProviderProtocolError("Qiskit QPY format version differs from profile")
    qiskit_version = tuple(
        int(item) for item in experiment.software.qiskit_version.split(".")
    )
    if tuple(header[7:10]) != qiskit_version:
        raise ProviderProtocolError(
            "QPY producer version differs from Qiskit software pin"
        )
    if experiment.golden_fixture_path is not None:
        _verify_golden_fixture(experiment)
    if experiment.replay_fixture_path is not None:
        _verify_replay_fixture(experiment)


def qiskit_contracts_digest() -> str:
    return sha256_digest(
        {
            "contracts_source": _file_sha256(Path(qiskit_contracts.__file__).resolve()),
            "identity": qiskit_identity.qiskit_identity_digest(),
            "verification_source": _file_sha256(Path(__file__).resolve()),
            "support_matrix": _file_sha256(QISKIT_SUPPORT_MATRIX),
        }
    )


__all__ = [
    "qiskit_contracts_digest",
    "validate_qiskit_counts",
    "verify_qiskit_experiment_files",
]
