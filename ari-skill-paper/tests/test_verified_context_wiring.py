"""Wiring test: write_paper_iterative injects the verified-context grounded block
into the system prompt (handoff: 'secure the flow' — consumption side).

Mirrors production by putting ari-core on sys.path (mcp.client injects it onto
the skill subprocess PYTHONPATH) so render_grounded_block is importable.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ARI_CORE = str(Path(__file__).resolve().parents[2] / "ari-core")
if _ARI_CORE not in sys.path:
    sys.path.insert(0, _ARI_CORE)

from unittest.mock import patch  # noqa: E402

from ari.public.execution import MeasurementRecordV1  # noqa: E402
from ari.public.figures import (  # noqa: E402
    FigureArtifactV1,
    FigureAxisV1,
    FigureBatchV1,
    FigureEnvironmentV1,
    FigureManifestV1,
    FigureSourceV1,
    FigureSpecV1,
    canonical_figure_digest,
)
from ari.public.research_contract import (  # noqa: E402
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
)
from ari.public.science_data import (  # noqa: E402
    ScienceArtifactRefV1,
    ScienceConfigurationV1,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
)
from src import server  # noqa: E402


SHA = "sha256:" + "1" * 64


def _native_inputs(root: Path, verified_context: str = "") -> dict[str, str]:
    tree = ScienceArtifactRefV1(
        relative_path="tree.json",
        digest=SHA,
        media_type="application/json",
        role="experiment-tree",
        size_bytes=1,
    )
    result = ScienceArtifactRefV1(
        relative_path="results.json",
        digest="sha256:" + "2" * 64,
        media_type="application/json",
        role="measurement-set",
        size_bytes=1,
    )
    measurement = MeasurementRecordV1(
        metric_id="throughput",
        value=150.0,
        unit="GFLOP/s",
        unit_status="declared",
        execution_identity="sha256:" + "3" * 64,
        execution_attempt_id="attempt-1",
        execution_status="completed",
        exit_code=0,
    )
    raw = ScienceRawV1.create(
        tree_artifact=tree,
        configurations=(
            ScienceConfigurationV1(
                config_id="cfg-1",
                run_id="run",
                node_id="node-1",
                rank=1,
                source_kind="typed-measurement",
                claim_eligible=True,
                measurements={"throughput": 150.0},
                measurement_records=(measurement,),
                source_artifacts=(tree, result),
            ),
        ),
        node_report_status="missing",
        measurement_status="complete",
    )
    science = ScienceDataV1.create(
        run_id="run",
        raw=raw,
        derived=ScienceDerivedV1.create(
            formula_registry_digest=formula_registry_digest()
        ),
        interpretation=ScienceInterpretationV1.create(
            status="unavailable",
            input_raw_digest=raw.raw_digest,
            error_kind="fixture",
            error_message="fixture",
        ),
        provenance=ScienceProvenanceV1(
            producer_tool_ref="transform-skill/nodes-to-science-data@v1",
            producer_version="1",
            input_artifacts=(tree, result),
        ),
    )
    (root / "science_data.json").write_text(json.dumps(science.model_dump(mode="json")))

    data = {"configuration": ["cfg-1"], "throughput": [150.0]}
    spec = FigureSpecV1.create(
        figure_id="throughput",
        chart_type="bar",
        data=data,
        source=FigureSourceV1(
            artifact_digest=science.science_data_digest,
            data_digest=canonical_figure_digest(data),
            record_ids=("cfg-1:throughput",),
        ),
        x_field="configuration",
        y_field="throughput",
        x_axis=FigureAxisV1(label="Configuration", unit="1"),
        y_axis=FigureAxisV1(label="Throughput", unit="GFLOP/s"),
        value_unit="GFLOP/s",
        caption="Measured throughput for the admitted configuration.",
    )
    roles = (
        ("source-data", "figures/source.json", "application/json"),
        ("spec", "figures/spec.json", "application/json"),
        ("png", "figures/throughput.png", "image/png"),
        ("pdf", "figures/throughput.pdf", "application/pdf"),
    )
    artifact_payloads = {
        "figures/source.json": b'{"throughput":150.0}',
        "figures/spec.json": json.dumps(
            spec.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "figures/throughput.png": b"fixture-png",
        "figures/throughput.pdf": b"fixture-pdf",
    }
    for relative_path, payload in artifact_payloads.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    manifest = FigureManifestV1.create(
        spec=spec,
        environment=FigureEnvironmentV1.create(
            renderer_version="fixture/v1",
            python_version="3.13",
            matplotlib_version="3.10",
            font_family="DejaVu Sans",
            font_digest="sha256:" + "4" * 64,
            platform="fixture",
        ),
        artifacts=tuple(
            FigureArtifactV1(
                role=role,
                relative_path=path,
                digest="sha256:" + hashlib.sha256(
                    artifact_payloads[path]
                ).hexdigest(),
                media_type=media_type,
                size_bytes=len(artifact_payloads[path]),
            )
            for role, path, media_type in roles
        ),
    )
    batch = FigureBatchV1.create(
        revision=0,
        manifests=(manifest,),
        figures={"throughput": "figures/throughput.pdf"},
        latex_snippets={
            "throughput": (
                "\\begin{figure}\\includegraphics{figures/throughput.pdf}"
                "\\caption{Measured throughput.}\\label{fig:throughput}"
                "\\end{figure}"
            )
        },
        figure_kinds={"throughput": "bar"},
    )
    (root / "figures_manifest.json").write_text(
        json.dumps(batch.model_dump(mode="json"))
    )

    record = RetrievalRecordV1(
        canonical_id="s2:fixture",
        provider="semantic-scholar",
        provider_record_id="fixture",
        provider_version="graph-v1",
        query="fixture query",
        retrieved_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        title="Verified fixture paper",
        abstract="Fixture abstract.",
        authors=("Ada Example",),
        year=2026,
        source_url="https://example.org/paper",
        payload_digest=canonical_digest({"paperId": "fixture"}),
    )
    snapshot = SurveySnapshotV1.create(
        mode="frozen",
        provider="semantic-scholar",
        provider_version="graph-v1",
        query="fixture query",
        byte_reproducible=True,
        records=(record,),
    )
    snapshot_ref = (
        f"retrieval_snapshots/{snapshot.snapshot_digest.removeprefix('sha256:')}.json"
    )
    snapshot_path = root / snapshot_ref
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(snapshot.model_dump(mode="json")))
    references = {
        "schema_version": "ari.retrieval-result/v1",
        "snapshot_ref": snapshot_ref,
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "survey_snapshot": snapshot.model_dump(mode="json"),
        "records": [record.model_dump(mode="json")],
    }
    (root / "related_refs.json").write_text(json.dumps(references))
    (root / "ear_manifest.json").write_text(
        json.dumps({"evidence_index_digest": "sha256:" + "9" * 64})
    )
    return {
        "workspace_root": str(root),
        "science_data_path": "science_data.json",
        "figures_manifest_path": "figures_manifest.json",
        "references_path": "related_refs.json",
        "ear_manifest_path": "ear_manifest.json",
        "rubric_id": "generic_conference",
        "verified_context_path": verified_context,
    }


@pytest.mark.asyncio
async def test_write_paper_injects_grounded_block(tmp_path):
    vc = tmp_path / "verified_context.json"
    vc.write_text(
        json.dumps(
            {
                "usable_for_claims": [
                    {
                        "text": "The kernel sustains 150 GFLOP/s on cpuX",
                        "repro_status": "rerun_passed",
                        "artifact_refs": [{"path": "ear/code/kernel.cu"}],
                    },
                ]
            }
        )
    )

    captured = {}

    class _Stop(Exception):
        pass

    async def _cap(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        raise _Stop("captured")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        with pytest.raises(Exception):
            await server.write_paper_iterative(
                **_native_inputs(tmp_path, "verified_context.json"),
                experiment_summary="some experiment context",
                venue="arxiv",
            )

    assert "messages" in captured, "litellm.acompletion was never reached"
    system_prompt = captured["messages"][0]["content"]
    assert "VERIFIED CONTEXT" in system_prompt
    assert "150 GFLOP/s" in system_prompt
    assert "rerun_passed" in system_prompt


@pytest.mark.asyncio
async def test_write_paper_no_verified_context_is_graceful(tmp_path):
    """Absent verified_context => no grounded block, no crash (default path)."""
    captured = {}

    async def _cap(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        raise RuntimeError("stop")

    with patch("src.server.litellm.acompletion", side_effect=_cap):
        with pytest.raises(Exception):
            await server.write_paper_iterative(
                **_native_inputs(tmp_path),
                experiment_summary="ctx",
                venue="arxiv",
            )
    system_prompt = captured["messages"][0]["content"]
    assert "VERIFIED CONTEXT" not in system_prompt


@pytest.mark.asyncio
async def test_whole_document_writer_uses_explicit_rubric_author_guidance(tmp_path):
    captured = {}

    async def _cap(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        raise RuntimeError("stop")

    arguments = _native_inputs(tmp_path)
    arguments["rubric_id"] = "sc"
    with patch("src.server.litellm.acompletion", side_effect=_cap):
        with pytest.raises(RuntimeError, match="stop"):
            await server.write_paper_iterative(
                **arguments,
                experiment_summary="ctx",
                venue="sc",
            )
    system_prompt = captured["messages"][0]["content"]
    assert "VENUE RUBRIC AUTHOR GUIDANCE" in system_prompt
    assert "scaling" in system_prompt.lower()
