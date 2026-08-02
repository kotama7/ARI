from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ari_skill_orchestrator.contracts import (
    ArtifactRefV1,
    RunRequestV1,
    bytes_digest,
)


ROOT = Path(__file__).resolve().parents[1]


def test_request_is_digest_bound_and_tamper_fails() -> None:
    request = RunRequestV1.from_parameters(
        experiment_md="# experiment\nmeasure throughput",
        idempotency_key="client:attempt-1",
    )
    assert request.experiment_digest == bytes_digest(request.experiment_md.encode())
    assert request.request_digest.startswith("sha256:")
    tampered = request.model_dump(mode="json")
    tampered["max_nodes"] = 99
    with pytest.raises(ValidationError, match="request_digest"):
        RunRequestV1.model_validate(tampered)


@pytest.mark.parametrize(
    "updates",
    [
        {"experiment_md": ""},
        {"idempotency_key": "../../escape"},
        {"max_nodes": 11, "max_total_nodes": 10},
        {"estimated_cost_usd": 2.0, "max_cost_usd": 1.0},
        {"max_recursion_depth": -1},
    ],
)
def test_request_rejects_invalid_policy(updates: dict) -> None:
    values = {"experiment_md": "science", "idempotency_key": "valid-key"}
    values.update(updates)
    with pytest.raises(ValidationError):
        RunRequestV1.from_parameters(**values)


def test_artifact_identity_must_equal_digest() -> None:
    with pytest.raises(ValidationError, match="artifact_id"):
        ArtifactRefV1(
            run_id="run_20260802T120000000000Z_0123456789abcdef",
            artifact_id="sha256:" + "a" * 64,
            digest="sha256:" + "b" * 64,
            role="log",
            media_type="text/plain",
            size_bytes=1,
        )


def test_checked_in_schemas_match_models() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_contracts.py")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for path in (ROOT / "schemas").glob("*.schema.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["type"] == "object"
