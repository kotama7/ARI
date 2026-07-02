"""Unit tests for CheckpointArtifactStore (subtask 010).

Minimal by-logical-name artefact access over the flat checkpoint layout. The
type-sniffing output writer stays owned by ``ari.pipeline.stages.OutputSink``
(subtask 012); this store performs plain, unambiguous writes only.
"""

from __future__ import annotations

import pytest

from ari.artifact_store import CheckpointArtifactStore
from ari.protocols.stores import ArtifactStore


def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ArtifactStore()  # abstract


def test_is_artifact_store_subclass(tmp_path):
    assert isinstance(CheckpointArtifactStore(tmp_path), ArtifactStore)


def test_put_text_bytes_and_path(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    store = CheckpointArtifactStore(ckpt)

    p = store.put("science_data.json", "{}")
    assert p == ckpt / "science_data.json"
    assert p.read_text() == "{}"
    assert store.exists("science_data.json")
    assert store.get("science_data.json") == ckpt / "science_data.json"

    store.put("full_paper.pdf", b"%PDF-1.4")
    assert (ckpt / "full_paper.pdf").read_bytes() == b"%PDF-1.4"

    src = tmp_path / "src.pdf"
    src.write_bytes(b"copied-bytes")
    store.put("out.pdf", src)
    assert (ckpt / "out.pdf").read_bytes() == b"copied-bytes"


def test_put_creates_subdirs(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    store = CheckpointArtifactStore(ckpt)
    store.put("evaluation/report.json", "{}")
    assert (ckpt / "evaluation" / "report.json").exists()


def test_exists_and_get_for_missing(tmp_path):
    store = CheckpointArtifactStore(tmp_path)
    assert store.exists("nope.tex") is False
    assert store.get("nope.tex") == tmp_path / "nope.tex"  # path even if absent


def test_list_filtering(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    store = CheckpointArtifactStore(ckpt)
    store.put("full_paper.tex", "x")
    store.put("a.pdf", b"1")
    store.put("fig_1.png", b"2")

    assert store.list(".pdf") == [ckpt / "a.pdf"]
    assert store.list("fig_*") == [ckpt / "fig_1.png"]

    all_files = store.list()
    assert (ckpt / "full_paper.tex") in all_files
    assert len(all_files) == 3


def test_list_empty_dir(tmp_path):
    store = CheckpointArtifactStore(tmp_path / "does-not-exist")
    assert store.list() == []
