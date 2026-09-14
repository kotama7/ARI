"""GUI refresh Wave 4a — ``/api/v1`` RQGM read models (task 08, plan 08).

Behavior of ``ari/viz/v1/rqgm.py`` (pure readers — no ``ari.rqgm`` import in
viz; this TEST file imports ``ari.rqgm.events`` only to pin vocabulary/hash
PARITY between the two) over the deterministic fixture factory
``tests/fixtures/gui_refresh/rqgm_fixture_factory.py``:

- happy paths for all 8 GET endpoints, including the two-channel score
  lineage separation (penalty channel vs epoch-policy channel — never one
  series);
- committed-only reads: a torn trailing append changes nothing; an
  uncommitted prepare tail is never adopted into current state;
- byte-offset cursor paging with no gaps/duplicates across pages;
- corrupt fixtures (``broken_chain`` / ``registry_mismatch`` /
  ``truncated_transitions``) answer 200 with integrity flags flipped +
  ``degraded_reasons`` — never a 500;
- truth rules: raw attacks are structurally scoreless; the registry
  lifecycle vocabulary and the node score-state vocabulary stay separate
  closed sets; the 404 envelope for non-RQGM runs everywhere except
  capabilities (which reports ``enabled=false, reasons=['simple_bfts run']``);
- GET side-effect-freeness (no file/env mutation);
- Wave 4b read models (same plan, same rules): epochs (committed replay
  rows carrying per-epoch policy hashes; an open boundary is never shown as
  zero activity), evolution (raw candidate vs validated candidate vs
  adopted policy — adoption derived only from the committed registry
  replay), and paper-archive (bounded scalars, explicit absent flags —
  never fabricated zeros).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import get_args

import pytest

from ari.rqgm.events import STATUS_VALUES, canonical_json, hash12
from ari.viz import api_state
from ari.viz.v1 import dto as v1_dto
from ari.viz.v1 import rqgm as v1_rqgm
from ari.viz.v1.router import dispatch, match

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "gui_refresh"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rqgm_factory = _load_module(
    "gui_refresh_rqgm_fixture_factory_for_v1",
    _FIXTURES_DIR / "rqgm_fixture_factory.py",
)
base_factory = _load_module(
    "gui_refresh_run_fixture_factory_for_v1",
    _FIXTURES_DIR / "run_fixture_factory.py",
)

RQGM_RUN = "20260723000000_rqgmfix"
PLAIN_RUN = "20260723000001_plain"
BROKEN_RUN = "20260723000002_broken"
STALE_RUN = "20260723000003_stale"
TRUNC_RUN = "20260723000004_trunc"
TORN_RUN = "20260723000005_torn"
PENDING_RUN = "20260723000006_pending"
PAPER_RUN = "20260723000007_paper"
# Wave 4b runs.
FULLPAPER_RUN = "20260723000009_fullpaper"
NOREW_RUN = "20260723000010_norew"
NOEVO_RUN = "20260723000011_noevo"


@pytest.fixture(scope="module")
def base_dir(tmp_path_factory):
    """One search base holding every fixture checkpoint (module-scoped: the
    factory is deterministic; only the runs built for mutation tests —
    TORN/PENDING — are ever written to, and only by their own test)."""
    base = tmp_path_factory.mktemp("v1_rqgm") / "checkpoints"
    base.mkdir()
    manifests = {
        RQGM_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / RQGM_RUN, nodes=10, epochs=2, seed=0
        ),
        TORN_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / TORN_RUN, nodes=10, epochs=2, seed=0
        ),
        PENDING_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / PENDING_RUN, nodes=10, epochs=2, seed=0
        ),
        PAPER_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / PAPER_RUN, nodes=10, epochs=2, seed=0
        ),
        BROKEN_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / BROKEN_RUN, nodes=10, epochs=2, seed=0,
            corrupt="broken_chain",
        ),
        STALE_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / STALE_RUN, nodes=10, epochs=2, seed=0,
            corrupt="registry_mismatch",
        ),
        TRUNC_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / TRUNC_RUN, nodes=10, epochs=2, seed=0,
            corrupt="truncated_transitions",
        ),
        PLAIN_RUN: base_factory.make_run_checkpoint(
            base / PLAIN_RUN, nodes=10, seed=0
        ),
        # Wave 4b: the full paper layer, a rewrite-less run (utility policy
        # candidate proposed but never adopted), and an evolution-less run.
        FULLPAPER_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / FULLPAPER_RUN, nodes=10, epochs=2, seed=0,
            with_paper=True,
        ),
        NOREW_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / NOREW_RUN, nodes=10, epochs=2, seed=0,
            with_policy_rewrite=False,
        ),
        NOEVO_RUN: rqgm_factory.make_rqgm_checkpoint(
            base / NOEVO_RUN, nodes=10, epochs=2, seed=0,
            with_evolution=False,
        ),
    }
    # Paper mode is paper_archive_state.json PRESENCE (independent axis).
    (base / PAPER_RUN / "paper_archive_state.json").write_text(
        json.dumps({"schema_version": 1, "paper_epoch": 0}),
        encoding="utf-8",
    )
    return base, manifests


@pytest.fixture
def ckpt(base_dir, monkeypatch):
    base, manifests = base_dir
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    return base, manifests


def _get(path: str) -> dict:
    r = dispatch("GET", path)
    assert r.get("_status", 200) == 200, r
    return r


def _strip(r: dict) -> dict:
    r = dict(r)
    r.pop("request_id", None)
    return r


def _assert_404(r: dict) -> None:
    assert r["_status"] == 404
    assert r["error"]["code"] == "not_found"


def _dir_digest(d: Path) -> dict[str, str]:
    return {
        str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*"))
        if p.is_file()
    }


# ── vocabulary / hash parity (viz duplicates are pinned to the source) ────


def test_registry_status_vocabulary_parity():
    assert v1_rqgm.REGISTRY_STATUSES == STATUS_VALUES
    assert set(get_args(v1_dto.RegistryStatusV1)) == set(STATUS_VALUES)
    assert set(get_args(v1_dto.NodeScoreStateV1)) == {
        "computed", "recomputed", "stale", "invalidated", "removed",
    }


def test_hash_contract_parity():
    payload = {"b": [1, 2], "a": "ü", "c": {"y": None, "x": 0.5}}
    assert v1_rqgm._canonical_json(payload) == canonical_json(payload)
    assert v1_rqgm._hash12(canonical_json(payload)) == hash12(
        canonical_json(payload)
    )


# ── capabilities ──────────────────────────────────────────────────────────


def test_capabilities_enabled(ckpt):
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/capabilities")
    assert r["schema_version"] == 1
    assert r["enabled"] is True
    assert r["mode"] == "ari_rqgm"
    assert r["mode_source"] == "config"
    assert r["paper_mode"] is False
    assert r["reasons"] == []


def test_capabilities_paper_mode_is_artifact_presence(ckpt):
    r = _get(f"/api/v1/runs/{PAPER_RUN}/rqgm/capabilities")
    assert r["enabled"] is True and r["paper_mode"] is True


def test_capabilities_simple_bfts_run(ckpt):
    r = _get(f"/api/v1/runs/{PLAIN_RUN}/rqgm/capabilities")
    assert r["enabled"] is False
    assert r["mode"] is None and r["mode_source"] is None
    assert r["reasons"] == ["simple_bfts run"]


def test_capabilities_unknown_run_404(ckpt):
    _assert_404(dispatch("GET", "/api/v1/runs/nope/rqgm/capabilities"))


def test_non_rqgm_runs_get_404_envelopes_everywhere_else(ckpt):
    for tail in (
        "overview",
        "registry",
        "transitions",
        "audit",
        "policies",
        "score-rewrites",
        "nodes/node_00001/lineage",
        # Wave 4b resources share the same non-RQGM 404 posture.
        "epochs",
        "epochs/epoch_000",
        "evolution",
        "paper-archive",
    ):
        r = dispatch("GET", f"/api/v1/runs/{PLAIN_RUN}/rqgm/{tail}")
        _assert_404(r)
        assert "simple_bfts" in r["error"]["message"]


# ── overview ──────────────────────────────────────────────────────────────


def test_overview_happy(ckpt):
    base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/overview")
    assert r["current_epoch"] == m["final_epoch_id"] == "epoch_001"
    assert r["utility_policy_hash"] == m["current_policy_hash"]
    meta = json.loads(
        (base / RQGM_RUN / "meta.json").read_text(encoding="utf-8")
    )
    assert r["constitution_hash"] == meta["constitution_hash"]
    rs = r["registry_summary"]
    assert rs["component_count"] == 5 and rs["prompt_count"] == 6
    assert rs["components_by_status"] == {"active": 5}
    assert rs["prompts_by_status"] == {
        "active": 4, "retired": 1, "probationary_active": 1,
    }
    assert r["last_committed_transition_at"]
    assert r["integrity"] == {
        "transitions_chain_ok": True,
        "registry_verified": True,
        "audit_chain_ok": True,
    }
    assert r["degraded_reasons"] == []
    # Bounded summary: no embedded entry/event lists (plan 08).
    assert "entries" not in r and "components" not in r


# ── registry ──────────────────────────────────────────────────────────────


def test_registry_happy(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/registry")
    assert r["verified"] is True
    assert (
        r["rollup_as_of_event_hash"]
        == r["replay_tail_event_hash"]
        == m["transitions_last_event_hash"]
    )
    for entry in r["components"] + r["prompts"]:
        assert entry["status"] in STATUS_VALUES
        assert entry["source_event_ids"]
    # Current state == committed replay: the adopted successor is active,
    # the superseded incumbent is retired and out of the active set.
    assert r["active_prompt_hashes"]["utility_policy"] == m["policy_hash_v2"]
    by_id = {p["prompt_id"]: p for p in r["prompts"]}
    assert by_id["utility_policy_prompt_v1"]["status"] == "retired"
    assert by_id["utility_policy_prompt_v2"]["status"] == (
        "probationary_active"
    )
    # The status-change event ids are cited on the touched entries.
    assert len(by_id["utility_policy_prompt_v1"]["source_event_ids"]) == 2
    assert r["active_components"]["utility_policy"] == "utility_policy_v1"
    assert r["degraded_reasons"] == []


# ── transitions ───────────────────────────────────────────────────────────


def test_transitions_listing_and_expand(ckpt):
    base, _ = ckpt
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions")
    assert [e["kind"] for e in r["entries"]] == [
        "transaction", "standalone", "transaction",
    ]
    assert [e["transition_id"] for e in r["entries"]] == [
        "transition_founding", None, "transition_000_to_001",
    ]
    assert r["total_entries"] == 3 and r["next_cursor"] is None
    assert r["chain_ok"] is True and r["degraded_reasons"] == []
    boundary = r["entries"][2]
    # rule_ids present; arrays summarized as counts (no inline event list).
    assert boundary["rule_ids"] == ["T20", "T6"]
    assert boundary["event_type_counts"]["prompt_status_change"] == 2
    assert boundary["epoch_closed"] == "epoch_000"
    assert boundary["epoch_opened"] == "epoch_001"
    assert all(e["events"] is None for e in r["entries"])

    # expand=1: the full raw records, byte-parity with the artifact
    # (unknown-field passthrough — records are served unmodified).
    rx = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions?expand=1")
    served = [ev for e in rx["entries"] for ev in e["events"]]
    on_disk = [
        json.loads(line)
        for line in (base / RQGM_RUN / "rqgm_transitions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert served == on_disk  # every fixture line is committed


def test_transitions_cursor_paging_no_gap_no_duplicate(ckpt):
    full = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions?limit=100")
    seen: list[int] = []
    cursor, pages = 0, 0
    while True:
        r = _get(
            f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions"
            f"?cursor={cursor}&limit=1"
        )
        seen.extend(e["byte_offset"] for e in r["entries"])
        pages += 1
        if r["next_cursor"] is None:
            break
        cursor = r["next_cursor"]
    assert pages == 3
    assert seen == [e["byte_offset"] for e in full["entries"]]
    assert len(seen) == len(set(seen))


# ── committed-only reads ──────────────────────────────────────────────────


def test_torn_trailing_append_changes_nothing(ckpt):
    base, _ = ckpt
    paths = (
        f"/api/v1/runs/{TORN_RUN}/rqgm/transitions",
        f"/api/v1/runs/{TORN_RUN}/rqgm/overview",
        f"/api/v1/runs/{TORN_RUN}/rqgm/registry",
    )
    before = [_strip(_get(p)) for p in paths]
    with open(
        base / TORN_RUN / "rqgm_transitions.jsonl", "a", encoding="utf-8"
    ) as fh:
        fh.write('{"schema_version": 1, "event_id": "evt_9')  # torn append
    after = [_strip(_get(p)) for p in paths]
    assert before == after


def test_uncommitted_prepare_tail_is_never_adopted(ckpt):
    base, m = ckpt
    trans_path = base / PENDING_RUN / "rqgm_transitions.jsonl"
    lines = trans_path.read_text(encoding="utf-8").splitlines()
    prev = json.loads(lines[-1])["event_hash"]
    before = _strip(_get(f"/api/v1/runs/{PENDING_RUN}/rqgm/transitions"))
    reg_before = _strip(_get(f"/api/v1/runs/{PENDING_RUN}/rqgm/registry"))

    def chained(seq: int, prev_hash: str, event_type: str, payload: dict):
        return json.dumps({
            "schema_version": 1,
            "event_id": f"evt_{seq:06d}",
            "event_type": event_type,
            "payload": payload,
            "event_hash": v1_rqgm._hash12(v1_rqgm._canonical_json(payload)),
            "prev_event_hash": prev_hash,
            "ts": 0.0,
            "ts_iso": "2026-07-23T09:00:00Z",
        }, ensure_ascii=False)

    # A chain-valid but UNCOMMITTED tail: prepare + a status change, no
    # commit — the crash-recovery rule must ignore both.
    l1 = chained(
        len(lines), prev, "epoch_transaction_prepare",
        {"transition_id": "transition_001_to_002"},
    )
    prev2 = json.loads(l1)["event_hash"]
    l2 = chained(
        len(lines) + 1, prev2, "prompt_status_change",
        {
            "prompt_id": "utility_policy_prompt_v2",
            "rule_id": "T20",
            "from_status": "probationary_active",
            "to_status": "retired",
            "transition_id": "transition_001_to_002",
        },
    )
    with open(trans_path, "a", encoding="utf-8") as fh:
        fh.write(l1 + "\n" + l2 + "\n")

    after = _strip(_get(f"/api/v1/runs/{PENDING_RUN}/rqgm/transitions"))
    reg_after = _strip(_get(f"/api/v1/runs/{PENDING_RUN}/rqgm/registry"))
    # No new entry, chain still verifies; the parsed region did grow.
    assert after["total_entries"] == before["total_entries"] == 3
    assert [e["byte_offset"] for e in after["entries"]] == [
        e["byte_offset"] for e in before["entries"]
    ]
    assert after["chain_ok"] is True
    assert after["source_revision"] > before["source_revision"]
    # Current state ignores the pending retirement...
    by_id = {p["prompt_id"]: p for p in reg_after["prompts"]}
    assert by_id["utility_policy_prompt_v2"]["status"] == (
        "probationary_active"
    )
    ov = _get(f"/api/v1/runs/{PENDING_RUN}/rqgm/overview")
    assert ov["current_epoch"] == "epoch_001"
    # ...while the rollup (as-of the pre-append tail) honestly reads as no
    # longer covering the physical tail — same posture as the store's
    # snapshot-vs-replay validation.
    assert reg_after["verified"] is False
    assert reg_before["verified"] is True


# ── corrupt fixtures: 200 + integrity flags, never a crash ───────────────


def test_broken_chain_flips_integrity_flag(ckpt):
    r = _get(f"/api/v1/runs/{BROKEN_RUN}/rqgm/overview")
    assert r["integrity"]["transitions_chain_ok"] is False
    assert r["integrity"]["registry_verified"] is True
    assert any("chain broken" in s for s in r["degraded_reasons"])
    page = _get(f"/api/v1/runs/{BROKEN_RUN}/rqgm/transitions")
    assert page["chain_ok"] is False
    assert any("chain broken" in s for s in page["degraded_reasons"])
    # The data itself is still served, flagged (degraded representation).
    assert page["total_entries"] == 3


def test_registry_mismatch_flips_verified(ckpt):
    r = _get(f"/api/v1/runs/{STALE_RUN}/rqgm/overview")
    assert r["integrity"]["registry_verified"] is False
    assert r["integrity"]["transitions_chain_ok"] is True
    assert any("as_of_event_hash" in s for s in r["degraded_reasons"])
    reg = _get(f"/api/v1/runs/{STALE_RUN}/rqgm/registry")
    assert reg["verified"] is False
    assert reg["rollup_as_of_event_hash"] != reg["replay_tail_event_hash"]


def test_truncated_transitions_falls_back_to_committed_state(ckpt):
    _base, manifests = ckpt
    m = manifests[TRUNC_RUN]
    r = _get(f"/api/v1/runs/{TRUNC_RUN}/rqgm/overview")
    # The torn line was the boundary commit: committed replay ends at
    # epoch_000 under the OLD policy, while the (stale, ahead) snapshot
    # rollup no longer verifies — surfaced, not guessed over.
    assert r["current_epoch"] == "epoch_000"
    assert r["utility_policy_hash"] == m["policy_hash_v1"]
    assert r["integrity"]["transitions_chain_ok"] is True
    assert r["integrity"]["registry_verified"] is False
    assert any("snapshot" in s for s in r["degraded_reasons"])


# ── node lineage: the two channels, never merged ─────────────────────────


def test_lineage_penalty_node_two_channels(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    node = m["penalty_node_ids"][0]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/nodes/{node}/lineage")

    # channel separation: disjoint source vocabularies, penalty values never
    # appear in the policy channel and frontier facts never in the penalty
    # channel — two series, no merge.
    assert {o["source"] for o in r["penalty_channel"]} <= {
        "node_metrics", "utility_record",
    }
    assert {o["source"] for o in r["policy_channel"]} <= {
        "node_metrics", "erasure_event",
    }
    for o in r["policy_channel"]:
        assert not (
            {"base_score", "penalty", "final_score",
             "_pre_penalty_score", "_validated_attack_penalty"}
            & set(o["values"])
        )
    for o in r["penalty_channel"]:
        assert "frontier_removed" not in o["values"]
        assert o["policy_hash"] == m["current_policy_hash"]

    by_source = {o["source"]: o for o in r["penalty_channel"]}
    utl = m["utility_record"]
    obs = by_source["utility_record"]
    assert obs["record_id"] == "utl_000000"
    assert obs["values"]["base_score"] == utl["base_score"]
    assert obs["values"]["penalty"] == utl["penalty"]
    assert obs["values"]["final_score"] == utl["final_score"]
    assert obs["state"] == "computed"
    # The penalty references ONLY the adjudicated vat id (invariant 8).
    assert obs["validated_attack_ids"] == ["vat_000000"]
    assert "atk_000000" not in obs["validated_attack_ids"]
    sent = by_source["node_metrics"]
    assert sent["values"]["_pre_penalty_score"] == utl["base_score"]
    assert sent["values"]["_validated_attack_penalty"] == utl["penalty"]

    # Raw vs validated: explicit kinds; the raw entry is structurally
    # scoreless (no score/penalty/confidence key exists at all).
    assert [a["kind"] for a in r["raw_attacks"]] == ["raw"]
    raw = r["raw_attacks"][0]
    assert set(raw) == {
        "kind", "record_id", "adversary_type", "severity_claimed",
        "status", "epoch_id", "target_node_id",
    }
    assert raw["record_id"] == "atk_000000"
    vat = r["validated_attacks"][0]
    assert vat["kind"] == "validated" and vat["record_id"] == "vat_000000"
    assert vat["affected_components"] == ["generator"]
    assert vat["target_component_id"] is None  # structurally inert chain


def test_lineage_invalidated_node(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    node = m["invalidated_node_id"]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/nodes/{node}/lineage")
    assert r["penalty_channel"] == []
    assert r["raw_attacks"] == [] and r["validated_attacks"] == []
    by_source: dict[str, list] = {}
    for o in r["policy_channel"]:
        by_source.setdefault(o["source"], []).append(o)
    (sent,) = by_source["node_metrics"]
    # Stamped under the RETIRED policy; invalidated, never re-scaled.
    assert sent["policy_hash"] == m["policy_hash_v1"]
    assert sent["state"] == "invalidated"
    assert sent["values"]["_stale_reason"] == "utility_invalidated"
    assert sent["record_id"] == "erase_00000"
    erasure_obs = [
        o for o in by_source["erasure_event"]
        if o["values"].get("invalidated")
    ]
    assert len(erasure_obs) == 1
    assert erasure_obs[0]["record_id"] == "erase_00000"
    assert erasure_obs[0]["state"] == "invalidated"
    assert erasure_obs[0]["policy_hash"] == m["policy_hash_v1"]
    frontier_obs = [
        o for o in by_source["erasure_event"]
        if o["values"].get("frontier_removed")
    ]
    assert len(frontier_obs) == 1
    assert frontier_obs[0]["record_id"] == "rebuild_00000"
    assert frontier_obs[0]["state"] is None  # frontier fact, not a score state


def test_lineage_unscored_node_is_empty_not_404(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    unscored = next(
        nid for nid in (f"node_{i:05d}" for i in range(10))
        if nid not in m["scored_node_ids"]
    )
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/nodes/{unscored}/lineage")
    assert r["penalty_channel"] == [] and r["policy_channel"] == []


def test_lineage_unknown_node_404(ckpt):
    _assert_404(
        dispatch("GET", f"/api/v1/runs/{RQGM_RUN}/rqgm/nodes/nope/lineage")
    )


# ── score rewrites ────────────────────────────────────────────────────────


def test_score_rewrites_join(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/score-rewrites")
    assert r["total_entries"] == 1 and r["next_cursor"] is None
    (e,) = r["entries"]
    assert e["rewrite_id"] == "rewrite_transition_000_to_001"
    assert e["transition_id"] == "transition_000_to_001"
    assert e["epoch_id"] == "epoch_001"
    assert e["from_policy_hash"] == m["policy_hash_v1"]
    assert e["to_policy_hash"] == m["policy_hash_v2"]
    assert e["invalidated_node_ids"] == [m["invalidated_node_id"]]
    assert e["invalidated_node_count"] == 1
    assert e["recompute_node_ids"] == []
    assert e["frontier_removed_node_ids"] == [m["invalidated_node_id"]]
    assert e["frontier_reinstated_node_ids"] == []
    # T6/T20 status-change events + the erasure/rebuild audit records.
    assert "erase_00000" in e["source_event_ids"]
    assert "rebuild_00000" in e["source_event_ids"]
    assert sum(
        1 for s in e["source_event_ids"] if s.startswith("evt_")
    ) == 2
    assert r["degraded_reasons"] == []


# ── policies ──────────────────────────────────────────────────────────────


def test_policies(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/policies")
    assert r["current_policy_hash"] == m["policy_hash_v2"]
    by_id = {p["prompt_id"]: p for p in r["policies"]}
    assert set(by_id) == {
        "utility_policy_prompt_v1", "utility_policy_prompt_v2",
    }
    v1p, v2p = (
        by_id["utility_policy_prompt_v1"], by_id["utility_policy_prompt_v2"]
    )
    assert v1p["status"] == "retired" and v1p["adopted_via"] is None
    assert v2p["status"] == "probationary_active"
    assert v2p["adopted_via"] == "transition_000_to_001"
    for p in (v1p, v2p):
        # The write-once body: exactly the 5 hashed keys, and its canonical
        # JSON re-seals to the registered hash (one value, three names).
        assert set(p["body"]) == {
            "composite", "axis_weights", "frontier_score",
            "depth_penalty_lambda", "ucb_c",
        }
        assert hash12(canonical_json(p["body"])) == p["policy_hash"]
    assert v1p["epochs_used"] == ["epoch_000"]
    assert v2p["epochs_used"] == ["epoch_001"]
    assert r["degraded_reasons"] == []


def test_policies_refuse_mutated_body(ckpt):
    base, _ = ckpt
    # A dedicated throwaway checkpoint: in-place mutation of a write-once
    # policy body must be refused (body withheld + degraded reason).
    run = "20260723000008_mutated"
    rqgm_factory.make_rqgm_checkpoint(
        base / run, nodes=10, epochs=2, seed=0
    )
    body_path = base / run / "rqgm_prompts" / "utility_policy_prompt_v2.json"
    body = json.loads(body_path.read_text(encoding="utf-8"))
    body["ucb_c"] = 99.0
    body_path.write_text(json.dumps(body), encoding="utf-8")
    r = _get(f"/api/v1/runs/{run}/rqgm/policies")
    by_id = {p["prompt_id"]: p for p in r["policies"]}
    assert by_id["utility_policy_prompt_v2"]["body"] is None
    assert by_id["utility_policy_prompt_v1"]["body"] is not None
    assert any(
        "in-place mutation is prohibited" in s for s in r["degraded_reasons"]
    )


# ── Wave 4b: epochs ───────────────────────────────────────────────────────


def test_epochs_list_happy(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs")
    assert [e["epoch_id"] for e in r["epochs"]] == [
        "epoch_000", "epoch_001",
    ]
    assert r["current_epoch"] == "epoch_001"
    e0, e1 = r["epochs"]
    # Cross-epoch comparability: each row carries its OWN policy hash and
    # the two differ across the rewrite — the FE can refuse naive
    # comparison (plan 08: compare only after compatibility is confirmed).
    assert e0["utility_policy_hash"] == m["policy_hash_v1"]
    assert e1["utility_policy_hash"] == m["policy_hash_v2"]
    assert e0["utility_policy_hash"] != e1["utility_policy_hash"]
    # epoch_000 was closed by the committed boundary: real event counts.
    assert e0["boundary_committed"] is True
    assert e0["closed_by_transition_id"] == "transition_000_to_001"
    assert e0["transition_counts"] == {
        "adoptions": 1,
        "sanctions": 0,
        "retirements": 1,
        "bans": 0,
        # No epoch_transition audit record supplies the fallbacks array in
        # the fixture: absent stays None, never a fabricated 0.
        "fallbacks": None,
    }
    # epoch_001 is still open: no boundary, so no counts at all (a boundary
    # that has not happened is never rendered as zero activity).
    assert e1["boundary_committed"] is False
    assert e1["closed_by_transition_id"] is None
    assert e1["transition_counts"] is None
    assert e1["opened_by_transition_id"] == "transition_000_to_001"
    assert e0["opened_by_transition_id"] is None  # standalone founding open
    assert r["degraded_reasons"] == []


def test_epochs_list_ordering_deterministic(ckpt):
    a = _strip(_get(f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs"))
    b = _strip(_get(f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs"))
    assert a == b
    # Replay order is truth-log file order: strictly increasing open events.
    events = [e["opened_at_event"] for e in a["epochs"]]
    assert events == sorted(events)


def test_epoch_detail_closed_epoch(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs/epoch_000")
    assert r["epoch"]["epoch_id"] == "epoch_000"
    assert r["epoch_seq"] == 0
    assert r["node_count_at_open"] == 1
    assert r["previous_epoch_id"] is None
    assert r["active_prompt_hashes"]["utility_policy"] == m["policy_hash_v1"]
    # Boundary transaction refs: standalone founding open + the committed
    # closing transaction.
    assert r["opening_transaction"]["kind"] == "standalone"
    assert r["closing_transaction"]["kind"] == "transaction"
    assert r["closing_transaction"]["transition_id"] == (
        "transition_000_to_001"
    )
    # Policy body via the policies reader: the write-once v1 body, and its
    # canonical JSON re-seals to this epoch's policy hash.
    assert r["policy_prompt_id"] == "utility_policy_prompt_v1"
    assert hash12(canonical_json(r["policy_body"])) == m["policy_hash_v1"]
    assert r["governance_report_present"] is True
    assert r["governance_report_record_id"] == "govreport_epoch_000"
    assert r["degraded_reasons"] == []


def test_epoch_detail_open_epoch(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs/epoch_001")
    assert r["epoch"]["boundary_committed"] is False
    assert r["closing_transaction"] is None
    assert r["opening_transaction"]["transition_id"] == (
        "transition_000_to_001"
    )
    assert r["previous_epoch_id"] == "epoch_000"
    assert r["policy_prompt_id"] == "utility_policy_prompt_v2"
    assert hash12(canonical_json(r["policy_body"])) == m["policy_hash_v2"]


def test_epoch_detail_unknown_404(ckpt):
    _assert_404(
        dispatch("GET", f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs/epoch_999")
    )


def test_epoch_route_extracts_both_params():
    handler, params, _t = match("/api/v1/runs/r%201/rqgm/epochs/epoch_000")
    assert handler.__name__ == "_handle_rqgm_epoch_detail"
    assert params == {"run_id": "r 1", "epoch_id": "epoch_000"}
    handler2, params2, _t2 = match("/api/v1/runs/r1/rqgm/epochs")
    assert handler2.__name__ == "_handle_rqgm_epochs"
    assert params2 == {"run_id": "r1"}


# ── Wave 4b: evolution ────────────────────────────────────────────────────


def test_evolution_raw_vs_adopted(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/evolution")
    assert r["evolution_present"] is True
    assert r["meta_outputs_present"] is True
    by_kind = {e["kind"]: e for e in r["entries"]}
    assert set(by_kind) == {"prompt", "utility_policy", "meta"}

    # RAW candidate: proposed, never validated, never registered — its own
    # status stays candidate vocabulary and the adoption join says no.
    raw = by_kind["prompt"]
    assert raw["candidate_id"] == m["prompt_candidate_id"]
    assert raw["status"] == "candidate"
    assert raw["validation_record_count"] == 0
    assert raw["adopted"] is False
    assert raw["adopted_via"] is None and raw["adopted_prompt_id"] is None
    assert raw["parent_ref"] == "adversary_overclaim_prompt_v1"
    assert raw["proposed_prompt_hash"] and raw["proposed_policy_hash"] is None

    # ADOPTED utility-policy candidate: adoption is derived ONLY from the
    # committed registry replay (the citing transition rides along), never
    # from the candidate record itself — whose own status is still
    # 'candidate'.
    upc = by_kind["utility_policy"]
    assert upc["candidate_id"] == m["utility_candidate_id"]
    assert upc["status"] == "candidate"
    assert upc["proposed_policy_hash"] == m["policy_hash_v2"]
    assert upc["validation_record_count"] == 1
    assert upc["validation_passed_count"] == 1
    assert upc["adopted"] is True
    assert upc["adopted_via"] == "transition_000_to_001"
    assert upc["adopted_prompt_id"] == "utility_policy_prompt_v2"
    assert upc["parent_ref"] == "utility_policy_prompt_v1"

    # META output: inert provenance — not an adoptable candidate at all.
    meta = by_kind["meta"]
    assert meta["record_id"] == m["meta_output_id"]
    assert meta["adopted"] is None
    assert meta["output_kind"] == "prompt_candidate_suggestion"
    assert meta["target_role"] == "adversary"
    assert meta["proposed_prompt_hash"] is None
    assert meta["proposed_policy_hash"] is None
    assert meta["source"] == "meta_outputs"

    # Deep-link shape: prompt_evolution entries carry their byte offsets in
    # file order.
    evo = [e for e in r["entries"] if e["source"] == "prompt_evolution"]
    offsets = [e["source_offset"] for e in evo]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)
    assert r["degraded_reasons"] == []


def test_evolution_candidate_without_rewrite_stays_unadopted(ckpt):
    _base, manifests = ckpt
    m = manifests[NOREW_RUN]
    r = _get(f"/api/v1/runs/{NOREW_RUN}/rqgm/evolution")
    upc = next(e for e in r["entries"] if e["kind"] == "utility_policy")
    # Same proposal, but no committed adoption transition exists: the join
    # must answer False (a validated candidate is still not an adopted
    # policy).
    assert upc["validation_passed_count"] == 1
    assert upc["adopted"] is False
    assert upc["adopted_via"] is None and upc["adopted_prompt_id"] is None
    assert m["current_policy_hash"] == m["policy_hash_v1"]


def test_evolution_missing_log_is_explicit_absence(ckpt):
    r = _get(f"/api/v1/runs/{NOEVO_RUN}/rqgm/evolution")
    assert r["evolution_present"] is False
    assert r["meta_outputs_present"] is False
    assert r["entries"] == []


# ── Wave 4b: paper archive ────────────────────────────────────────────────


def test_paper_archive_happy(ckpt):
    _base, manifests = ckpt
    m = manifests[FULLPAPER_RUN]
    r = _get(f"/api/v1/runs/{FULLPAPER_RUN}/rqgm/paper-archive")
    assert r["state_present"] is True
    assert r["paper_mode"] == "rqgm_archive"
    assert r["mode_source"] == "config"
    assert r["rqgm_paper_enabled"] is True
    assert r["paper_epoch_fingerprint"] == m["paper_utility_policy_hash"]
    assert r["archive_present"] is True
    assert r["epochs"] == m["paper_epoch_ids"]
    assert r["draft_count"] == len(m["paper_draft_ids"]) == 4
    assert r["anchor"] == {"enabled": True, "corpus_present": True}
    sp = r["self_preference"]
    assert sp["stat_present"] is True
    assert sp["margin"] == m["self_preference_margin"]
    assert sp["sample_count"] == len(m["anchor_case_ids"])
    # Summary scalars only — per-case scores never ride the payload.
    assert "per_case_scores" not in sp
    assert r["winner"] == {
        "node_id": m["paper_winner_node_id"], "materialized": True,
    }
    assert r["degraded_reasons"] == []


def test_paper_archive_absent_flags_never_fabricated_zeros(ckpt):
    # The standard RQGM fixture has NO paper layer: every absence is an
    # explicit flag; a missing archive is draft_count=None (never 0), and
    # absence of the state file means paper mode 'linear' by the source
    # contract — with state_present=False keeping the derivation honest.
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/paper-archive")
    assert r["state_present"] is False
    assert r["paper_mode"] == "linear"
    assert r["mode_source"] is None and r["rqgm_paper_enabled"] is None
    assert r["archive_present"] is False
    assert r["draft_count"] is None
    assert r["epochs"] == []
    assert r["anchor"] == {"enabled": None, "corpus_present": False}
    assert r["self_preference"] == {
        "stat_present": False,
        "epoch_id": None,
        "margin": None,
        "ai_mean": None,
        "human_mean": None,
        "sample_count": None,
    }
    assert r["winner"] == {"node_id": None, "materialized": False}


def test_paper_archive_state_without_mode_is_degraded(ckpt):
    # PAPER_RUN's hand-written state file has no paper_mode: the reader
    # answers 200 with paper_mode=None + a degraded reason (never guessed).
    r = _get(f"/api/v1/runs/{PAPER_RUN}/rqgm/paper-archive")
    assert r["state_present"] is True
    assert r["paper_mode"] is None
    assert any("paper_mode" in s for s in r["degraded_reasons"])


# ── audit ─────────────────────────────────────────────────────────────────


def test_audit_listing_filters_and_expand(ckpt):
    _base, manifests = ckpt
    m = manifests[RQGM_RUN]
    r = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/audit")
    assert [e["event_type"] for e in r["entries"]] == [
        "governance_report", "selective_erasure", "frontier_rebuild",
        "governance_report",
    ]
    assert r["chain_ok"] is True and r["total_entries"] == 4
    erasure = r["entries"][1]
    # Arrays summarized as counts; payload only on expand.
    assert erasure["summary"]["invalidated_node_ids_count"] == 1
    assert "invalidated_node_ids" not in erasure["summary"]
    assert erasure["payload"] is None

    by_event_type = _get(
        f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?record_type=selective_erasure"
        f"&expand=1"
    )
    assert len(by_event_type["entries"]) == 1
    assert by_event_type["entries"][0]["payload"] == m["erasure_event"]

    by_record_type = _get(
        f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?record_type=FrontierRebuildEvent"
    )
    assert [e["record_id"] for e in by_record_type["entries"]] == [
        "rebuild_00000",
    ]

    by_epoch = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?epoch=epoch_000")
    assert [e["record_id"] for e in by_epoch["entries"]] == [
        "govreport_epoch_000", "erase_00000",
    ]


def test_audit_cursor_paging_no_gap_no_duplicate(ckpt):
    full = _get(f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?limit=100")
    seen: list[int] = []
    cursor, pages = 0, 0
    while True:
        r = _get(
            f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?cursor={cursor}&limit=1"
        )
        seen.extend(e["byte_offset"] for e in r["entries"])
        pages += 1
        if r["next_cursor"] is None:
            break
        cursor = r["next_cursor"]
    assert pages == 4
    assert seen == [e["byte_offset"] for e in full["entries"]]
    assert len(seen) == len(set(seen))


# ── query validation ──────────────────────────────────────────────────────


def test_invalid_cursor_and_limit_are_400(ckpt):
    for path in (
        f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions?cursor=abc",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions?cursor=-1",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?limit=0",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?limit=101",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/score-rewrites?cursor=x",
    ):
        r = dispatch("GET", path)
        assert r["_status"] == 400
        assert r["error"]["code"] == "invalid_request"


# ── routing + read-only surface ───────────────────────────────────────────


def test_lineage_route_extracts_both_params():
    handler, params, _t = match("/api/v1/runs/r%201/rqgm/nodes/n1/lineage")
    assert handler.__name__ == "_handle_rqgm_node_lineage"
    assert params == {"run_id": "r 1", "node_id": "n1"}


def test_rqgm_surface_is_get_only():
    # Plan 08: no direct governance mutation endpoint may exist in v1.
    from ari.viz.v1.router import ROUTES

    for method, template, _h in ROUTES:
        if "/rqgm/" in template:
            assert method == "GET", template


def test_get_side_effect_freeness(ckpt):
    base, manifests = ckpt
    m = manifests[RQGM_RUN]
    node = m["penalty_node_ids"][0]
    before_files = _dir_digest(base / RQGM_RUN)
    before_env = dict(os.environ)
    for path in (
        f"/api/v1/runs/{RQGM_RUN}/rqgm/capabilities",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/overview",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/registry",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/transitions?expand=1",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/audit?expand=1&epoch=epoch_000",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/policies",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/score-rewrites",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/nodes/{node}/lineage",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/epochs/epoch_000",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/evolution",
        f"/api/v1/runs/{RQGM_RUN}/rqgm/paper-archive",
    ):
        _get(path)
    assert _dir_digest(base / RQGM_RUN) == before_files
    assert dict(os.environ) == before_env
