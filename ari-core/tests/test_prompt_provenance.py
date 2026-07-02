"""Tests for subtask 044 — prompt-provenance recorder + run rollup.

Covers determinism (same body -> same 12-char hash, matching
``load_versioned``), that a record is written with the additive schema, the
no-op-without-checkpoint-dir behaviour, env-pin resolution, the rollup writer,
and that the new artifact filenames are registered as ARI metadata.
"""

from __future__ import annotations

import hashlib
import json

from ari.prompts import (
    FilesystemPromptLoader,
    build_prompt_versions_rollup,
    load_prompt_trace,
    record_prompt_use,
)
from ari.prompts._provenance import (
    PROMPT_TRACE_FILENAME,
    PROMPT_VERSIONS_FILENAME,
    hash12,
)


# ── determinism ────────────────────────────────────────────────────────────


def test_hash12_is_deterministic_and_matches_sha256_prefix():
    text = "You are a helpful assistant.\n{tool_desc}\n"
    assert hash12(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    assert len(hash12(text)) == 12
    # Same body -> identical hash across calls (machine-stable).
    assert hash12(text) == hash12(text)


def test_template_hash_matches_load_versioned():
    """The recorder's hash scheme is the exact one ``load_versioned`` uses."""
    loader = FilesystemPromptLoader()
    for key in ("agent/system", "orchestrator/bfts_select", "evaluator/peer_review"):
        text, thash = loader.load_versioned(key)
        assert thash == hash12(text)
        # load() and load_versioned()[0] return byte-identical text — the
        # load->load_versioned migration cannot perturb any rendered prompt.
        assert loader.load(key) == text


# ── record written + additive schema ───────────────────────────────────────


def test_record_writes_valid_jsonl_with_additive_schema(tmp_path):
    record_prompt_use(
        "orchestrator/bfts_select",
        "abc123def456",
        rendered_text="rendered body",
        model="gpt-4o-mini",
        node_id="node-1",
        phase="bfts",
        checkpoint_dir=tmp_path,
    )
    trace = tmp_path / PROMPT_TRACE_FILENAME
    assert trace.exists()
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["prompt_name"] == "orchestrator/bfts_select"
    assert rec["template_hash"] == "abc123def456"
    assert rec["rendered_prompt_hash"] == hash12("rendered body")
    assert rec["model"] == "gpt-4o-mini"
    assert rec["node_id"] == "node-1"
    assert rec["phase"] == "bfts"
    assert rec["source"] == "core"
    assert rec["timestamp"]  # non-empty metadata (never hashed)
    # Registry-derived fields are absent-as-null until subtask 038 lands.
    assert rec["prompt_version"] is None
    assert rec["prompt_registry_version"] is None


def test_rendered_hash_is_none_when_no_rendered_text(tmp_path):
    record_prompt_use("agent/system", "deadbeef0000", checkpoint_dir=tmp_path)
    rec = json.loads((tmp_path / PROMPT_TRACE_FILENAME).read_text().splitlines()[0])
    assert rec["rendered_prompt_hash"] is None


def test_appends_multiple_records(tmp_path):
    for i in range(3):
        record_prompt_use(f"k{i}", f"h{i}", checkpoint_dir=tmp_path)
    assert len(load_prompt_trace(tmp_path)) == 3


# ── no-op safety / env resolution ──────────────────────────────────────────


def test_noop_when_no_checkpoint_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    # No checkpoint_dir arg and no env pin -> silent no-op, no exception.
    assert record_prompt_use("agent/system", "abc") is None
    assert not (tmp_path / PROMPT_TRACE_FILENAME).exists()


def test_resolves_checkpoint_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    record_prompt_use("agent/system", "abc", rendered_text="x")
    assert (tmp_path / PROMPT_TRACE_FILENAME).exists()


def test_recorder_is_offline_no_llm_or_network_imports():
    """The recorder must perform zero LLM/network calls (P2)."""
    import ari.prompts._provenance as prov

    text = open(prov.__file__, encoding="utf-8").read()
    for forbidden in ("import litellm", "import requests", "import urllib",
                      "import socket", "import http"):
        assert forbidden not in text, forbidden


# ── rollup ─────────────────────────────────────────────────────────────────


def test_build_rollup_aggregates_by_prompt_name(tmp_path):
    record_prompt_use("orchestrator/bfts_select", "hashA", checkpoint_dir=tmp_path)
    record_prompt_use("orchestrator/bfts_select", "hashA", checkpoint_dir=tmp_path)
    record_prompt_use("agent/system", "hashB", checkpoint_dir=tmp_path)
    rollup = build_prompt_versions_rollup(tmp_path)
    assert rollup["orchestrator/bfts_select"]["call_count"] == 2
    assert rollup["orchestrator/bfts_select"]["template_hash"] == "hashA"
    assert rollup["orchestrator/bfts_select"]["prompt_version"] is None
    assert rollup["agent/system"]["call_count"] == 1


def test_build_rollup_empty_when_no_trace(tmp_path):
    assert build_prompt_versions_rollup(tmp_path) == {}


def test_save_prompt_versions_json_formatting(tmp_path):
    from ari.checkpoint import save_prompt_versions_json

    rollup = {"agent/system": {"template_hash": "h", "prompt_version": None, "call_count": 1}}
    save_prompt_versions_json(tmp_path, rollup)
    p = tmp_path / PROMPT_VERSIONS_FILENAME
    assert p.exists()
    raw = p.read_text(encoding="utf-8")
    # indent=2, ensure_ascii=False layout (consistent with other writers).
    assert "\n  " in raw
    assert json.loads(raw) == rollup


# ── metadata registration ──────────────────────────────────────────────────


def test_new_filenames_are_meta_files():
    from ari.paths import PathManager

    assert PROMPT_TRACE_FILENAME in PathManager.META_FILES
    assert PROMPT_VERSIONS_FILENAME in PathManager.META_FILES
    assert PathManager.is_meta_file(PROMPT_TRACE_FILENAME) is True
    assert PathManager.is_meta_file(PROMPT_VERSIONS_FILENAME) is True


def test_prompt_versions_is_internal_json():
    from ari.orchestrator.node_report.builder import (
        _INTERNAL_JSON_NAMES,
        classify_artifact_role,
    )

    assert PROMPT_VERSIONS_FILENAME in _INTERNAL_JSON_NAMES
    # Internal JSON is not surfaced as a publishable data output.
    assert classify_artifact_role(PROMPT_VERSIONS_FILENAME) == "unknown"
