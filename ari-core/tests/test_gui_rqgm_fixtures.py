"""GUI refresh Wave 4a — deterministic RQGM checkpoint fixture tests.

Pins ``tests/fixtures/gui_refresh/rqgm_fixture_factory.py`` (plan
``docs/plans/gui_refresh/08`` §Source artifacts / §Governance state model):

- every written RQGM artifact validates against its ``ari/schemas/*.schema.json``
  (``jsonschema`` 4.x is a test dependency — verified importable here;
  ``rqgm_state.json`` and ``meta.json`` have no schema file, so they get
  structural assertions instead);
- the ``rqgm_transitions.jsonl`` / ``rqgm_audit.jsonl`` hash chains verify by
  recomputing ``hash12(canonical_json(payload))`` per line, and the
  utility-policy seal reproduces via the imported production helpers
  (the plan-08 "compute the hash the same way ``seal_utility_policy`` does"
  parity requirement);
- ``RqgmStateStore.replay`` over the factory's transitions log reconstructs
  exactly the written ``epoch_state.json`` / ``rqgm_registry.json`` rollups
  (``load_state`` leaves the snapshot bytes untouched — in-sync);
- same ``(nodes, epochs, seed)`` ⇒ byte-identical files (P2);
- each corrupt mode (``broken_chain`` / ``truncated_transitions`` /
  ``registry_mismatch``) produces exactly its intended defect under current
  library behaviour;
- truth rules (plan 08): the penalty references a ``vat_*`` record, never the
  raw attack; the deterministic record-violation surfaces return clean; the
  registry lifecycle vocabulary and the node score-state sentinels stay in
  their own state machines;
- the base ``simple_bfts`` fixture from ``run_fixture_factory`` remains
  byte-identical when the RQGM factory is not invoked (no RQGM file leaks).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest

from ari.rqgm.adversarial.records import (
    raw_attack_violations,
    utility_record_violations,
    validated_attack_violations,
)
from ari.rqgm.events import STATUS_VALUES, canonical_json, hash12
from ari.rqgm.kernel_rules import CONSTITUTION_HASH
from ari.rqgm.store import RqgmStateStore

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "gui_refresh"
_SCHEMAS_DIR = (
    Path(__file__).resolve().parents[1] / "ari" / "schemas"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rqgm_factory = _load_module(
    "gui_refresh_rqgm_fixture_factory",
    _FIXTURES_DIR / "rqgm_fixture_factory.py",
)
base_factory = _load_module(
    "gui_refresh_run_fixture_factory",
    _FIXTURES_DIR / "run_fixture_factory.py",
)
make_rqgm_checkpoint = rqgm_factory.make_rqgm_checkpoint
make_run_checkpoint = base_factory.make_run_checkpoint

_RQGM_FILES = (
    "rqgm_state.json",
    "rqgm_transitions.jsonl",
    "rqgm_audit.jsonl",
    "epoch_state.json",
    "rqgm_registry.json",
    "rqgm_adversarial_cases.jsonl",
    # Wave 4b layers (with_evolution default-on; with_paper opt-in) — none
    # of these may ever leak into a simple_bfts checkpoint either.
    "prompt_evolution.jsonl",
    "rqgm_meta_outputs.jsonl",
    "paper_archive_state.json",
    "paper_draft_archive.jsonl",
    "paper_anchor_corpus.jsonl",
    "full_paper.tex",
)

#: Node score-state sentinel keys (plan 10 §6) — a vocabulary DISTINCT from
#: the registry lifecycle statuses; the two must never bleed into each other.
_NODE_SENTINELS = (
    "_stale", "_valid_for_frontier", "_stale_reason", "_erasure_event_id",
    "_pre_penalty_score", "_validated_attack_penalty", "_utility_policy_hash",
)


def _schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tree_metrics(dest: Path) -> dict[str, dict]:
    tree = json.loads((dest / "tree.json").read_text(encoding="utf-8"))
    return {n["id"]: n["metrics"] for n in tree["nodes"]}


@pytest.fixture(scope="module")
def rqgm_checkpoint(tmp_path_factory):
    """One shared full-featured checkpoint (module-scoped: the factory is
    deterministic and the tests below only read it)."""
    dest = tmp_path_factory.mktemp("rqgm_fixture") / "ck"
    manifest = make_rqgm_checkpoint(
        dest, nodes=10, epochs=2, seed=0,
        with_penalty=True, with_policy_rewrite=True,
    )
    return dest, manifest


# ──────────────────────────────────────────────
# schema validation per artifact
# ──────────────────────────────────────────────


def test_epoch_state_and_registry_validate(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    es = json.loads((dest / "epoch_state.json").read_text(encoding="utf-8"))
    jsonschema.validate(es, _schema("epoch_state.schema.json"))
    assert es["epoch_id"] == manifest["final_epoch_id"] == "epoch_001"
    assert es["utility_policy"]["utility_policy_hash"] == (
        manifest["current_policy_hash"]
    )

    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(rollup, _schema("rqgm_registry.schema.json"))
    # Lifecycle vocabulary is the implementation's closed STATUS_VALUES set.
    for entry in rollup["components"] + rollup["prompts"]:
        assert entry["status"] in STATUS_VALUES


def test_transitions_lines_validate(rqgm_checkpoint):
    dest, _ = rqgm_checkpoint
    schema = _schema("rqgm_transition_event.schema.json")
    lines = _jsonl(dest / "rqgm_transitions.jsonl")
    assert lines
    for rec in lines:
        jsonschema.validate(rec, schema)


def test_audit_lines_validate(rqgm_checkpoint):
    """Audit lines reuse the transition-event ENVELOPE with governance
    event types (outside the transitions ``event_type`` enum — the schema's
    documented split), so the envelope is checked structurally and each
    payload against its own record schema."""
    dest, manifest = rqgm_checkpoint
    payload_schemas = {
        "governance_report": _schema("governance_report.schema.json"),
        "selective_erasure": _schema("selective_erasure_event.schema.json"),
        "frontier_rebuild": _schema("frontier_rebuild_event.schema.json"),
    }
    lines = _jsonl(dest / "rqgm_audit.jsonl")
    # one governance_report per epoch + the erasure/rebuild pair.
    assert [r["event_type"] for r in lines] == [
        "governance_report", "selective_erasure", "frontier_rebuild",
        "governance_report",
    ]
    for rec in lines:
        assert rec["schema_version"] == 1
        assert re.fullmatch(r"evt_[0-9]{6,}", rec["event_id"])
        assert re.fullmatch(r"[0-9a-f]{12}", rec["event_hash"])
        assert isinstance(rec["payload"], dict)
        jsonschema.validate(
            rec["payload"], payload_schemas[rec["event_type"]]
        )
    erasure = lines[1]["payload"]
    assert erasure == manifest["erasure_event"]
    assert erasure["retired_prompt_hashes"] == [manifest["policy_hash_v1"]]


def test_adversarial_lines_validate(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    attack_schema = _schema("rqgm_attack_records.schema.json")
    utility_schema = _schema("rqgm_utility_record.schema.json")
    lines = _jsonl(dest / "rqgm_adversarial_cases.jsonl")
    assert [r["record_type"] for r in lines] == [
        "raw_attack", "defender_response", "judgment_record",
        "validated_attack", "utility_record",
    ]
    for rec in lines:
        schema = (
            utility_schema
            if rec["record_type"] == "utility_record"
            else attack_schema
        )
        jsonschema.validate(rec, schema)
    assert lines[-1] == manifest["utility_record"]


def test_state_and_meta_structural(rqgm_checkpoint):
    """No ``ari/schemas`` file exists for rqgm_state.json / meta.json —
    structural assertions instead (documented in the factory docstring)."""
    dest, _ = rqgm_checkpoint
    state = json.loads((dest / "rqgm_state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["mode"] == "ari_rqgm"
    assert state["rqgm_enabled"] is True
    assert state["mode_source"] == "config"
    assert state["switch_journal"][0] == {
        "event": "run_start", "mode": "ari_rqgm", "epoch_id": None,
    }
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["constitution_hash"] == CONSTITUTION_HASH


# ──────────────────────────────────────────────
# hash chains + policy-seal parity
# ──────────────────────────────────────────────


def _assert_chain(path: Path) -> None:
    prev = ""
    lines = _jsonl(path)
    assert lines, path.name
    for i, rec in enumerate(lines):
        assert rec["event_hash"] == hash12(canonical_json(rec["payload"])), (
            f"{path.name}: event {i} hash does not cover its payload"
        )
        assert rec["prev_event_hash"] == prev, (
            f"{path.name}: event {i} breaks the chain"
        )
        prev = rec["event_hash"]


def test_hash_chain_integrity(rqgm_checkpoint):
    dest, _ = rqgm_checkpoint
    _assert_chain(dest / "rqgm_transitions.jsonl")
    _assert_chain(dest / "rqgm_audit.jsonl")


def test_utility_policy_seal_parity(rqgm_checkpoint):
    """``utility_policy_hash`` reproduces via ``hash12(canonical_json(body))``
    — the exact ``seal_utility_policy`` arithmetic — and the write-once body
    files carry the very bytes the registered ``prompt_hash`` covers."""
    dest, manifest = rqgm_checkpoint
    es = json.loads((dest / "epoch_state.json").read_text(encoding="utf-8"))
    policy = dict(es["utility_policy"])
    sealed = policy.pop("utility_policy_hash")
    assert set(policy) == {
        "composite", "axis_weights", "frontier_score",
        "depth_penalty_lambda", "ucb_c",
    }
    assert sealed == hash12(canonical_json(policy))

    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    policy_prompts = [
        p for p in rollup["prompts"] if p["role"] == "utility_policy"
    ]
    assert len(policy_prompts) == 2
    for entry in policy_prompts:
        body_bytes = (dest / entry["source"]["path"]).read_text(
            encoding="utf-8"
        )
        assert hash12(body_bytes) == entry["prompt_hash"]
    assert {p["status"] for p in policy_prompts} == {
        "retired", "probationary_active",
    }
    assert manifest["policy_hash_v1"] != manifest["policy_hash_v2"]


# ──────────────────────────────────────────────
# replay consistency (rollup == replay of the truth log)
# ──────────────────────────────────────────────


def test_replay_matches_snapshots(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    store = RqgmStateStore()
    state = store.replay(dest)
    assert state is not None and state.epoch is not None

    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    assert rollup["registry_version"] == state.prompts.registry_version()
    assert rollup["as_of_event_hash"] == state.last_event_hash
    assert rollup["as_of_event_hash"] == (
        manifest["transitions_last_event_hash"]
    )

    es = json.loads((dest / "epoch_state.json").read_text(encoding="utf-8"))
    assert state.epoch.epoch_id == es["epoch_id"]
    assert state.epoch.status == es["status"] == "open"
    assert state.epoch.epoch_fingerprint == es["epoch_fingerprint"]

    # Current state = committed replay: the adopted successor is the active
    # utility_policy hash; the retired incumbent is out of the active set.
    active = state.prompts.active_prompt_hashes()
    assert active["utility_policy"] == manifest["policy_hash_v2"]

    # In-sync snapshots: load_state must not rewrite either rollup.
    before = {
        f: (dest / f).read_bytes()
        for f in ("epoch_state.json", "rqgm_registry.json")
    }
    assert store.load_state(dest) is not None
    after = {
        f: (dest / f).read_bytes()
        for f in ("epoch_state.json", "rqgm_registry.json")
    }
    assert before == after


# ──────────────────────────────────────────────
# determinism (P2)
# ──────────────────────────────────────────────


def test_same_seed_byte_identity(tmp_path):
    # with_paper=True so the Wave 4b evolution AND paper layers are inside
    # the byte-identity net (rglob below walks archive/ and rqgm/ too).
    make_rqgm_checkpoint(
        tmp_path / "a", nodes=10, epochs=2, seed=3, with_paper=True
    )
    make_rqgm_checkpoint(
        tmp_path / "b", nodes=10, epochs=2, seed=3, with_paper=True
    )
    names = sorted(
        str(p.relative_to(tmp_path / "a"))
        for p in (tmp_path / "a").rglob("*")
        if p.is_file()
    )
    assert names == sorted(
        str(p.relative_to(tmp_path / "b"))
        for p in (tmp_path / "b").rglob("*")
        if p.is_file()
    )
    for name in names:
        assert (tmp_path / "a" / name).read_bytes() == (
            tmp_path / "b" / name
        ).read_bytes(), f"{name} not byte-identical for identical seeds"


def test_different_seed_changes_content(tmp_path):
    make_rqgm_checkpoint(tmp_path / "a", nodes=10, epochs=2, seed=3)
    make_rqgm_checkpoint(tmp_path / "c", nodes=10, epochs=2, seed=4)
    assert (tmp_path / "a" / "rqgm_transitions.jsonl").read_bytes() != (
        tmp_path / "c" / "rqgm_transitions.jsonl"
    ).read_bytes()


# ──────────────────────────────────────────────
# score-lineage sentinels + plan-08 truth rules
# ──────────────────────────────────────────────


def test_penalty_sentinels_and_truth_rules(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    metrics = _tree_metrics(dest)
    node_a, node_b = manifest["penalty_node_ids"]
    for nid in (node_a, node_b):
        m = metrics[nid]
        assert m["_scientific_score"] == max(
            0.0, m["_pre_penalty_score"] - m["_validated_attack_penalty"]
        )
        assert m["_utility_policy_hash"] == manifest["current_policy_hash"]

    lines = _jsonl(dest / "rqgm_adversarial_cases.jsonl")
    by_type = {r["record_type"]: r for r in lines}
    utl = by_type["utility_record"]
    # Raw attack != validated penalty: the penalty channel references the
    # adjudicated vat_* id only — never the atk_* id (invariant 8).
    assert utl["penalty"] > 0
    vat_ids = utl["input_refs"]["validated_attack_ids"]
    assert vat_ids == ["vat_000000"]
    assert "atk_000000" not in vat_ids
    assert utl["node_id"] == node_a
    m_a = metrics[node_a]
    assert utl["base_score"] == m_a["_pre_penalty_score"]
    assert utl["penalty"] == m_a["_validated_attack_penalty"]
    assert utl["final_score"] == m_a["_scientific_score"]
    assert utl["utility_policy_hash"] == manifest["current_policy_hash"]
    # Task-14 self-describing record: the epoch policy travels by value.
    assert utl["frozen_policy"]["utility_policy"]["utility_policy_hash"] == (
        manifest["current_policy_hash"]
    )

    # Deterministic kernel-surface re-checks stay clean on the fixture.
    assert raw_attack_violations(by_type["raw_attack"]) == []
    assert validated_attack_violations(by_type["validated_attack"]) == []
    assert utility_record_violations(utl) == []

    # Structurally inert accountability chain (plan 08): the vat implicates
    # the generator ROLE and binds no component — the key must be absent,
    # never present-and-empty.
    vat = by_type["validated_attack"]
    assert vat["affected_components"] == ["generator"]
    assert "target_component_id" not in vat


def test_invalidated_node_sentinels(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    metrics = _tree_metrics(dest)
    stale_id = manifest["invalidated_node_id"]
    m = metrics[stale_id]
    assert m["_stale"] is True
    assert m["_valid_for_frontier"] is False
    assert m["_stale_reason"] == "utility_invalidated"
    assert m["_erasure_event_id"] == "erase_00000"
    # Scored under the retired policy — the stamp names the OLD hash.
    assert m["_utility_policy_hash"] == manifest["policy_hash_v1"]
    # The node score-state sentinels never leak registry lifecycle words.
    assert m["_stale_reason"] not in STATUS_VALUES

    for nid in manifest["scored_node_ids"]:
        if nid == stale_id:
            continue
        assert metrics[nid]["_utility_policy_hash"] == (
            manifest["current_policy_hash"]
        )
        assert "_stale" not in metrics[nid]

    # Cause/effect join: erasure and rebuild events name exactly this node.
    assert manifest["erasure_event"]["invalidated_node_ids"] == [stale_id]
    rebuild = manifest["rebuild_event"]
    assert rebuild["removed_node_ids"] == [stale_id]
    assert stale_id in rebuild["frontier_before"]
    assert stale_id not in rebuild["frontier_after"]
    assert rebuild["source_refs"] == ["erase_00000"]

    # Logical-only erasure: results.json / nodes_tree.json still carry the
    # node (staleness is never physical deletion).
    results = json.loads((dest / "results.json").read_text(encoding="utf-8"))
    assert stale_id in results["nodes"]
    assert results["nodes"][stale_id]["metrics"] == m


def test_sentinels_mirrored_across_tree_files(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    tree_metrics = _tree_metrics(dest)
    nodes_tree = json.loads(
        (dest / "nodes_tree.json").read_text(encoding="utf-8")
    )
    results = json.loads((dest / "results.json").read_text(encoding="utf-8"))
    for nid in manifest["scored_node_ids"]:
        nt = next(n for n in nodes_tree["nodes"] if n["id"] == nid)
        assert nt["metrics"] == tree_metrics[nid]
        assert results["nodes"][nid]["metrics"] == tree_metrics[nid]


# ──────────────────────────────────────────────
# flags off
# ──────────────────────────────────────────────


def test_without_penalty(tmp_path):
    dest = tmp_path / "nopen"
    manifest = make_rqgm_checkpoint(
        dest, nodes=10, epochs=2, seed=0, with_penalty=False,
    )
    assert manifest["penalty_node_ids"] == []
    assert manifest["utility_record"] is None
    assert not (dest / "rqgm_adversarial_cases.jsonl").exists()
    for m in _tree_metrics(dest).values():
        assert "_pre_penalty_score" not in m
        assert "_validated_attack_penalty" not in m


def test_without_policy_rewrite(tmp_path):
    dest = tmp_path / "norew"
    manifest = make_rqgm_checkpoint(
        dest, nodes=10, epochs=2, seed=0, with_policy_rewrite=False,
    )
    assert manifest["policy_hash_v2"] is None
    assert manifest["invalidated_node_id"] is None
    assert manifest["current_policy_hash"] == manifest["policy_hash_v1"]
    events = [r["event_type"] for r in _jsonl(dest / "rqgm_audit.jsonl")]
    assert events == ["governance_report", "governance_report"]
    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    assert [
        p["prompt_id"] for p in rollup["prompts"]
        if p["role"] == "utility_policy"
    ] == ["utility_policy_prompt_v1"]
    for m in _tree_metrics(dest).values():
        assert "_stale" not in m
        if "_utility_policy_hash" in m:
            assert m["_utility_policy_hash"] == manifest["policy_hash_v1"]


def test_argument_validation(tmp_path):
    with pytest.raises(ValueError):
        make_rqgm_checkpoint(tmp_path / "x", epochs=0)
    with pytest.raises(ValueError):
        make_rqgm_checkpoint(tmp_path / "x", epochs=1, with_policy_rewrite=True)
    with pytest.raises(ValueError):
        make_rqgm_checkpoint(tmp_path / "x", corrupt="nonsense")


def test_three_epochs_replay(tmp_path):
    dest = tmp_path / "e3"
    manifest = make_rqgm_checkpoint(dest, nodes=10, epochs=3, seed=0)
    assert manifest["final_epoch_id"] == "epoch_002"
    state = RqgmStateStore().replay(dest)
    assert state.epoch.epoch_id == "epoch_002"
    es = json.loads((dest / "epoch_state.json").read_text(encoding="utf-8"))
    assert es["epoch_id"] == "epoch_002"
    assert es["previous_epoch_id"] == "epoch_001"
    jsonschema.validate(es, _schema("epoch_state.schema.json"))


# ──────────────────────────────────────────────
# Wave 4b: prompt_evolution / meta outputs / paper layer
# ──────────────────────────────────────────────


def test_prompt_evolution_lines_validate(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    lines = _jsonl(dest / "prompt_evolution.jsonl")
    by_type = {r["record_type"]: r for r in lines}
    assert list(by_type) == [
        "prompt_candidate", "utility_policy_candidate",
        "prompt_candidate_validation",
    ]
    evolution_schema = _schema("rqgm_prompt_evolution.schema.json")
    upc_schema = _schema("rqgm_utility_policy_candidate.schema.json")
    for rec in lines:
        if rec["record_type"] == "utility_policy_candidate":
            jsonschema.validate(rec, upc_schema)
        else:
            jsonschema.validate(rec, evolution_schema)
    upc = by_type["utility_policy_candidate"]
    # One value, three names: hash12(canonical_json(policy)) IS policy_hash
    # IS the utility_policy_hash the candidate would freeze if adopted.
    assert upc["policy_hash"] == hash12(canonical_json(upc["policy"]))
    assert upc["policy_hash"] == manifest["policy_hash_v2"]
    assert upc["candidate_id"] == manifest["utility_candidate_id"]
    assert upc["parent_prompt_id"] == "utility_policy_prompt_v1"
    # The validation record cites the candidate, not the registry.
    pval = by_type["prompt_candidate_validation"]
    assert pval["candidate_id"] == upc["candidate_id"]
    assert pval["passed"] is True
    # The raw prompt candidate is never registered: its hash appears in no
    # registry rollup prompt entry (raw candidate != adopted prompt).
    pcand = by_type["prompt_candidate"]
    assert pcand["candidate_id"] == manifest["prompt_candidate_id"]
    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    assert pcand["prompt_hash"] not in {
        p["prompt_hash"] for p in rollup["prompts"]
    }


def test_meta_outputs_line_structural(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    (rec,) = _jsonl(dest / "rqgm_meta_outputs.jsonl")
    assert rec["record_type"] == "meta_agent_output"
    assert rec["record_id"] == manifest["meta_output_id"]
    # Content-derived id parity with ari.rqgm.meta_evolution._meta_output_id.
    assert rec["record_id"] == "meta_out_" + hash12(canonical_json([
        rec["component_id"], rec["epoch_id"], rec["output_kind"],
        rec["input_bundle_hash"], rec["output_payload_hash"],
    ]))
    assert rec["candidate_ref"] == manifest["prompt_candidate_id"]
    assert rec["status"] == "recorded"


def test_without_evolution(tmp_path):
    dest = tmp_path / "noevo"
    manifest = make_rqgm_checkpoint(
        dest, nodes=10, epochs=2, seed=0, with_evolution=False,
    )
    assert manifest["utility_candidate_id"] is None
    assert not (dest / "prompt_evolution.jsonl").exists()
    assert not (dest / "rqgm_meta_outputs.jsonl").exists()


def test_paper_layer_absent_by_default(rqgm_checkpoint):
    dest, manifest = rqgm_checkpoint
    assert manifest["with_paper"] is False
    for name in (
        "paper_archive_state.json", "paper_draft_archive.jsonl",
        "paper_anchor_corpus.jsonl", "full_paper.tex",
    ):
        assert not (dest / name).exists()
    assert not (dest / "rqgm" / "paper_self_preference_stat.json").exists()


@pytest.fixture(scope="module")
def paper_checkpoint(tmp_path_factory):
    dest = tmp_path_factory.mktemp("rqgm_paper_fixture") / "ck"
    manifest = make_rqgm_checkpoint(
        dest, nodes=10, epochs=2, seed=0, with_paper=True,
    )
    return dest, manifest


def test_paper_state_and_policy_seal(paper_checkpoint):
    dest, manifest = paper_checkpoint
    state = json.loads(
        (dest / "paper_archive_state.json").read_text(encoding="utf-8")
    )
    assert state["schema_version"] == 1
    assert state["paper_mode"] == "rqgm_archive"
    assert state["rqgm_paper_enabled"] is True
    assert state["mode_source"] == "config"
    policy = state["paper_utility_policy"]
    assert policy["anchor_enabled"] is True
    # capture_paper_utility_policy seal parity: the hash is OF the body
    # without its own hash key.
    body = {
        k: v for k, v in policy.items() if k != "paper_utility_policy_hash"
    }
    assert policy["paper_utility_policy_hash"] == hash12(
        canonical_json(body)
    )
    assert state["paper_epoch_fingerprint"] == (
        policy["paper_utility_policy_hash"]
    ) == manifest["paper_utility_policy_hash"]
    # The frozen corpus digest matches the written corpus.
    from ari.rqgm.paper_anchor import corpus_digest

    cases = _jsonl(dest / "paper_anchor_corpus.jsonl")
    assert [c["case_id"] for c in cases] == manifest["anchor_case_ids"]
    assert policy["anchor_corpus_digest"] == corpus_digest(cases)
    for case in cases:
        assert case["record_type"] == "PaperAnchorCase"
        assert case["ground_truth_label"] in ("accept", "reject")
        assert case["label_source"] == "human_curated"


def test_paper_draft_archive_content_hash_consistent(paper_checkpoint):
    dest, manifest = paper_checkpoint
    records = _jsonl(dest / "paper_draft_archive.jsonl")
    assert [r["node_id"] for r in records] == manifest["paper_draft_ids"]
    epochs_seen = []
    for r in records:
        assert r["schema_version"] == 1
        assert r["kind"] in ("seed", "refine")
        if r["epoch_id"] not in epochs_seen:
            epochs_seen.append(r["epoch_id"])
        # §8.6 content-hash rule: the bytes at each record's own tex_path
        # hash to its recorded tex_sha256.
        import hashlib as _hashlib

        got = _hashlib.sha256(
            (dest / r["tex_path"]).read_text(encoding="utf-8").encode()
        ).hexdigest()
        assert got == r["tex_sha256"], r["node_id"]
    assert epochs_seen == manifest["paper_epoch_ids"]
    # Exactly ONE best-belief carrier (§6.1), and the materialized winner is
    # a byte copy of that record's tex.
    winners = [r for r in records if r["is_best_belief"]]
    assert [r["node_id"] for r in winners] == [
        manifest["paper_winner_node_id"]
    ]
    assert (dest / "full_paper.tex").read_bytes() == (
        dest / winners[0]["tex_path"]
    ).read_bytes()


def test_paper_self_preference_stat_structural(paper_checkpoint):
    dest, manifest = paper_checkpoint
    stat = json.loads(
        (dest / "rqgm" / "paper_self_preference_stat.json").read_text(
            encoding="utf-8"
        )
    )
    assert stat["record_type"] == "paper_self_preference_stat"
    assert stat["schema_version"] == 1
    assert stat["sample_ids"] == sorted(manifest["anchor_case_ids"])
    assert stat["margin"] == manifest["self_preference_margin"]
    # The population identity the statistic claims: margin = ai - human.
    assert stat["margin"] == round(
        stat["ai_mean"] - stat["human_mean"], 6
    )


# ──────────────────────────────────────────────
# corrupt modes — the intended defect, nothing else
# ──────────────────────────────────────────────


def test_corrupt_broken_chain(tmp_path):
    dest = tmp_path / "broken"
    make_rqgm_checkpoint(dest, nodes=10, epochs=2, seed=0,
                         corrupt="broken_chain")
    lines = _jsonl(dest / "rqgm_transitions.jsonl")
    breaks = []
    prev = ""
    for i, rec in enumerate(lines):
        # Every hash still covers its payload — ONLY the chain is broken.
        assert rec["event_hash"] == hash12(canonical_json(rec["payload"]))
        if rec["prev_event_hash"] != prev:
            breaks.append(i)
        prev = rec["event_hash"]
    assert breaks == [1]
    # Each line still validates individually (pattern-valid wrong hash).
    schema = _schema("rqgm_transition_event.schema.json")
    for rec in lines:
        jsonschema.validate(rec, schema)


def test_corrupt_truncated_transitions(tmp_path):
    dest = tmp_path / "torn"
    make_rqgm_checkpoint(dest, nodes=10, epochs=2, seed=0,
                         corrupt="truncated_transitions")
    raw_lines = (
        (dest / "rqgm_transitions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw_lines[-1])
    for line in raw_lines[:-1]:
        json.loads(line)
    # The torn line was the boundary commit: replay's crash-recovery filter
    # drops the whole uncommitted tail, so the replayed current state falls
    # back to epoch_000 while the (now stale) snapshot still says epoch_001
    # — exactly the degraded shape the GUI must surface.
    state = RqgmStateStore().replay(dest)
    assert state is not None
    assert state.epoch.epoch_id == "epoch_000"
    es = json.loads((dest / "epoch_state.json").read_text(encoding="utf-8"))
    assert es["epoch_id"] == "epoch_001"


def test_corrupt_registry_mismatch(tmp_path):
    dest = tmp_path / "stale"
    make_rqgm_checkpoint(dest, nodes=10, epochs=2, seed=0,
                         corrupt="registry_mismatch")
    store = RqgmStateStore()
    state = store.replay(dest)
    rollup = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    assert rollup["as_of_event_hash"] != state.last_event_hash  # stale rollup
    # Current library behaviour: load_state detects the mismatch and rebuilds
    # the snapshot from replay.
    assert store.load_state(dest) is not None
    rebuilt = json.loads(
        (dest / "rqgm_registry.json").read_text(encoding="utf-8")
    )
    assert rebuilt["as_of_event_hash"] == state.last_event_hash


# ──────────────────────────────────────────────
# simple_bfts base fixture stays untouched
# ──────────────────────────────────────────────


def test_base_fixture_untouched_by_rqgm_factory(tmp_path):
    make_run_checkpoint(tmp_path / "plain_before", nodes=10, seed=0)
    make_rqgm_checkpoint(tmp_path / "rqgm", nodes=10, epochs=2, seed=0)
    make_run_checkpoint(tmp_path / "plain_after", nodes=10, seed=0)

    before_files = sorted(
        p.name for p in (tmp_path / "plain_before").iterdir() if p.is_file()
    )
    after_files = sorted(
        p.name for p in (tmp_path / "plain_after").iterdir() if p.is_file()
    )
    assert before_files == after_files
    # No RQGM artifact ever appears in a simple_bfts checkpoint (absence is
    # the mode signal), and no sentinel key leaks into its metrics.
    for fname in _RQGM_FILES:
        assert fname not in before_files
    assert not (tmp_path / "plain_before" / "rqgm_prompts").exists()
    for fname in before_files:
        assert (tmp_path / "plain_before" / fname).read_bytes() == (
            tmp_path / "plain_after" / fname
        ).read_bytes(), f"{fname} drifted after RQGM factory use"
    for m in _tree_metrics(tmp_path / "plain_before").values():
        for key in _NODE_SENTINELS:
            assert key not in m
    meta = json.loads(
        (tmp_path / "plain_before" / "meta.json").read_text(encoding="utf-8")
    )
    assert "constitution_hash" not in meta
