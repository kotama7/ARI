"""RQGM Task 07 — candidate lifecycle, PromptMutator, budgets, shadow, smoke
(docs/reference/rqgm_schemas.md §Prompt-evolution schemas (Task 07) — the
monotonic stage ladder and the born-`candidate` / no-instant-activation rule;
docs/reference/configuration.md §``rqgm.prompt_evolution`` — candidate caps /
§``rqgm.shadow`` — shadow live-evaluation sampling).

Covers: monotonic stage order (skipping rejected), terminal schema_dry_run
failure, no adoption without all six stage records, the founding-spec
exception as the sole active-on-creation path, in-place-mutation rejection,
the PromptMutator's write-surface audit (no registry access), per-epoch
candidate budgets, deterministic shadow sampling + caps + observation-only
records, defaults parity for the new config blocks, and the `ari_rqgm`
smoke: bootstrap → mutation candidate → six stages (stub LLM + real
AdversarialReplayPool) → adoption request handed to a stubbed transition
engine → provenance rows with populated `prompt_version` /
`prompt_registry_version`.

No test calls a real LLM: mutators/evaluators/judges are deterministic
fakes (P2).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ari.config import (
    ARIConfig,
    RQGMPromptEvolutionConfig,
    RQGMShadowConfig,
)
from ari.rqgm.events import TransitionEvent, hash12
from ari.rqgm.prompt_evolution import (
    STAGES,
    CandidateValidationPipeline,
    PromptMutator,
    build_adoption_request,
    candidate_budget_reason,
    load_prompt_evolution_log,
    record_prompt_evolution_event,
    save_prompt_specs_snapshot,
)
from ari.rqgm.prompt_loader import (
    GovernedPromptLoader,
    active_prompt_view,
    evolved_prompt_path,
)
from ari.rqgm.prompt_spec import (
    REQUIRED_CONSTRAINTS_BY_ROLE,
    build_founding_specs,
    founding_registration_payloads,
    prompt_spec_from_dict,
)

INCUMBENT_TEXT = "Review {proposal} using {node_report}.\n"
CANDIDATE_TEXT = "Carefully review {proposal} using {node_report}.\n"


@pytest.fixture(autouse=True)
def _no_env_run_pin(monkeypatch):
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)


def _incumbent():
    from ari.rqgm.prompt_spec import PromptSpec

    return PromptSpec(
        prompt_id="reviewer_prompt_v3",
        role="reviewer",
        version=3,
        status="active",
        generation_mode="mutation",
        parent_prompt_id="reviewer_prompt_v2",
        template_ref={"kind": "checkpoint",
                      "key": "rqgm_prompts/reviewer_prompt_v3"},
        prompt_hash=hash12(INCUMBENT_TEXT),
        full_sha256=hashlib.sha256(INCUMBENT_TEXT.encode()).hexdigest(),
        spec={
            "role_instruction": INCUMBENT_TEXT,
            "constitutional_constraints": list(
                REQUIRED_CONSTRAINTS_BY_ROLE["reviewer"]
            ),
            "input_contract": {"required_fields": ["node_report", "proposal"]},
            "output_schema": {"__reply__": "json_object",
                              "major_issues": "list"},
            "rubric": {},
            "calibration_policy": {},
            "budget_policy": {"max_tokens": 1200},
        },
    )


def _mutator(**kw) -> PromptMutator:
    kw.setdefault("llm", lambda prompt: CANDIDATE_TEXT)
    return PromptMutator("prompt_mutator_v1", **kw)


def _propose(mutator=None, **kw):
    mutator = mutator or _mutator()
    kw.setdefault("incumbent_text", INCUMBENT_TEXT)
    kw.setdefault("epoch_id", "epoch_004")
    candidate = mutator.propose("reviewer", _incumbent(), **kw)
    assert candidate is not None
    return candidate


def _pipeline(tmp_path=None, **kw):
    kw.setdefault("cfg", ARIConfig())
    kw.setdefault("llm", lambda prompt: '{"major_issues": []}')
    kw.setdefault("case_evaluator", lambda cand, case: True)
    kw.setdefault("known_specs", {"reviewer_prompt_v3": _incumbent()})
    kw.setdefault(
        "component_roles", {"prompt_mutator_v1": "prompt_mutator"}
    )
    return CandidateValidationPipeline(checkpoint_dir=tmp_path, **kw)


def _run_through(pipeline, candidate, upto: str) -> None:
    fixtures = {"node_report": "<node_report>", "proposal": "<proposal>"}
    for stage in STAGES:
        if stage == "shadow":
            pipeline.record_shadow_observation(
                candidate, "reviewer_prompt_v3", node_id="node_1",
                candidate_output="CANDIDATE_SHADOW_OUTPUT_SENTINEL",
                incumbent_output="INCUMBENT_OUTPUT",
            )
        rec = pipeline.run_stage(
            candidate, stage,
            template_text=CANDIDATE_TEXT,
            incumbent=_incumbent(),
            fixture_kwargs=fixtures,
        )
        assert rec.passed, f"{stage}: {rec.details}"
        if stage == upto:
            return


# ── lifecycle order (§9 test 2) ──────────────────────────────────────────────


def test_stage_order_is_monotonic_and_skipping_is_rejected():
    pipeline = _pipeline()
    candidate = _propose()
    pipeline.add_candidate(candidate)
    # Skipping straight to any later stage is rejected.
    for stage in STAGES[1:]:
        with pytest.raises(ValueError, match="monotonic"):
            pipeline.run_stage(candidate, stage, template_text=CANDIDATE_TEXT)
    # Unknown stages are rejected outright.
    with pytest.raises(ValueError, match="unknown"):
        pipeline.run_stage(candidate, "instant_activation")
    # The declared order succeeds end-to-end.
    _run_through(pipeline, candidate, "shadow")
    assert pipeline.passed_stages(candidate.candidate_id) == list(STAGES)
    # A fully validated candidate has no further stages.
    with pytest.raises(ValueError, match="terminal"):
        pipeline.run_stage(candidate, "shadow", template_text=CANDIDATE_TEXT)


def test_failed_schema_dry_run_is_terminal():
    pipeline = _pipeline(llm=lambda prompt: "NOT JSON")
    candidate = _propose()
    pipeline.add_candidate(candidate)
    _run_through(pipeline, candidate, "constitutional_validation")
    rec = pipeline.run_stage(
        candidate, "schema_dry_run", template_text=CANDIDATE_TEXT,
        fixture_kwargs={"node_report": "x", "proposal": "y"},
    )
    assert not rec.passed
    assert pipeline.is_rejected(candidate.candidate_id)
    assert pipeline.next_stage(candidate.candidate_id) is None
    with pytest.raises(ValueError, match="terminal"):
        pipeline.run_stage(candidate, "replay_evaluation")
    assert build_adoption_request(candidate, pipeline) is None


def test_no_adoption_without_all_six_stage_records():
    pipeline = _pipeline()
    candidate = _propose()
    pipeline.add_candidate(candidate)
    assert build_adoption_request(candidate, pipeline) is None
    for stage in STAGES[:-1]:
        _run = stage  # readability
        rec = pipeline.run_stage(
            candidate, stage, template_text=CANDIDATE_TEXT,
            incumbent=_incumbent(),
            fixture_kwargs={"node_report": "x", "proposal": "y"},
        )
        assert rec.passed, rec.details
        # Never adoptable before the full chain exists.
        assert build_adoption_request(candidate, pipeline) is None
    pipeline.record_shadow_observation(candidate, "reviewer_prompt_v3")
    pipeline.run_stage(candidate, "shadow", template_text=CANDIDATE_TEXT)
    request = build_adoption_request(candidate, pipeline)
    assert request is not None
    assert request["from_status"] == "candidate"
    assert request["to_status"] == "probationary_active"
    assert request["stages_passed"] == list(STAGES)
    assert len(request["validation_record_ids"]) >= len(STAGES)


def test_founding_bootstrap_is_the_sole_active_on_creation_path():
    # Founding specs are born active (they ARE today's incumbents)…
    assert {s.status for s in build_founding_specs()} == {"active"}
    # …while every mutator output is born `candidate`, spec included.
    candidate = _propose()
    assert candidate.status == "candidate"
    assert candidate.prompt_spec["status"] == "candidate"
    assert candidate.generation_mode == "mutation"


def test_mutator_never_reuses_a_prompt_id_in_place():
    candidate = _propose()
    assert candidate.candidate_id != candidate.source_prompt_id
    assert candidate.candidate_id == "reviewer_prompt_v4"
    assert candidate.prompt_hash == hash12(CANDIDATE_TEXT)
    assert candidate.prompt_hash != _incumbent().prompt_hash


# ── PromptMutator write-surface audit (§9 test 2) ────────────────────────────


def test_prompt_mutator_exposes_no_registry_write_surface():
    public = [
        n
        for n in dir(PromptMutator)
        if not n.startswith("_") and callable(getattr(PromptMutator, n))
    ]
    assert public == ["propose"], public
    # And the modules never touch the registry/store write machinery.
    import ari.rqgm.prompt_evolution as pe
    import ari.rqgm.prompt_records as pr

    for mod in (pe, pr):
        text = open(mod.__file__, encoding="utf-8").read()
        for forbidden in (
            "from ari.rqgm.store", "import ari.rqgm.store",
            "from ari.rqgm.registry", "import ari.rqgm.registry",
            "EpochTransaction", "apply_registry_event",
        ):
            assert forbidden not in text, f"{mod.__name__}: {forbidden}"


# ── budgets (§9 budget tests; numbers owned by Task 12) ──────────────────────


def test_candidate_budget_caps_per_role_and_total():
    cfg = ARIConfig()
    one = _propose().to_dict()
    # Per-role cap (default 1).
    assert candidate_budget_reason([one], "epoch_004", "reviewer", cfg)
    assert candidate_budget_reason([one], "epoch_004", "router", cfg) is None
    # Another epoch does not count.
    assert candidate_budget_reason([one], "epoch_005", "reviewer", cfg) is None
    # Total cap (default 4) across roles.
    records = [
        {**one, "role": role}
        for role in ("router", "generator", "judge", "adversary")
    ]
    assert candidate_budget_reason(records, "epoch_004", "reviewer", cfg)
    # The mutator honors the caps by refusing to propose.
    assert _mutator().propose(
        "reviewer", _incumbent(), incumbent_text=INCUMBENT_TEXT,
        epoch_id="epoch_004", existing_records=[one], cfg=cfg,
    ) is None


def test_mutation_kind_gating_and_llm_absence():
    # Unknown kinds are refused.
    assert _mutator().propose(
        "reviewer", _incumbent(), incumbent_text=INCUMBENT_TEXT,
        mutation_kind="prompt_rewrite_hack",
    ) is None
    # Text-rewriting kinds need the injected LLM.
    assert PromptMutator("prompt_mutator_v1").propose(
        "reviewer", _incumbent(), incumbent_text=INCUMBENT_TEXT,
    ) is None
    # Knob-only kinds work without any LLM (deterministic).
    candidate = PromptMutator("prompt_mutator_v1").propose(
        "reviewer", _incumbent(), incumbent_text=INCUMBENT_TEXT,
        mutation_kind="threshold_tuning", epoch_id="epoch_004",
        spec_overrides={"calibration_policy": {"confidence_threshold": 0.7}},
    )
    assert candidate is not None
    assert candidate.prompt_hash == _incumbent().prompt_hash  # same bytes
    assert candidate.candidate_id == "reviewer_prompt_v4"  # new identity


# ── shadow sampling + observation-only records (§9) ──────────────────────────


def test_shadow_sampling_is_deterministic_and_capped():
    cfg = ARIConfig()
    cfg.rqgm.shadow.sample_rate = 1.0
    cfg.rqgm.shadow.max_shadow_calls_per_epoch = 2
    pipeline = _pipeline(cfg=cfg)
    candidate = _propose()
    # Deterministic: same inputs, same decision (P2).
    first = pipeline.should_shadow("epoch_004", "node_1")
    assert first == pipeline.should_shadow("epoch_004", "node_1")
    assert first is True  # sample_rate 1.0 == always, until the cap
    pipeline.record_shadow_observation(candidate, "reviewer_prompt_v3")
    assert pipeline.shadow_budget_left("epoch_004") == 1
    pipeline.record_shadow_observation(candidate, "reviewer_prompt_v3")
    assert pipeline.shadow_budget_left("epoch_004") == 0
    assert pipeline.should_shadow("epoch_004", "node_1") is False
    # sample_rate 0 never samples.
    cfg.rqgm.shadow.sample_rate = 0.0
    cfg.rqgm.shadow.max_shadow_calls_per_epoch = 10
    assert _pipeline(cfg=cfg).should_shadow("epoch_004", "node_1") is False


def test_shadow_records_carry_hashes_never_output_text(tmp_path):
    pipeline = _pipeline(tmp_path)
    candidate = _propose()
    obs = pipeline.record_shadow_observation(
        candidate, "reviewer_prompt_v3", node_id="node_7",
        input_context="INPUT_TEXT",
        candidate_output="CANDIDATE_SHADOW_OUTPUT_SENTINEL",
        incumbent_output="INCUMBENT_OUTPUT_SENTINEL",
        divergence={"recommended_action": ["revise", "accept"]},
    )
    assert obs.candidate_output_hash == hash12(
        "CANDIDATE_SHADOW_OUTPUT_SENTINEL"
    )
    assert obs.status == "recorded"
    raw = (tmp_path / "prompt_evolution.jsonl").read_text(encoding="utf-8")
    # Observation-only: hashes are logged, raw shadow output text is NOT.
    assert "CANDIDATE_SHADOW_OUTPUT_SENTINEL" not in raw
    assert "INCUMBENT_OUTPUT_SENTINEL" not in raw
    assert obs.candidate_output_hash in raw


# ── defaults parity (repo convention) ────────────────────────────────────────


def test_new_config_blocks_mirror_defaults_yaml():
    defaults = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1]
            / "ari" / "configs" / "defaults.yaml"
        ).read_text(encoding="utf-8")
    )
    shadow = defaults["rqgm"]["shadow"]
    typed_shadow = RQGMShadowConfig()
    assert typed_shadow.sample_rate == shadow["sample_rate"]
    assert typed_shadow.max_shadow_calls_per_epoch == (
        shadow["max_shadow_calls_per_epoch"]
    )
    evo = defaults["rqgm"]["prompt_evolution"]
    typed_evo = RQGMPromptEvolutionConfig()
    assert typed_evo.enabled == evo["enabled"]
    assert typed_evo.max_candidates_per_role_per_epoch == (
        evo["max_candidates_per_role_per_epoch"]
    )
    assert typed_evo.max_total_candidates_per_epoch == (
        evo["max_total_candidates_per_epoch"]
    )
    assert typed_evo.max_clean_room_generations_per_epoch == (
        evo["max_clean_room_generations_per_epoch"]
    )
    assert typed_evo.mutation_kinds == evo["mutation_kinds"]
    # The mode default stays untouched: expand_prompt preserves behavior.
    assert ARIConfig().bfts.expand_prompt == "orchestrator/bfts_expand"


# ── ari_rqgm smoke (§9 integration) ──────────────────────────────────────────


def test_ari_rqgm_prompt_evolution_smoke(tmp_path):
    """Bootstrap → mutation candidate → six stages (stub LLM, real replay
    pool) → adoption request → stubbed transition engine → provenance."""
    from ari.rqgm.adversarial.pool import AdversarialReplayPool
    from ari.rqgm.store import RqgmStateStore

    cfg = ARIConfig()
    store = RqgmStateStore()
    state = store.open_epoch(tmp_path, cfg, node_count=0, run_id="smoke")
    assert state is not None and state.epoch is not None
    epoch_id = state.epoch.epoch_id

    # 1. Founding bootstrap registers through the Task 02 event log.
    events = [
        TransitionEvent(event_type="prompt_registered", payload=payload)
        for payload in founding_registration_payloads()
    ]
    state = store.apply_transition(tmp_path, "transition_000_to_001", events)
    incumbent_entry = state.prompts.get("reviewer_prompt_v1")
    assert incumbent_entry is not None and incumbent_entry.status == "active"

    # Provenance for a founding prompt use: reserved fields populated.
    state.prompts.record_use(
        "reviewer_prompt_v1", model="m", node_id="node_0", phase="bfts",
        checkpoint_dir=tmp_path,
    )

    # 2. One synthetic mutation candidate (deterministic fake mutator LLM).
    founding = {
        s.template_ref["key"]: s for s in build_founding_specs()
    }
    incumbent = founding["evaluator/peer_review"]
    from ari.prompts import FilesystemPromptLoader

    incumbent_text = FilesystemPromptLoader().load("evaluator/peer_review")
    new_text = "Evolved peer review instructions.\n\n{axes_block}\n"
    mutator = PromptMutator(
        "prompt_mutator_v1", llm=lambda prompt: new_text,
        checkpoint_dir=tmp_path,
    )
    candidate = mutator.propose(
        "reviewer", incumbent, [{"summary_id": "fsum_00001"}],
        incumbent_text=incumbent_text, epoch_id=epoch_id,
        existing_records=[], cfg=cfg, rationale="smoke",
    )
    assert candidate is not None
    assert evolved_prompt_path(tmp_path, candidate.candidate_id).exists()

    # 3. Replay pool with one adjudicated case (Task 06 consumer API).
    pool = AdversarialReplayPool(tmp_path, cfg.rqgm.adversarial)
    admitted = pool.admit(
        [{
            "record_id": "vat_000001", "case_type": "overclaim",
            "raw_attack_id": "atk_000001", "judgment_id": "jdg_000001",
            "verdict": "valid", "severity": "high",
            "source_node_id": "node_0",
            "expected_behavior": {"reviewer": "flag unfair baseline"},
            "target_artifact_hash": "1" * 12,
        }],
        epoch_id=epoch_id,
    )
    assert len(admitted) == 1

    # 4. The six stages with injected deterministic components.
    pipeline = CandidateValidationPipeline(
        checkpoint_dir=tmp_path,
        cfg=cfg,
        llm=lambda prompt: '{"scores": {}}',
        case_evaluator=lambda cand, case: True,
        replay_pool=pool,
        anchor_cases=[{"case_id": "anchor_00001",
                       "expected_behavior": {"reviewer": "flag it"}}],
        known_specs={incumbent.prompt_id: incumbent},
        component_roles={"prompt_mutator_v1": "prompt_mutator"},
    )
    pipeline.add_candidate(candidate)
    for stage in STAGES:
        if stage == "shadow":
            assert pipeline.should_shadow(epoch_id, "node_1") in (True, False)
            pipeline.record_shadow_observation(
                candidate, incumbent.prompt_id, node_id="node_1",
                candidate_output="shadow-only-output",
            )
        rec = pipeline.run_stage(
            candidate, stage,
            incumbent=incumbent,
            fixture_kwargs={"axes_block": "<axes_block>"},
            incumbent_evaluator=lambda spec, case: True,
        )
        assert rec.passed, f"{stage}: {rec.details}"
    replay_rec = [
        r for r in pipeline.stage_records(candidate.candidate_id)
        if r["stage"] == "replay_evaluation"
    ][0]
    assert replay_rec["case_results"][0]["case_id"] == "adv_case_00000"
    assert replay_rec["case_results"][0]["cache_key"]

    # 5. Adoption request → stubbed transition engine (Task 09 seam):
    #    status changes flow ONLY through the Task 02 transaction.
    request = build_adoption_request(candidate, pipeline)
    assert request is not None
    state = store.apply_transition(
        tmp_path, "transition_001_to_002",
        [
            TransitionEvent(
                event_type="prompt_registered",
                payload=request["registration_payload"],
            ),
            TransitionEvent(
                event_type="prompt_status_change",
                payload={
                    "prompt_id": request["candidate_id"],
                    "from_status": request["from_status"],
                    "to_status": request["to_status"],
                },
            ),
        ],
    )
    adopted = state.prompts.get(candidate.candidate_id)
    assert adopted is not None
    assert adopted.status == "probationary_active"
    # The adopted body resolves from the checkpoint, hash-verified.
    text, version_id = state.prompts.resolve_text(
        candidate.candidate_id, checkpoint_dir=tmp_path
    )
    assert (text, version_id) == (new_text, candidate.prompt_hash)

    # The GovernedPromptLoader resolves the adopted spec for the new epoch.
    adopted_spec = prompt_spec_from_dict(
        {**candidate.prompt_spec, "status": "probationary_active"}
    )
    loader = GovernedPromptLoader(
        active_prompt_view([adopted_spec]), checkpoint_dir=tmp_path
    )
    assert loader.load("rqgm_prompts/reviewer_prompt_v2") == new_text

    # 6. Provenance: reserved fields populated for the evolved prompt too.
    state.prompts.record_use(
        candidate.candidate_id, phase="bfts", checkpoint_dir=tmp_path
    )
    from ari.prompts import load_prompt_trace

    rows = load_prompt_trace(tmp_path)
    governed = [r for r in rows if r["prompt_version"] is not None]
    assert {r["prompt_version"] for r in governed} == {
        "reviewer_prompt_v1", candidate.candidate_id,
    }
    assert all(r["prompt_registry_version"] for r in governed)

    # 7. Shadow output text never leaks into any evolution record; the
    #    rollup snapshot derives from the JSONL truth.
    raw = (tmp_path / "prompt_evolution.jsonl").read_text(encoding="utf-8")
    assert "shadow-only-output" not in raw
    save_prompt_specs_snapshot(tmp_path)
    rollup = json.loads(
        (tmp_path / "prompt_specs.json").read_text(encoding="utf-8")
    )
    entry = rollup["specs"][candidate.candidate_id]
    assert entry["stages_passed"] == list(STAGES)
    assert entry["rejected"] is False

    # 8. Resume: a fresh pipeline reconstructs the chain from the JSONL.
    resumed = CandidateValidationPipeline(checkpoint_dir=tmp_path, cfg=cfg)
    assert resumed.passed_stages(candidate.candidate_id) == list(STAGES)
    assert resumed.ready_for_adoption(candidate.candidate_id)


def test_fail_open_writer_and_zero_files_without_checkpoint(tmp_path):
    """No checkpoint → no-op, never raises; simple_bfts never constructs
    these classes, so no RQGM prompt file can appear (§5.7 mode table)."""
    record_prompt_evolution_event(None, {"record_type": "prompt_candidate"})
    save_prompt_specs_snapshot(None)
    assert load_prompt_evolution_log(None) == []
    assert list(tmp_path.iterdir()) == []


# ── exploration candidates must be VALIDATED before scoring (sweep) ──────────
#
# `CandidateValidationPipeline` — the documented six-stage validation — is never
# instantiated in production. The paper path re-implements stages 1-3 inline;
# the EXPLORATION path did nothing, so a minted candidate went straight into
# `candidate_evaluations` unvalidated and could be board-scored and adopted.

class _MutatorLLM:
    def complete(self, messages, **kw):
        class _R:
            content = (
                "You are the reviewer. Judge only what the evidence supports.\n"
                "Do not override fixed verifier failures.\n"
                "Do not directly modify frontier scores.\n"
            )
        return _R()


def _runtime_for_minting(tmp_path):
    from ari.config import ARIConfig
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=_MutatorLLM())
    rt.ensure_epoch(0, checkpoint_dir=tmp_path, run_id="validation-test")
    return rt


def test_real_minted_candidates_survive_the_deterministic_gate(tmp_path):
    """The gate must not break prompt evolution: well-formed candidates pass."""
    rt = _runtime_for_minting(tmp_path)
    assert rt._generate_prompt_candidates(tmp_path), (
        "the deterministic validation gate rejected every legitimate candidate"
    )


def test_a_failing_candidate_never_enters_candidate_evaluations(tmp_path, monkeypatch):
    """The gate is actually REACHED on the mint path — a rejected candidate is
    dropped before it can be scored or adopted."""
    from ari.rqgm.runtime import RQGMRuntime

    rt = _runtime_for_minting(tmp_path)
    monkeypatch.setattr(
        RQGMRuntime, "_deterministic_candidate_failures",
        lambda self, cand, ckpt: ["forced_failure"],
    )
    assert rt._generate_prompt_candidates(tmp_path) == ()


def test_the_gate_calls_the_single_stage_definitions(tmp_path):
    """One implementation of each stage — never a second exploration-local copy."""
    import inspect

    from ari.rqgm.runtime import RQGMRuntime

    src = inspect.getsource(RQGMRuntime._deterministic_candidate_failures)
    for fn in ("static_validation_failures",
               "constitutional_validation_failures",
               "role_instruction_constraint_failures"):
        assert fn in src, f"the gate does not run {fn}"
    assert "from ari.rqgm.prompt_evolution import" in src


# ── LIVE shadow: the stage that makes T6 reachable for behavioural roles ─────
#
# T6 (`shadow -> probationary_active`) reads `shadow_samples`/`shadow_score`,
# and the governance board — the only producer of exploration evaluations —
# emits neither, so the adoption edge was unreachable for EVERY exploration
# role: candidates were minted, scored, then stranded in `shadow` forever.
# The sampler, budget and observation record all existed; nothing called them.

class _ShadowLLM:
    def complete(self, messages, **kw):
        class _R:
            content = ("CAND-OUT" if "CANDIDATE-BODY" in messages[0]["content"]
                       else "INC-OUT")
        return _R()


def _runtime_with_shadow_candidate(tmp_path):
    from types import SimpleNamespace as NS

    from ari.config import ARIConfig
    from ari.rqgm.prompt_evolution import PromptCandidate
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=_ShadowLLM())
    rt.ensure_epoch(0, checkpoint_dir=tmp_path, run_id="shadow-test")
    st = rt._epoch_state
    entries = st.prompts.entries()
    inc = next(p for p, e in entries.items()
               if getattr(e, "role", "") == "reviewer"
               and getattr(e, "status", "") == "active")
    rt.validation_pipeline.add_candidate(PromptCandidate(
        record_id="r1", epoch_id="epoch_000", component_id="reviewer_v1",
        prompt_hash="c" * 12, candidate_id="cand_shadow_1", role="reviewer",
        generated_by={"component_id": "prompt_mutator_v1"},
        generation_mode="mutation", mutation_kind="tighten_constraint",
        source_prompt_id=inc,
    ))
    entries["reviewer_prompt_v2"] = NS(
        prompt_id="reviewer_prompt_v2", role="reviewer", status="shadow",
        prompt_hash="c" * 12,
    )
    st.prompts.resolve_text = lambda pid, **kw: (
        ("CANDIDATE-BODY", "c" * 12) if pid == "reviewer_prompt_v2"
        else ("INCUMBENT-BODY", "i" * 12)
    )
    st.prompts.entries = lambda: entries
    return rt


def _sampled_node_id(rt):
    from types import SimpleNamespace as NS

    pipe = rt.validation_pipeline
    for i in range(200):
        nid = f"node_{i}"
        if pipe.should_shadow("epoch_000", nid):
            return NS(id=nid)
    raise AssertionError("the deterministic sampler selected no node")


def test_live_shadow_records_a_side_by_side_observation(tmp_path):
    rt = _runtime_with_shadow_candidate(tmp_path)
    node = _sampled_node_id(rt)

    assert rt.run_shadow_comparison(node, input_context="live ctx") == 1

    obs = [r for r in rt.validation_pipeline.records()
           if r.get("record_type") == "comparison_observation"]
    assert len(obs) == 1
    o = obs[0]
    # BOTH sides ran on the SAME live input, and only HASHES are kept
    assert o["candidate_output_hash"] and o["incumbent_output_hash"]
    assert o["candidate_output_hash"] != o["incumbent_output_hash"]
    assert o["divergence"] == {"agreed": False}
    assert "CAND-OUT" not in str(o)          # raw output never stored


def test_shadow_evidence_gives_T6_a_basis(tmp_path):
    rt = _runtime_with_shadow_candidate(tmp_path)
    rt.run_shadow_comparison(_sampled_node_id(rt), input_context="live ctx")

    ev = rt.shadow_evidence("c" * 12, "cand_shadow_1")
    assert ev["shadow_samples"] == 1
    assert ev["shadow_score"] == 0.0        # the two disagreed


def test_absent_observations_are_honestly_absent(tmp_path):
    """No basis must never become a stand-in number — T6 simply stays shut."""
    rt = _runtime_with_shadow_candidate(tmp_path)
    assert rt.shadow_evidence("no_such_hash") == {
        "shadow_samples": 0, "shadow_score": None,
    }


def test_shadow_output_never_reaches_a_bfts_score(tmp_path):
    """Observation-only: the candidate's output informs ADOPTION and nothing
    else — never node metrics, the frontier, or any BFTS score."""
    from types import SimpleNamespace as NS

    rt = _runtime_with_shadow_candidate(tmp_path)
    node = NS(id=_sampled_node_id(rt).id, metrics={"_scientific_score": 0.42})
    before = dict(node.metrics)

    rt.run_shadow_comparison(node, input_context="live ctx")

    assert node.metrics == before, "the shadow run mutated node metrics"


# ── an ADOPTED evolved prompt must actually be RENDERED (sweep) ──────────────
#
# `AdversarialRound` was constructed in production with `loader=None`, so the
# adversary / defender / judge all fell back to `FilesystemPromptLoader` and
# read the COMMITTED TEMPLATE off disk. An adopted evolved prompt was therefore
# never rendered and prompt evolution had NO effect on their behaviour —
# co-evolution was cosmetic for every governed actor. `GovernedPromptLoader`
# exists exactly to prevent this and was never constructed.

def _rqgm(tmp_path):
    from ari.config import ARIConfig
    from ari.rqgm.runtime import RQGMRuntime

    cfg = ARIConfig()
    cfg.ari.mode = "ari_rqgm"
    cfg.rqgm.enabled = True
    rt = RQGMRuntime(cfg, checkpoint_dir=tmp_path, llm=object())
    rt.ensure_epoch(0, checkpoint_dir=tmp_path, run_id="loader-test")
    return rt


def test_the_governed_loader_reaches_every_governed_actor(tmp_path):
    from ari.rqgm.prompt_loader import GovernedPromptLoader

    rt = _rqgm(tmp_path)
    assert isinstance(rt.governed_loader, GovernedPromptLoader)
    rnd = rt.adversarial
    for actor in ("engine", "defender", "judge"):
        loader = getattr(getattr(rnd, actor), "_loader", None)
        assert isinstance(loader, GovernedPromptLoader), (
            f"{actor} still loads the committed template — an adopted evolved "
            "prompt would never be rendered"
        )


def test_an_adopted_evolved_prompt_is_rendered(tmp_path):
    import hashlib
    from types import SimpleNamespace as NS

    rt = _rqgm(tmp_path)
    st = rt._epoch_state
    entries = st.prompts.entries()
    body = "EVOLVED DEFENDER BODY\n"
    (tmp_path / "rqgm_prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "rqgm_prompts" / "defender_v2.md").write_text(body)
    digest = hashlib.sha256(body.encode()).hexdigest()[:12]
    entries["defender_prompt_v2"] = NS(
        prompt_id="defender_prompt_v2", role="defender", status="active",
        prompt_hash=digest,
        source={"kind": "checkpoint_file", "path": "rqgm_prompts/defender_v2"},
    )
    st.prompts.entries = lambda: entries

    text, version = rt.governed_loader.load_versioned("rqgm_prompts/defender_v2")

    assert text == body
    assert version == digest        # refuses bytes that drifted from the spec


def test_ungoverned_keys_degrade_byte_identically(tmp_path):
    """A key no spec governs must resolve exactly as before the loader existed."""
    from ari.prompts import FilesystemPromptLoader

    rt = _rqgm(tmp_path)
    entries = rt._epoch_state.prompts.entries()
    key = next((getattr(e, "source", {}) or {}).get("key")
               for e in entries.values()
               if getattr(e, "role", "") == "defender")
    governed, _ = rt.governed_loader.load_versioned(key)
    plain, _ = FilesystemPromptLoader().load_versioned(key)
    assert governed == plain


def test_a_policy_body_is_never_offered_for_rendering(tmp_path):
    """A utility policy is frozen, not rendered (plan 14 §5.3)."""
    from types import SimpleNamespace as NS

    rt = _rqgm(tmp_path)
    st = rt._epoch_state
    entries = st.prompts.entries()
    entries["utility_policy_vX"] = NS(
        prompt_id="utility_policy_vX", role="utility_policy", status="active",
        prompt_hash="p" * 12,
        source={"kind": "policy", "path": "rqgm_prompts/utility_policy_vX"},
    )
    st.prompts.entries = lambda: entries
    view = getattr(rt.governed_loader, "_view", {})
    assert "rqgm_prompts/utility_policy_vX" not in view
