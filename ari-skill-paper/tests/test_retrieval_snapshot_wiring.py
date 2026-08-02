"""Paper references are resolved from verified snapshot refs, not inline payloads."""

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

from ari.public.research_contract import (  # noqa: E402
    ResearchArtifactRefV1,
    ResearchContractError,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
)
from src import server  # noqa: E402


def _recorded_result(tmp_path: Path) -> tuple[dict, Path]:
    cassette = b'{"fixture":true}\n'
    cassette_path = tmp_path / "retrieval_cassettes" / "source.json"
    cassette_path.parent.mkdir()
    cassette_path.write_bytes(cassette)
    artifact = ResearchArtifactRefV1(
        logical_name="retrieval_cassettes/source.json",
        digest="sha256:" + hashlib.sha256(cassette).hexdigest(),
        media_type="application/json",
        role="raw-provider-cassette",
    )
    record = RetrievalRecordV1(
        canonical_id="s2:verified",
        provider="semantic-scholar",
        provider_record_id="verified",
        provider_version="graph-v1",
        query="verified literature",
        retrieved_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        title="Verified source title",
        abstract="A source-backed result.",
        authors=("Ada Example",),
        year=2026,
        source_url="https://example.org/paper",
        payload_digest=canonical_digest({"paperId": "verified"}),
    )
    snapshot = SurveySnapshotV1.create(
        mode="record",
        provider="semantic-scholar",
        provider_version="graph-v1",
        query="verified literature",
        retrieved_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        byte_reproducible=False,
        records=(record,),
        artifacts=(artifact,),
    )
    ref = (
        "retrieval_snapshots/"
        f"{snapshot.snapshot_digest.removeprefix('sha256:')}.json"
    )
    snapshot_path = tmp_path / ref
    snapshot_path.parent.mkdir()
    snapshot_path.write_text(json.dumps(snapshot.model_dump(mode="json")))
    result = {
        "schema_version": "ari.retrieval-result/v1",
        "snapshot_ref": ref,
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "papers": [{"title": "FORGED INLINE TITLE"}],
    }
    return result, cassette_path


def test_paper_uses_verified_snapshot_instead_of_inline_records(tmp_path, monkeypatch):
    result, _ = _recorded_result(tmp_path)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))

    resolved = server._resolve_retrieval_refs(json.dumps(result))
    bibtex, keys = server._build_bib_content(result)

    assert resolved["papers"][0]["title"] == "Verified source title"
    assert "FORGED INLINE TITLE" not in bibtex
    assert "Verified source title" in bibtex
    assert keys[0][1] == "Verified source title"


def test_paper_rejects_tampered_snapshot_artifact(tmp_path, monkeypatch):
    result, cassette_path = _recorded_result(tmp_path)
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    cassette_path.write_bytes(cassette_path.read_bytes() + b" ")

    with pytest.raises(ResearchContractError, match="artifact digest mismatch"):
        server._resolve_retrieval_refs(result)


def test_typed_live_result_cannot_downgrade_to_inline_papers():
    with pytest.raises(ValueError, match="recorded retrieval snapshot_ref"):
        server._resolve_retrieval_refs(
            {
                "schema_version": "ari.retrieval-result/v1",
                "snapshot_ref": None,
                "papers": [{"title": "unrecorded"}],
            }
        )
