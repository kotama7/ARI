"""Selective-erasure awareness (plan 10 §3, the memory half — settled).

ARI governance can logically erase a research node: nothing is deleted, and
what is withdrawn is the STANDING of the judgment attached to it. The memory
layer therefore ANNOTATES rather than hides — a caller that deliberately asks
for an erased node's entries gets them labelled — while the one PUSH path
exposed as a tool (``get_verified_context``, whose output grounds paper
claims) hard-excludes instead.

The reader is the published ``rqgm_erasure_state.json`` rollup; absence means
nothing is stale, so every assertion here is inert on a non-RQGM checkpoint.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from ari_skill_memory import erasure

_SERVER_PY = Path(__file__).resolve().parent.parent / "src" / "server.py"
_spec = importlib.util.spec_from_file_location(
    "ari_skill_memory_server_erasure", _SERVER_PY)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def _write_rollup(ckpt, invalid, *, schema_version=1):
    (ckpt / erasure.ERASURE_STATE_FILENAME).write_text(json.dumps({
        "schema_version": schema_version,
        "retired_prompt_hashes": {},
        "stale_record_ids": {},
        erasure.INVALID_NODE_IDS_FIELD: invalid,
        "last_erasure_event_id": "erase_000001",
        "last_rebuild_event_id": "",
    }))


def _seed(backend, monkeypatch, node_id, text, metadata=None):
    """Write one entry as *node_id* (the CoW guard pins writes to the node
    named by ``ARI_CURRENT_NODE_ID``)."""
    monkeypatch.setenv("ARI_CURRENT_NODE_ID", node_id)
    res = backend.add_memory(
        node_id, text, metadata or {"type": "result_summary"})
    assert res.get("ok"), res
    return res


def _read_capability(authorized_context, tool_name, node_ids):
    """Issue the transport capability for a reader below ``node_ids``."""

    lineage = list(node_ids)
    return authorized_context(
        tool_name,
        node_id="reader",
        parent_node_id=lineage[-1] if lineage else None,
        ancestor_node_ids=lineage,
    )


def _artifact_ref(ckpt, relative_path, payload):
    """Materialize one immutable fixture artifact and return its typed ref."""

    target = ckpt / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "role": "data_output",
    }


# ── the rollup reader ───────────────────────────────────────────────────────

def test_absent_rollup_means_nothing_is_erased(ckpt_env):
    assert erasure.erased_nodes(ckpt_env) == {}


def test_rollup_is_read_and_reread_when_it_changes(ckpt_env):
    _write_rollup(ckpt_env, {"p1": "erase_000001"})
    assert erasure.erased_nodes(ckpt_env) == {"p1": "erase_000001"}
    # The runtime rewrites the rollup at epoch boundaries and this skill is a
    # long-lived process: a changed file must not serve a stale cache.
    _write_rollup(ckpt_env, {"p1": "erase_000001", "p2": "erase_000002"})
    assert set(erasure.erased_nodes(ckpt_env)) == {"p1", "p2"}


def test_malformed_or_newer_rollup_degrades_to_nothing_erased(ckpt_env):
    (ckpt_env / erasure.ERASURE_STATE_FILENAME).write_text("{not json")
    assert erasure.erased_nodes(ckpt_env) == {}
    for version in (99, "99", 99.0, None):
        # A non-int version must degrade too: read with v1 semantics it would
        # produce exactly the "wrong label" this reader refuses to risk.
        _write_rollup(ckpt_env, {"p1": "e"}, schema_version=version)
        assert erasure.erased_nodes(ckpt_env) == {}, version


def test_a_same_size_rewrite_is_not_served_from_cache(ckpt_env):
    # The cache keys on the BYTES: a same-size rewrite inside one clock tick
    # shares st_mtime_ns (and st_ctime_ns), so a timestamp signature would
    # serve a stale set for the life of this long-lived process.
    _write_rollup(ckpt_env, {"p1": "erase_000001"})
    assert set(erasure.erased_nodes(ckpt_env)) == {"p1"}
    _write_rollup(ckpt_env, {"p2": "erase_000001"})   # identical byte length
    assert set(erasure.erased_nodes(ckpt_env)) == {"p2"}


def test_a_non_mapping_node_id_field_degrades_rather_than_guessing(ckpt_env):
    # A str would iterate character-by-character and mark nodes literally
    # named "n"/"1" — drop_erased would then fail UNSAFE, dropping live
    # ancestors from the grounded claims.
    _write_rollup(ckpt_env, "n1")
    assert erasure.erased_nodes(ckpt_env) == {}
    _write_rollup(ckpt_env, ["p1", "p2"])             # a list IS accepted
    assert set(erasure.erased_nodes(ckpt_env)) == {"p1", "p2"}


def test_caller_cannot_poison_the_process_cache(ckpt_env):
    _write_rollup(ckpt_env, {"p1": "erase_000001"})
    erasure.erased_nodes(ckpt_env)["injected"] = "x"
    assert "injected" not in erasure.erased_nodes(ckpt_env)


# ── PULL: annotate, never hide ─────────────────────────────────────────────

def test_get_node_memory_labels_an_erased_node(
    ckpt_env, backend, monkeypatch, authorized_context
):
    _seed(backend, monkeypatch, "p1", "P1: tiling -> 140 GB/s")
    _write_rollup(ckpt_env, {"p1": "erase_000001"})

    out = server.get_node_memory(
        "p1",
        ari_context=_read_capability(authorized_context, "get_node_memory", ["p1"]),
    )

    assert len(out["entries"]) == 1                 # returned, not emptied
    entry = out["entries"][0]
    assert "140 GB/s" in entry["text"]              # the measurement survives
    assert entry[erasure.ERASED_KEY] is True
    assert entry[erasure.ERASURE_EVENT_KEY] == "erase_000001"
    assert "withdrawn" in entry[erasure.ERASURE_NOTE_KEY]


def test_search_memory_labels_only_the_erased_nodes(ckpt_env, backend,
                                                    monkeypatch,
                                                    authorized_context):
    _seed(backend, monkeypatch, "p1", "erased finding about tiling")
    _seed(backend, monkeypatch, "p2", "valid finding about tiling")
    _write_rollup(ckpt_env, {"p1": "erase_000001"})

    results = server.search_memory(
        "tiling",
        ["p1", "p2"],
        5,
        ari_context=_read_capability(
            authorized_context, "search_memory", ["p1", "p2"]
        ),
    )["results"]

    by_node = {r["node_id"]: r for r in results}
    assert set(by_node) == {"p1", "p2"}
    assert by_node["p1"][erasure.ERASED_KEY] is True
    assert erasure.ERASED_KEY not in by_node["p2"]


def test_typed_search_labels_erased_entries(
    ckpt_env, backend, monkeypatch, authorized_context
):
    result = server.add_experiment_result(
        "p1",
        "throughput 140 GB/s at tile=32",
        artifact_refs=[
            _artifact_ref(ckpt_env, "out/bench.csv", b"tile,throughput\n32,140\n")
        ],
        ari_context=authorized_context("add_experiment_result", node_id="p1"),
    )
    assert result["ok"]
    _write_rollup(ckpt_env, {"p1": "erase_000001"})

    results = server.search_research_memory(
        "throughput",
        ["p1"],
        ari_context=_read_capability(
            authorized_context, "search_research_memory", ["p1"]
        ),
    )["results"]

    assert results and results[0][erasure.ERASED_KEY] is True


def test_no_rollup_leaves_payloads_byte_identical(ckpt_env, backend,
                                                  monkeypatch,
                                                  authorized_context):
    # Identity default: a non-RQGM checkpoint never carries the rollup, so no
    # response gains a key.
    _seed(backend, monkeypatch, "p1", "a finding")
    assert all(
        erasure.ERASED_KEY not in e
        for e in server.get_node_memory(
            "p1",
            ari_context=_read_capability(
                authorized_context, "get_node_memory", ["p1"]
            ),
        )["entries"]
    )
    assert all(
        erasure.ERASED_KEY not in r
        for r in server.search_memory(
            "finding",
            ["p1"],
            5,
            ari_context=_read_capability(
                authorized_context, "search_memory", ["p1"]
            ),
        )["results"]
    )


# ── PUSH: grounded claims hard-exclude ─────────────────────────────────────

def test_limitations_keep_the_erased_node_labelled(ckpt_env, backend,
                                                   monkeypatch,
                                                   authorized_context):
    # The honest record of a direction that was later invalidated is exactly
    # what a limitations section is for — so limitations are built from the
    # FULL ancestor set while the claim lists are not.
    result = server.add_failure_case(
        "p1",
        "tiling stalled at 40 GB/s",
        ari_context=authorized_context("add_failure_case", node_id="p1"),
    )
    assert result["ok"]
    _write_rollup(ckpt_env, {"p1": "erase_000001"})

    ctx = server.get_verified_context(
        ["p1"],
        ari_context=_read_capability(
            authorized_context, "get_verified_context", ["p1"]
        ),
    )

    assert [lim["node_id"] for lim in ctx["limitations"]] == ["p1"]
    assert ctx["claims"] == [] and ctx["usable_for_claims"] == []


def test_verified_context_excludes_erased_ancestors(ckpt_env, backend,
                                                    monkeypatch,
                                                    authorized_context):
    erased = server.add_experiment_result(
        "p1",
        "erased claim: 999 GB/s",
        artifact_refs=[
            _artifact_ref(ckpt_env, "out/a.csv", b"throughput\n999\n")
        ],
        ari_context=authorized_context("add_experiment_result", node_id="p1"),
    )
    valid = server.add_experiment_result(
        "p2",
        "valid claim: 140 GB/s",
        artifact_refs=[
            _artifact_ref(ckpt_env, "out/b.csv", b"throughput\n140\n")
        ],
        ari_context=authorized_context("add_experiment_result", node_id="p2"),
    )
    assert erased["ok"] and valid["ok"]
    _write_rollup(ckpt_env, {"p1": "erase_000001"})

    ctx = server.get_verified_context(
        ["p1", "p2"],
        ari_context=_read_capability(
            authorized_context, "get_verified_context", ["p1", "p2"]
        ),
    )

    blob = json.dumps(ctx)
    assert "999 GB/s" not in blob      # a withdrawn judgment grounds nothing
    assert "140 GB/s" in blob


def test_drop_erased_is_identity_without_a_rollup(ckpt_env):
    assert erasure.drop_erased(["p1", "p2"], ckpt_env) == ["p1", "p2"]


# ── cross-package contract ─────────────────────────────────────────────────

def test_rollup_field_name_matches_ari_core_writer():
    """ari-core WRITES the rollup, this skill READS it — the field name is a
    cross-package contract, and a rename on either side would silently
    disable erasure awareness here while both suites stayed green."""
    import pytest

    core = Path(__file__).resolve().parents[2] / "ari-core" / "ari"
    core_state = core / "rqgm" / "erasure_state.py"
    core_writer = core / "checkpoint.py"
    if not core_state.is_file():        # skill checked out standalone
        pytest.skip("ari-core not present in this checkout")

    src = core_state.read_text(encoding="utf-8")
    assert f'"{erasure.INVALID_NODE_IDS_FIELD}"' in src, (
        f"ari-core no longer writes {erasure.INVALID_NODE_IDS_FIELD!r} — "
        "the memory layer's erasure awareness is now dead code"
    )
    # The SCHEMA the payload declares must be one this reader understands;
    # a bump on the ari-core side silently turns `drop_erased` into a no-op
    # (fail-OPEN for the grounded-claims path).
    import re
    m = re.search(r"ERASURE_STATE_SCHEMA_VERSION\s*=\s*(\d+)", src)
    assert m, "ari-core no longer declares ERASURE_STATE_SCHEMA_VERSION"
    assert int(m.group(1)) <= erasure.SUPPORTED_SCHEMA_VERSION, (
        f"ari-core writes rollup schema v{m.group(1)}; this reader "
        f"understands v{erasure.SUPPORTED_SCHEMA_VERSION} and would degrade "
        "to 'nothing is erased' — teach it the new schema"
    )
    # Pin the PATH against the module that actually writes it, not only the
    # constant: a RELOCATION (e.g. under an `rqgm/` subdir) would leave both
    # suites green while this reader stats a file that never exists.
    assert erasure.ERASURE_STATE_FILENAME in core_state.read_text("utf-8")
    assert (
        f'"{erasure.ERASURE_STATE_FILENAME}"' in
        core_writer.read_text(encoding="utf-8")
    ), (
        f"ari-core's writer no longer puts {erasure.ERASURE_STATE_FILENAME} "
        "at the checkpoint root — this reader would find nothing"
    )
