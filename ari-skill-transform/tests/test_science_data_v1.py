from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from ari.public.science_data import parse_science_data, science_data_projection

import server


def _checkpoint(tmp_path: Path) -> Path:
    run_id = "science-v1"
    checkpoint = tmp_path / "checkpoints" / run_id
    work = tmp_path / "experiments" / run_id / "node-1"
    checkpoint.mkdir(parents=True)
    work.mkdir(parents=True)
    tree = checkpoint / "tree.json"
    tree.write_text(
        json.dumps(
            [
                {
                    "id": "node-1",
                    "label": "validation",
                    "has_real_data": True,
                    "metrics": {"latency": 1.25},
                }
            ]
        )
    )
    (work / "node_report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "node_id": "node-1",
                "status": "success",
                "executor": "local",
                "hostname": "fixture",
                "cpu_info": {"model": "fixture-cpu", "arch": "x86_64"},
                "files_changed": {
                    "added": [],
                    "modified": [],
                    "deleted": [],
                    "inherited_unchanged": [],
                },
                "metrics": {"latency": 1.25},
                "self_assessment": {
                    "succeeded": True,
                    "headline": "ok",
                    "concerns": [],
                },
                "artifacts": [],
            }
        )
    )
    record = {
        "metric_id": "latency",
        "value": 1.25,
        "unit": "ms",
        "unit_status": "declared",
        "provenance": "benchmark",
        "parameters": {"threads": 4},
        "artifact_digests": [],
        "execution_identity": "sha256:" + "b" * 64,
        "execution_attempt_id": "attempt-1",
        "execution_status": "completed",
        "exit_code": 0,
    }
    document = {
        "schema_version": "1.0",
        "typed_schema_version": "ari.measurement-set/v1",
        "measurement_set": {
            "schema_version": "ari.measurement-set/v1",
            "parameters": {"threads": 4},
            "measurements": [record],
            "predictions": {},
            "scores": {},
            "artifact_digests": [],
        },
        "params": {"threads": 4},
        "measurements": {"latency": 1.25},
        "measurement_records": [record],
        "predictions": {},
        "scores": {},
        "_provenance": {"latency": "benchmark"},
    }
    (work / "results.json").write_text(json.dumps(document))
    return tree


def _response(context: dict, overview: dict | None = None):
    class Response:
        choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Message",
                        (),
                        {
                            "content": json.dumps(
                                {
                                    "evaluation_protocol": {"domain": "fixture"},
                                    "experiment_context": context,
                                    **(
                                        {"implementation_overview": overview}
                                        if overview is not None
                                        else {}
                                    ),
                                }
                            )
                        },
                    )()
                },
            )()
        ]

    return Response()


def test_llm_numbers_never_mutate_raw_or_derived(monkeypatch, tmp_path: Path):
    tree = _checkpoint(tmp_path)

    async def fake(**_kwargs):
        return _response({"latency": 999999, "finding": "model interpretation"})

    monkeypatch.setattr(server.litellm, "acompletion", fake)
    value = asyncio.run(
        server.nodes_to_science_data(str(tree), primary_metric="latency")
    )
    parsed = parse_science_data(value)
    projection = science_data_projection(parsed)
    assert projection["configurations"][0]["measurements"] == {"latency": 1.25}
    assert parsed.interpretation.experiment_context["latency"] == 999999
    assert parsed.interpretation.claim_eligible is False
    assert parsed.derived.metric_summaries[0].best_value == 1.25


def test_annotation_revision_preserves_deterministic_digest(
    monkeypatch, tmp_path: Path
):
    tree = _checkpoint(tmp_path)
    responses = iter([_response({"story": "A"}), _response({"story": "B"})])

    async def fake(**_kwargs):
        return next(responses)

    monkeypatch.setattr(server.litellm, "acompletion", fake)
    first = parse_science_data(asyncio.run(server.nodes_to_science_data(str(tree))))
    second = parse_science_data(asyncio.run(server.nodes_to_science_data(str(tree))))
    assert first.deterministic_digest == second.deterministic_digest
    assert first.science_data_digest != second.science_data_digest


def test_raw_model_response_is_content_addressed(monkeypatch, tmp_path: Path):
    tree = _checkpoint(tmp_path)
    response = _response({"finding": "grounded"})
    raw = response.choices[0].message.content.encode()

    async def fake(**_kwargs):
        return response

    monkeypatch.setattr(server.litellm, "acompletion", fake)
    parsed = parse_science_data(asyncio.run(server.nodes_to_science_data(str(tree))))
    artifact = parsed.interpretation.raw_response_artifact
    assert artifact is not None
    assert artifact.digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert (tmp_path / artifact.relative_path).read_bytes() == raw


def test_tampered_report_is_not_replaced_by_trace_scan(monkeypatch, tmp_path: Path):
    tree = _checkpoint(tmp_path)
    report = tmp_path / "experiments" / "science-v1" / "node-1" / "node_report.json"
    value = json.loads(report.read_text())
    value["node_id"] = "other-node"
    report.write_text(json.dumps(value))
    called = False

    async def fake(**_kwargs):
        nonlocal called
        called = True
        return _response({})

    monkeypatch.setattr(server.litellm, "acompletion", fake)
    parsed = parse_science_data(asyncio.run(server.nodes_to_science_data(str(tree))))
    assert called is False
    assert parsed.raw.node_report_status == "missing"
    assert parsed.interpretation.error_kind == "node-report-unavailable"
