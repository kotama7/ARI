"""GAP-1/GAP-3 regression suite — founding registration IS invoked at run
start (``RQGMRuntime._register_founding`` via the first ``ensure_epoch``).

Pre-fix, ``founding_registration_payloads``/``build_founding_specs`` had no
runtime caller: live ``ari_rqgm`` checkpoints ended with an EMPTY
``rqgm_registry.json`` and an epoch whose active sets were ``{}``, so
governance ran on the ``*_v0`` fallback ids and no live component was
enrolled for evolution or degradation. These tests pin the fixed behavior:

* a live-style boot (mode=ari_rqgm, tmp checkpoint) registers the founding
  prompt + component tables through the Task 02 transaction seam;
* ``registry_version`` / ``epoch_fingerprint`` are byte-stable across two
  identical boots (P2);
* resume replays — never re-registers (write-once discipline);
* the governance pipeline resolves REAL registered actor ids for roles with
  founding components — including the whole judiciary now (#78b: auditor /
  evidence_clerk / governance_judge are founding components, so ``*_v0`` is
  only ever the no-registry fallback);
* the adversarial actors resolve their record ``component_id`` from the
  frozen active set, family-guarded, with the ad-hoc ids as fallback.

No test calls a real LLM (P2).
"""

from __future__ import annotations

import json

import pytest

from ari.config import ARIConfig
from ari.rqgm.prompt_spec import (
    FOUNDING_COMPONENT_TABLE,
    FOUNDING_PROMPT_TABLE,
    UTILITY_POLICY_PROMPT_ID,
)
from ari.rqgm.runtime import RQGMRuntime
from ari.rqgm.store import (
    RQGM_REGISTRY_FILENAME,
    RQGM_TRANSITIONS_FILENAME,
    RqgmStateStore,
)


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _cfg() -> ARIConfig:
    return ARIConfig(ari={"mode": "ari_rqgm"}, rqgm={"enabled": True})


def _boot(tmp_path, run_id="founding-boot"):
    rt = RQGMRuntime(_cfg(), checkpoint_dir=tmp_path)
    epoch = rt.ensure_epoch(1, run_id=run_id)
    assert epoch is not None
    return rt, epoch


def _event_types(tmp_path) -> list[str]:
    out = []
    for line in (tmp_path / RQGM_TRANSITIONS_FILENAME).read_text(
        encoding="utf-8"
    ).splitlines():
        if line.strip():
            out.append(json.loads(line)["event_type"])
    return out


# ── live-style boot registers the founding set ──────────────────────────────


def test_live_boot_registers_founding_set(tmp_path):
    _rt, epoch = _boot(tmp_path)
    doc = json.loads((tmp_path / RQGM_REGISTRY_FILENAME).read_text())
    prompt_ids = {p["prompt_id"] for p in doc["prompts"]}
    component_ids = {c["component_id"] for c in doc["components"]}
    # Task 14 (plan 14 §5.3/§8.3): the founding prompt set is the frozen
    # table PLUS the cfg-derived ``utility_policy_prompt_v1`` — the governed
    # score itself. It is deliberately NOT a table row: its bytes depend on
    # the resolved cfg, and FOUNDING_PROMPT_TABLE's contract is "frozen code
    # constants". This is the DECLARED, author-accepted epoch-0 identity
    # change (§8.3): the registry genuinely contains two more governed
    # objects, so registry_version() and the epoch_000 fingerprint move.
    assert prompt_ids == {pid for pid, *_ in FOUNDING_PROMPT_TABLE} | {
        UTILITY_POLICY_PROMPT_ID
    }
    assert component_ids == {cid for cid, *_ in FOUNDING_COMPONENT_TABLE}
    assert all(p["status"] == "active" for p in doc["prompts"])
    assert all(c["status"] == "active" for c in doc["components"])
    # The epoch_000 freeze carries the founding active sets (non-empty).
    assert epoch.epoch_id == "epoch_000"
    assert epoch.active_prompt_hashes  # populated
    # 8 -> 10 roles (§8.3): +policy_mutator (the score's proposer),
    # +utility_policy (the score itself). The utility_policy entry is what
    # makes ``capture_utility_policy`` able to read an ADOPTED policy at all
    # — before Task 14 the role was in neither half of events.ROLES.
    assert set(epoch.active_prompt_hashes) == {
        "adversary", "clean_room_generator", "defender",
        "failure_summary_compressor", "generator", "judge", "policy_mutator",
        "prompt_mutator", "replay_selector", "reviewer", "router",
        "utility_policy",
    }
    assert epoch.active_components == {
        "adversary": "adversary_reproducibility_v1",
        # #78b: the governance judiciary is now founding, so the auditor /
        # evidence_clerk / governance_judge roles appear in the active set with
        # real registered ids — they are inside the impeachment net (P4).
        "auditor": "auditor_v1",
        "clean_room_generator": "clean_room_generator_v1",
        "defender": "defender_v1",
        "evidence_clerk": "evidence_clerk_v1",
        # plan 11 §5.2 items 3-4: the recommendation roles now have a founding
        # component each, so they appear in the boot's active set like every
        # other governed role. The research generator is now also a registered
        # component, closing node-provenance accountability.
        "failure_summary_compressor": "failure_summary_compressor_v1",
        "generator": "generator_v1",
        "governance_judge": "governance_judge_v1",
        "judge": "artifact_judge_v1",
        "policy_mutator": "policy_mutator_v1",
        "prompt_mutator": "prompt_mutator_v1",
        "replay_selector": "replay_selector_v1",
        "router": "proposal_router_v1",
        "utility_policy": "utility_policy_v1",
    }
    assert epoch.registry_version == doc["registry_version"]
    # The identity bridge (§5.3): one value, three names.
    assert epoch.active_prompt_hashes["utility_policy"] == (
        epoch.utility_policy["utility_policy_hash"]
    )


def test_boot_registry_snapshot_validates_against_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    from ari import schemas

    _boot(tmp_path)
    doc = json.loads((tmp_path / RQGM_REGISTRY_FILENAME).read_text())
    jsonschema.validate(doc, schemas.load("rqgm_registry.schema"))


def test_founding_hashes_match_the_loader_scheme(tmp_path):
    """Registered ``prompt_hash`` IS ``load_versioned(key)[1]`` for the
    RQGM-native templates too — one hash scheme, no second implementation."""
    from ari.prompts import FilesystemPromptLoader

    _boot(tmp_path)
    doc = json.loads((tmp_path / RQGM_REGISTRY_FILENAME).read_text())
    # Task 14: the utility_policy row references its body by PATH, not by
    # a loader key (source.kind == "policy") — it has no committed template.
    by_key = {
        p["source"]["key"]: p for p in doc["prompts"] if "key" in p["source"]
    }
    loader = FilesystemPromptLoader()
    for key in ("rqgm/adversary_overclaim", "rqgm/defender",
                "rqgm/judge_adjudication", "governance/auditor"):
        _text, version_id = loader.load_versioned(key)
        assert by_key[key]["prompt_hash"] == version_id
        assert by_key[key]["prompt_sha256"][:12] == version_id


# ── determinism (P2) ─────────────────────────────────────────────────────────


def test_registry_version_stable_across_two_identical_boots(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _rt_a, ep_a = _boot(a, run_id="same-run")
    _rt_b, ep_b = _boot(b, run_id="same-run")
    assert ep_a.registry_version == ep_b.registry_version
    assert ep_a.epoch_fingerprint == ep_b.epoch_fingerprint
    doc_a = json.loads((a / RQGM_REGISTRY_FILENAME).read_text())
    doc_b = json.loads((b / RQGM_REGISTRY_FILENAME).read_text())
    assert doc_a["registry_version"] == doc_b["registry_version"]


def test_runtime_stamps_generator_provenance_once_from_frozen_epoch(tmp_path):
    from ari.orchestrator.node import Node

    rt, epoch = _boot(tmp_path)
    node = Node(id="node_001", parent_id=None, depth=0)

    assert rt.stamp_node_producer(node)
    assert node.producer_component_id == "generator_v1"
    assert node.producer_prompt_hash == epoch.active_prompt_hashes["generator"]
    assert node.producer_epoch_id == epoch.epoch_id

    # The provenance is an issuance-time fact. A later call or live-registry
    # mutation must not rewrite it and transfer old work to a successor.
    node.producer_component_id = "generator_v1"
    original = (
        node.producer_component_id,
        node.producer_prompt_hash,
        node.producer_epoch_id,
    )
    epoch.active_components["generator"] = "generator_v2"
    assert rt.stamp_node_producer(node)
    assert (
        node.producer_component_id,
        node.producer_prompt_hash,
        node.producer_epoch_id,
    ) == original


# ── resume discipline (write-once) ───────────────────────────────────────────


def test_resume_does_not_duplicate_registrations(tmp_path):
    _rt, ep0 = _boot(tmp_path)
    before = _event_types(tmp_path)
    rt2 = RQGMRuntime(_cfg(), checkpoint_dir=tmp_path)
    ep1 = rt2.ensure_epoch(2, run_id="founding-boot")
    assert ep1.epoch_id == ep0.epoch_id
    assert ep1.epoch_fingerprint == ep0.epoch_fingerprint
    after = _event_types(tmp_path)
    assert after == before  # replay-only resume: zero new events
    # +1: the cfg-derived utility_policy row (plan 14 §5.3/§8.3).
    n_prompt_rows = len(FOUNDING_PROMPT_TABLE) + 1
    n_registrations = n_prompt_rows + len(FOUNDING_COMPONENT_TABLE)
    assert after.count("prompt_registered") == n_prompt_rows
    assert after.count("component_registered") == len(
        FOUNDING_COMPONENT_TABLE
    )
    assert after.count("epoch_transaction_prepare") == 1  # founding tx only
    assert len([t for t in after if t.endswith("_registered")]) == \
        n_registrations


def test_pre_founding_checkpoint_resumes_without_registration(tmp_path):
    """A checkpoint whose epoch opened BEFORE this fix (empty registry) must
    resume as-is: replay rebuilds the (empty) registry and the founding
    tables are NOT retro-registered mid-run (write-once, plan-02 freeze)."""
    store = RqgmStateStore()
    legacy = store.open_epoch(tmp_path, _cfg(), node_count=1, run_id="old")
    assert legacy.epoch.active_prompt_hashes == {}
    rt = RQGMRuntime(_cfg(), checkpoint_dir=tmp_path)
    epoch = rt.ensure_epoch(1, run_id="old")
    assert epoch.epoch_id == legacy.epoch.epoch_id
    assert epoch.epoch_fingerprint == legacy.epoch.epoch_fingerprint
    types = _event_types(tmp_path)
    assert types.count("prompt_registered") == 0
    assert types.count("component_registered") == 0


def test_crashed_founding_transaction_is_rerun(tmp_path):
    """A founding prepare without commit is invisible to replay (crash
    recovery), so the next boot re-runs the registration exactly once."""
    from ari.rqgm.events import TransitionEvent
    from ari.rqgm.prompt_spec import founding_registration_payloads

    store = RqgmStateStore()
    tx = store.begin_transaction(tmp_path, "transition_founding")
    tx.__enter__()
    tx.add(TransitionEvent(
        event_type="prompt_registered",
        payload=founding_registration_payloads()[0],
    ))
    # NO commit — simulated crash mid-founding.
    _rt, epoch = _boot(tmp_path)
    assert epoch.active_prompt_hashes  # the re-run founding tx committed
    types = _event_types(tmp_path)
    # abandoned prepare + real founding tx; replay counts only the committed.
    assert types.count("epoch_transaction_prepare") == 2
    assert types.count("epoch_transaction_commit") == 1
    state = store.load_state(tmp_path)
    # +1: the cfg-derived utility_policy row (plan 14 §5.3/§8.3).
    assert len(state.prompts.entries()) == len(FOUNDING_PROMPT_TABLE) + 1


# ── governance actors pick up the REAL registered ids ────────────────────────


def test_governance_actor_ids_resolve_from_founding_registry(tmp_path):
    from ari.rqgm.governance._pipeline import _actor_id
    from ari.rqgm.governance._records import (
        AUDITOR_ROLE,
        DEFENDER_ROLE,
        EVIDENCE_CLERK_ROLE,
        GOVERNANCE_JUDGE_ROLE,
    )

    rt, _epoch = _boot(tmp_path)
    components = rt.state.components
    # Role with a founding component: the REAL registered id.
    assert _actor_id(components, DEFENDER_ROLE) == "defender_v1"
    # #78b: the governance judiciary is now founding too, so every actor
    # resolves to its REAL registered ``*_v1`` id (was ``*_v0``) — the whole
    # judiciary is inside the impeachment net (P3/P4). The ``*_v0`` fallbacks
    # survive only for a no-registry boot (simple_bfts / stubs).
    assert _actor_id(components, AUDITOR_ROLE) == "auditor_v1"
    assert _actor_id(components, EVIDENCE_CLERK_ROLE) == "evidence_clerk_v1"
    assert _actor_id(components, GOVERNANCE_JUDGE_ROLE) == \
        "governance_judge_v1"


# ── adversarial actors resolve component ids from the frozen active set ─────


def test_adversarial_actors_resolve_registered_component_ids(tmp_path):
    from ari.rqgm.adversarial import AdversarialRound

    rt, epoch = _boot(tmp_path)
    round_ = AdversarialRound(
        rt.cfg.rqgm.adversarial,
        checkpoint_dir=tmp_path,
        epoch_state=lambda: rt.current_epoch,
    )
    assert round_._active_components() == epoch.active_components
    # Family-guarded resolution: the frozen active id wins within its own
    # versioned family; foreign same-role ids never leak across actors.
    assert round_.defender._component_id("defender", "defender_v1") == \
        "defender_v1"
    assert round_.judge._component_id("judge", "artifact_judge_v1") == \
        "artifact_judge_v1"
    assert round_.engine._component_id(
        "adversary", "adversary_reproducibility_v1"
    ) == "adversary_reproducibility_v1"
    # A non-rollup-winner adversary type keeps its own deterministic id
    # (the active rollup winner belongs to another family).
    assert round_.engine._component_id(
        "adversary", "adversary_overclaim_v1"
    ) == "adversary_overclaim_v1"
    # Unregistered role → fallback id untouched.
    assert round_.engine._component_id("generator", "ghost_v1") == "ghost_v1"


def test_component_id_resolution_follows_evolution(tmp_path):
    """When a later epoch freezes an evolved family member as the active
    component, the actor's records carry the evolved id (fallback only
    while the family is absent)."""
    from ari.rqgm.adversarial.engine import Defender

    active = {"defender": "defender_v3"}
    actor = Defender(active_components=lambda: active)
    assert actor._component_id("defender", "defender_v1") == "defender_v3"
    # Absent map (no epoch open yet) → deterministic fallback.
    bare = Defender()
    assert bare._component_id("defender", "defender_v1") == "defender_v1"
    # A failing lookup degrades to the fallback, never raises.
    def _boom():
        raise RuntimeError("no state")

    failing = Defender(active_components=_boom)
    assert failing._component_id("defender", "defender_v1") == "defender_v1"
