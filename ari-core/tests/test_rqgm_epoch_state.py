"""RQGM Task 02 — structures, vocabulary, and hash discipline
(docs/reference/rqgm_schemas.md §Id and hash discipline /
§State and event-log schemas (Task 02)).

Covers ``ari.rqgm.events`` (canonical_json byte-golden pins, hash12 reuse,
id formats, closed vocabularies), ``ari.rqgm.registry`` (prompt-hash
equivalence with ``load_versioned``, no-setter storage rule, active-set
resolution), and ``ari.rqgm.state`` (frozen ``EpochState``, deterministic
``epoch_fingerprint``/``utility_policy_hash`` with wall-clock excluded).

No test calls an LLM; everything here is pure-stdlib deterministic (P2).
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ari.rqgm.events import (
    ACTIVE_STATUSES,
    EMERGENCY_EVENT_TYPE,
    EVENT_TYPES,
    EVOLVABLE_ROLES,
    FIXED_ROLES,
    GOVERNANCE_ACTOR_ROLES,
    ROLES,
    STATUS_VALUES,
    TIERS,
    TransitionEvent,
    canonical_json,
    expected_event_hash,
    finalize_event,
    format_component_id,
    format_epoch_id,
    format_event_id,
    format_prompt_id,
    format_transition_id,
    hash12,
    payload_hash,
)
from ari.rqgm.registry import (
    ComponentEntry,
    ComponentRegistry,
    GovernedPromptEntry,
    GovernedPromptRegistry,
    apply_registry_event,
    build_prompt_registration_payload,
)
from ari.rqgm.state import (
    capture_utility_policy,
    execution_fingerprint,
    epoch_fingerprint,
    epoch_state_from_payload,
    epoch_state_payload,
    freeze_epoch,
    policy_fingerprint,
)


def _fixed_registries():
    """Deterministic two-entry registries used by the golden-hash tests."""
    comps: dict = {}
    prompts: dict = {}
    apply_registry_event(
        comps, prompts, "component_registered",
        {"component_id": "reviewer_v1", "role": "reviewer",
         "tier": "institutional", "status": "active",
         "prompt_id": "reviewer_prompt_v1", "epoch_id": "epoch_000"},
    )
    apply_registry_event(
        comps, prompts, "prompt_registered",
        {"prompt_id": "reviewer_prompt_v1", "role": "reviewer",
         "status": "active", "prompt_hash": "a" * 12,
         "prompt_sha256": "a" * 64,
         "source": {"kind": "committed_template", "key": "evaluator/peer_review"},
         "epoch_id": "epoch_000"},
    )
    return SimpleNamespace(
        components=ComponentRegistry(comps),
        prompts=GovernedPromptRegistry(prompts),
    )


def _fixed_cfg():
    return SimpleNamespace(
        evaluator=SimpleNamespace(
            composite="harmonic_mean", axis_weights={"novelty": 1.0}
        ),
        bfts=SimpleNamespace(
            frontier_score="scientific_plus_diversity",
            depth_penalty_lambda=0.05,
            ucb_c=0.5,
        ),
    )


# ── canonical hashing: byte-golden pins (plan §10 mitigation) ────────────────


def test_canonical_json_byte_golden():
    assert canonical_json({"b": 1, "a": [1, 2], "s": "µ"}) == \
        '{"a":[1,2],"b":1,"s":"µ"}'
    # No whitespace, sorted keys, non-ASCII NOT escaped.
    assert canonical_json({}) == "{}"
    assert canonical_json([["x", "y"]]) == '[["x","y"]]'


def test_payload_hash_byte_golden():
    assert hash12('{"a":[1,2],"b":1,"s":"µ"}') == "c031dc421ab9"
    assert payload_hash({"b": 1, "a": [1, 2], "s": "µ"}) == "c031dc421ab9"
    assert payload_hash({"transition_id": "transition_000_to_001"}) == \
        "5b365f758439"


def test_hash12_is_the_provenance_scheme_no_second_scheme():
    """`prompt_hash` IS load_versioned's sha256[:12] (plan 02 §5.4)."""
    import ari.prompts._provenance as prov
    from ari.rqgm import events

    assert events.hash12 is prov.hash12
    assert hash12("x") == hashlib.sha256(b"x").hexdigest()[:12]


# ── id formats (§5.5) ────────────────────────────────────────────────────────


def test_id_formats_match_spec_examples():
    assert format_epoch_id(0) == "epoch_000"
    assert format_epoch_id(4) == "epoch_004"
    assert format_transition_id(3, 4) == "transition_003_to_004"
    assert format_transition_id(4, 5) == "transition_004_to_005"
    assert format_event_id(0) == "evt_000000"
    assert format_event_id(42) == "evt_000042"
    assert format_component_id("reviewer", 3) == "reviewer_v3"
    assert format_prompt_id("reviewer", 4) == "reviewer_prompt_v4"


# ── vocabulary (owned here; Task 09 owns the transition table) ───────────────


def test_status_lifecycle_vocabulary_closed_set():
    assert STATUS_VALUES == (
        "candidate", "validated", "shadow", "probationary_active", "active",
        "warning", "probation", "quarantine", "retired", "banned",
    )
    assert set(ACTIVE_STATUSES) == {"active", "probationary_active"}
    assert TIERS == ("fixed", "institutional", "meta")
    # #78b: ROLES is a three-way partition (evolvable / governance-actor /
    # fixed).
    assert (
        set(EVOLVABLE_ROLES) | set(GOVERNANCE_ACTOR_ROLES) | set(FIXED_ROLES)
        == set(ROLES)
    )
    assert "generator" in EVOLVABLE_ROLES and "judge" in EVOLVABLE_ROLES
    assert "governance_judge" in GOVERNANCE_ACTOR_ROLES
    assert "constitutional_kernel" in FIXED_ROLES


def test_event_types_closed_set():
    assert EVENT_TYPES == (
        "epoch_transaction_prepare", "component_registered",
        "prompt_registered", "component_status_change",
        "prompt_status_change", "epoch_close", "epoch_open",
        "epoch_transaction_commit", "emergency_quarantine",
    )
    assert EMERGENCY_EVENT_TYPE == "emergency_quarantine"


# ── event envelope: timestamps outside the hash ──────────────────────────────


def test_finalize_event_binds_replay_semantics_but_not_timestamps():
    ev = finalize_event(
        TransitionEvent(event_type="epoch_open", payload={"k": "v"}),
        event_seq=7, prev_event_hash="ab" * 6,
    )
    assert ev.event_id == "evt_000007"
    assert len(ev.event_hash) == 64
    assert ev.event_hash == expected_event_hash(ev)
    assert ev.prev_event_hash == "ab" * 6
    assert ev.ts is not None and ev.ts_iso  # metadata present ...
    # ... but not part of the hashed commitment:
    assert "ts" not in ev.payload and "ts_iso" not in ev.payload
    line = ev.to_line_dict()
    assert list(line) == ["schema_version", "event_id", "event_type",
                          "transaction_id", "payload", "event_hash",
                          "prev_event_hash",
                          "ts", "ts_iso"]
    assert expected_event_hash(dict(line, event_type="epoch_close")) != \
        ev.event_hash
    assert expected_event_hash(dict(line, event_id="evt_000008")) != \
        ev.event_hash
    assert expected_event_hash(dict(line, prev_event_hash="cd" * 6)) != \
        ev.event_hash
    # A frozen envelope cannot be edited after finalization.
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.event_hash = "0" * 12  # type: ignore[misc]


# ── prompt_hash equivalence (§9 test 3) ──────────────────────────────────────


def test_prompt_hash_equals_load_versioned_for_committed_template():
    from ari.prompts import FilesystemPromptLoader

    key = "orchestrator/lineage_decision"
    payload = build_prompt_registration_payload(
        "reviewer_prompt_v1", "reviewer", source_key=key,
        status="active", epoch_id="epoch_000",
    )
    text, version_id = FilesystemPromptLoader().load_versioned(key)
    assert payload["prompt_hash"] == version_id == hash12(text)
    full = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert payload["prompt_sha256"] == full
    assert payload["prompt_hash"] == full[:12]
    assert payload["source"] == {"kind": "committed_template", "key": key}

    # Registered entry resolves back through the loader (delegation).
    comps: dict = {}
    prompts: dict = {}
    apply_registry_event(comps, prompts, "prompt_registered", payload)
    reg = GovernedPromptRegistry(prompts)
    assert reg.resolve_text("reviewer_prompt_v1") == (text, version_id)
    assert reg.active_prompt_hashes() == {"reviewer": version_id}


def test_resolve_text_checkpoint_file_reads_checkpoint_body(
    monkeypatch, tmp_path
):
    """Task 07 landed the ``checkpoint_file`` source: bytes are read from the
    checkpoint root and REFUSED when they no longer hash to the registered
    ``prompt_hash`` (no in-place mutation)."""
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    from ari.rqgm.events import hash12 as _hash12

    body = "evolved generator prompt {goal}\n"
    (tmp_path / "rqgm_prompts").mkdir()
    (tmp_path / "rqgm_prompts" / "g9.md").write_text(body, encoding="utf-8")
    reg = GovernedPromptRegistry({
        "gen_prompt_v9": GovernedPromptEntry(
            prompt_id="gen_prompt_v9", role="generator", status="shadow",
            prompt_hash=_hash12(body), prompt_sha256="0" * 64,
            source={"kind": "checkpoint_file", "path": "rqgm_prompts/g9.md"},
        )
    })
    assert reg.resolve_text(
        "gen_prompt_v9", checkpoint_dir=tmp_path
    ) == (body, _hash12(body))
    # No checkpoint resolvable (arg absent AND run pin unset) → error.
    with pytest.raises(FileNotFoundError):
        reg.resolve_text("gen_prompt_v9")
    # Tampered bytes are refused, never served.
    (tmp_path / "rqgm_prompts" / "g9.md").write_text(
        body + "tampered", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        reg.resolve_text("gen_prompt_v9", checkpoint_dir=tmp_path)
    with pytest.raises(KeyError):
        reg.resolve_text("missing_prompt")


def test_loader_with_divergent_scheme_is_rejected():
    class _BadLoader:
        def load_versioned(self, key):
            return "text", "not-sha256-12"

    with pytest.raises(ValueError):
        build_prompt_registration_payload(
            "p", "reviewer", source_key="x", loader=_BadLoader()
        )


# ── no-setter storage rule (§9 test 5, storage side) ─────────────────────────


def test_registries_expose_no_status_setter():
    for cls in (ComponentRegistry, GovernedPromptRegistry):
        for name in dir(cls):
            assert not name.startswith("set_"), f"{cls.__name__}.{name}"
        assert not hasattr(cls, "register")
    entry = ComponentEntry(
        component_id="reviewer_v1", role="reviewer",
        tier="institutional", status="active",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.status = "banned"  # type: ignore[misc]
    pentry = GovernedPromptEntry(
        prompt_id="p", role="reviewer", status="shadow",
        prompt_hash="0" * 12, prompt_sha256="0" * 64,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        pentry.status = "active"  # type: ignore[misc]


def test_status_changes_only_via_replayed_events():
    comps: dict = {}
    prompts: dict = {}
    apply_registry_event(
        comps, prompts, "component_registered",
        {"component_id": "judge_v1", "role": "judge",
         "tier": "institutional", "status": "candidate"},
    )
    assert comps["judge_v1"].status == "candidate"
    apply_registry_event(
        comps, prompts, "component_status_change",
        {"component_id": "judge_v1", "from_status": "candidate",
         "to_status": "active"},
    )
    assert comps["judge_v1"].status == "active"
    # Emergency quarantine is the sole mid-epoch mutation.
    apply_registry_event(
        comps, prompts, EMERGENCY_EVENT_TYPE,
        {"component_id": "judge_v1", "to_status": "quarantine"},
    )
    assert comps["judge_v1"].status == "quarantine"
    # Unknown ids are skipped, never raised (absence-tolerant replay).
    apply_registry_event(
        comps, prompts, "prompt_status_change",
        {"prompt_id": "ghost", "to_status": "banned"},
    )
    assert "ghost" not in prompts


# ── EpochState freeze (§9 test 4) ────────────────────────────────────────────


def test_epoch_state_is_frozen():
    st = freeze_epoch(_fixed_registries(), _fixed_cfg(),
                      epoch_seq=0, node_count=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.epoch_id = "epoch_999"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.active_components = {}  # type: ignore[misc]
    assert st.record_id == "epochstate_epoch_000"
    assert st.status == "open"


def test_active_set_captured_at_open_does_not_track_registries():
    comps: dict = {}
    prompts: dict = {}
    apply_registry_event(
        comps, prompts, "component_registered",
        {"component_id": "reviewer_v1", "role": "reviewer",
         "tier": "institutional", "status": "active"},
    )
    regs = SimpleNamespace(
        components=ComponentRegistry(comps),
        prompts=GovernedPromptRegistry(prompts),
    )
    st = freeze_epoch(regs, _fixed_cfg(), epoch_seq=1, node_count=5)
    assert st.active_components == {"reviewer": "reviewer_v1"}
    # Later registry evolution must not leak into the frozen epoch.
    apply_registry_event(
        comps, prompts, "component_registered",
        {"component_id": "reviewer_v2", "role": "reviewer",
         "tier": "institutional", "status": "active"},
    )
    regs2 = ComponentRegistry(comps)
    assert regs2.active_set() == {"reviewer": "reviewer_v2"}
    assert st.active_components == {"reviewer": "reviewer_v1"}


def test_epoch_fingerprint_deterministic_and_wall_clock_free():
    regs, cfg = _fixed_registries(), _fixed_cfg()
    a = freeze_epoch(regs, cfg, epoch_seq=3, node_count=17, run_id="fixed_run")
    b = dataclasses.replace(a, created_at="1999-01-01T00:00:00Z")
    # created_at is metadata: same fingerprint despite a different timestamp.
    assert epoch_fingerprint(a) == epoch_fingerprint(b) == a.epoch_fingerprint
    # open→closed does not re-fingerprint the frozen content.
    closed = dataclasses.replace(a, status="closed")
    assert epoch_fingerprint(closed) == a.epoch_fingerprint
    # Golden pins (P2: machine-stable; recomputed from canonical content).
    assert regs.prompts.registry_version() == "852526c4b2fa"
    # Re-pinned 2026-08-03: Tasks 16-19 add three fixed binder/resolver roles
    # to the frozen component vocabulary committed by the epoch identity.
    assert a.epoch_fingerprint == "70b33a359957"
    assert a.policy_fingerprint == policy_fingerprint(a)
    assert a.execution_fingerprint == execution_fingerprint(a)
    assert a.execution_identity["complete"] is False
    assert a.execution_identity["provider_model_revision"] == "unresolved"
    assert a.utility_policy["utility_policy_hash"] == "b192196ced57"
    # Content changes DO change the fingerprint.
    c = dataclasses.replace(a, active_components={"reviewer": "reviewer_v9"})
    assert epoch_fingerprint(c) != a.epoch_fingerprint


def test_epoch_state_payload_roundtrip_excludes_created_at():
    st = freeze_epoch(_fixed_registries(), _fixed_cfg(),
                      epoch_seq=2, node_count=9, run_id="r")
    payload = epoch_state_payload(st)
    assert "created_at" not in payload
    rebuilt = epoch_state_from_payload(payload, created_at="later")
    assert rebuilt.epoch_fingerprint == st.epoch_fingerprint
    assert epoch_fingerprint(rebuilt) == st.epoch_fingerprint
    assert rebuilt.created_at == "later"
    assert rebuilt.active_prompt_hashes == st.active_prompt_hashes
    assert rebuilt.policy_fingerprint == st.policy_fingerprint
    assert rebuilt.execution_fingerprint == st.execution_fingerprint


def test_policy_and_execution_fingerprints_separate_change_classes():
    from ari.config import ARIConfig

    regs = _fixed_registries()
    base = ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})
    model_changed = ARIConfig(
        ari={"mode": "ari_rqgm"}, rqgm={"enabled": True},
        llm={"model": "different-model"},
    )
    policy_changed = ARIConfig(
        ari={"mode": "ari_rqgm"},
        rqgm={"enabled": True, "transition": {"shadow_min_samples": 9}},
    )
    search_changed = ARIConfig(
        ari={"mode": "ari_rqgm"}, rqgm={"enabled": True},
        bfts={"max_depth": 9},
    )
    a = freeze_epoch(regs, base, epoch_seq=0, node_count=0)
    b = freeze_epoch(regs, model_changed, epoch_seq=0, node_count=0)
    c = freeze_epoch(regs, policy_changed, epoch_seq=0, node_count=0)
    d = freeze_epoch(regs, search_changed, epoch_seq=0, node_count=0)
    assert a.policy_fingerprint == b.policy_fingerprint
    assert a.execution_fingerprint != b.execution_fingerprint
    assert a.policy_fingerprint != c.policy_fingerprint
    assert a.execution_fingerprint == c.execution_fingerprint
    assert a.policy_fingerprint == d.policy_fingerprint
    assert a.execution_fingerprint != d.execution_fingerprint
    assert len({a.epoch_fingerprint, b.epoch_fingerprint,
                c.epoch_fingerprint, d.epoch_fingerprint}) == 4


def test_capture_utility_policy_reads_typed_config():
    from ari.config import ARIConfig

    policy = capture_utility_policy(ARIConfig())
    assert policy["composite"] == "harmonic_mean"
    assert policy["frontier_score"] == "scientific_plus_diversity"
    assert policy["depth_penalty_lambda"] == 0.05
    assert policy["ucb_c"] == 0.5
    assert policy["utility_policy_hash"] == payload_hash(
        {k: v for k, v in policy.items() if k != "utility_policy_hash"}
    )
    # Total over pre-RQGM cfg objects (duck-typed getattr).
    assert capture_utility_policy(SimpleNamespace())["composite"] == \
        "harmonic_mean"


def test_registry_version_tracks_status_changes():
    comps: dict = {}
    prompts: dict = {}
    apply_registry_event(
        comps, prompts, "prompt_registered",
        {"prompt_id": "p1", "role": "reviewer", "status": "shadow",
         "prompt_hash": "1" * 12, "prompt_sha256": "1" * 64,
         "source": {"kind": "committed_template", "key": "k"}},
    )
    v1 = GovernedPromptRegistry(prompts).registry_version()
    apply_registry_event(
        comps, prompts, "prompt_status_change",
        {"prompt_id": "p1", "from_status": "shadow", "to_status": "active"},
    )
    v2 = GovernedPromptRegistry(prompts).registry_version()
    assert v1 != v2
    assert GovernedPromptRegistry({}).registry_version() == payload_hash([])


# ── offline guard (mirror test_recorder_is_offline...) ───────────────────────


def test_rqgm_state_layer_is_offline_no_llm_or_network_imports():
    """The RQGM state layer performs zero LLM/network calls and uses no
    randomness in decision logic (P2; plan 02 §9 test 2)."""
    import ari.rqgm as pkg

    for py in sorted(Path(pkg.__file__).parent.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for forbidden in ("import litellm", "import requests", "import urllib",
                          "import socket", "import http", "import random",
                          "from random"):
            assert forbidden not in text, f"{py.name}: {forbidden}"
