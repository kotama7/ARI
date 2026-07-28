"""RQGM Task 13 — ablation-condition expansion (docs/plans/ari_rqgm/13 §5.1/§9).

Pins each B0-B8 preset in ``scripts/rqgm_eval/ablation_matrix.yaml`` to its
exact mode + feature-flag expansion AND to the EFFECTIVE config the spawned
``ari run --config`` resolves (the layer flags default TRUE, so the ladder
only exists because every rung explicitly disables the layers above it),
checks B0 equals the shipped default config, the additive-ladder property
(each rung's enabled-flag set ⊇ the previous, B2/B3 VirSci fork excepted),
that every overlay key is a TYPED config field (``load_config`` filtering
would silently drop untyped keys), all four mode × VirSci combinations are
expressible, and the ``rqgm.eval`` defaults parity between defaults.yaml
and ``RQGMEvalConfig``.

No LLM, no network — pure YAML + dict expansion (P2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ari.config import ARIConfig, RQGMEvalConfig
from ari.rqgm.evaluation.conditions import (
    ADDITIVE_PAIRS,
    CONDITION_IDS,
    MODEL_ENV_VARS,
    VIRSCI_ARTIFACTS,
    condition_overlay,
    deep_merge,
    default_matrix_path,
    enabled_flag_paths,
    eval_defaults_overlay,
    expand_condition,
    flag_paths,
    load_matrix,
    resolve_models,
    virsci_absence_violations,
    virsci_enabled,
)

MATRIX = load_matrix()


# ── matrix shape ─────────────────────────────────────────────────────────────


def test_default_matrix_path_exists():
    path = default_matrix_path()
    assert path.name == "ablation_matrix.yaml"
    assert path.is_file()


def test_all_nine_conditions_defined():
    assert set(MATRIX["conditions"]) == set(CONDITION_IDS)
    assert CONDITION_IDS == (
        "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8",
    )


def test_eval_defaults_declared():
    defaults = MATRIX["eval_defaults"]
    assert len(defaults["seeds"]) >= 3          # plan 13 §5.2 paired seeds
    assert defaults["bfts"]["max_total_nodes"] == 20
    assert defaults["bfts"]["max_depth"] == 4


def test_eval_defaults_bfts_applies_node_budget_parity():
    """§5.2: the harness merges eval_defaults.bfts UNDER every condition,
    so the node budget is identical across the whole ladder and every
    merged overlay key survives load_config's typed-field filter."""
    parity = eval_defaults_overlay(MATRIX)
    assert parity == {"bfts": {"max_total_nodes": 20, "max_depth": 4}}
    for cid in CONDITION_IDS:
        merged = deep_merge(parity, condition_overlay(MATRIX, cid))
        assert merged["bfts"] == parity["bfts"], cid
        for path in flag_paths(merged):
            _assert_typed(ARIConfig, path)
    assert eval_defaults_overlay({"conditions": {}}) == {}


def test_resolve_models_pins_phase_env_vars():
    """§5.2 model pinning: eval_defaults.models resolves to the ARI_MODEL_*
    phase env vars from one campaign-start snapshot; unresolved ${VAR}
    placeholders drop out instead of leaking literally."""
    assert MODEL_ENV_VARS == {
        "coding": "ARI_MODEL_CODING",
        "bfts": "ARI_MODEL_BFTS",
        "eval": "ARI_MODEL_EVAL",
    }
    snapshot = {
        "ARI_MODEL_CODING": "prov/code-1",
        "ARI_MODEL_BFTS": "prov/bfts-1",
        "ARI_MODEL_EVAL": "prov/eval-1",
    }
    assert resolve_models(MATRIX, snapshot) == snapshot
    assert resolve_models(MATRIX, {}) == {}
    literal = {"eval_defaults": {"models": {"eval": "prov/eval-2"}}}
    assert resolve_models(literal, {}) == {"ARI_MODEL_EVAL": "prov/eval-2"}
    assert resolve_models({"conditions": {}}, {}) == {}


def test_resolve_models_unknown_role_raises():
    with pytest.raises(ValueError, match="unknown model role"):
        resolve_models({"eval_defaults": {"models": {"idea": "m"}}}, {})


# ── exact expansions (§11 completion criterion 1) ────────────────────────────

def _rqgm_layers(**overrides: bool) -> dict:
    """The `rqgm:` block shared by every ari_rqgm rung: each preset sets
    ALL five layer flags explicitly (they default TRUE in the typed config,
    so an absent key would silently run the layer — plan 13 §5.1 †)."""
    block: dict = {
        "enabled": True,
        "adversarial": {"enabled": False},
        "governance": {"enabled": False},
        "frontier_repair": {"enabled": False},
        "prompt_evolution": {"enabled": False},
        "meta_evolution": {"enabled": False},
    }
    for key, value in overrides.items():
        block[key] = {"enabled": value}
    return block


_NO_VIRSCI = {"generators": {"virsci": {"enabled": False}}}

_EXPECTED = {
    "B0": {"mode": "simple_bfts", "rqgm": {"enabled": False}},
    "B1": {"mode": "simple_bfts", "rqgm": {"enabled": False},
           "proposal_router": {"record_only": True}},
    "B2": {"mode": "ari_rqgm", "rqgm": _rqgm_layers(),
           "proposal_router": {"generators": {"virsci": {
               "enabled": True, "mode": "event_triggered",
               "max_calls_per_epoch": 2}}}},
    "B3": {"mode": "ari_rqgm", "rqgm": _rqgm_layers(),
           "proposal_router": _NO_VIRSCI},
    "B4": {"mode": "ari_rqgm",
           "rqgm": _rqgm_layers(adversarial=True),
           "proposal_router": _NO_VIRSCI},
    "B5": {"mode": "ari_rqgm",
           "rqgm": _rqgm_layers(adversarial=True, governance=True),
           "proposal_router": _NO_VIRSCI},
    "B6": {"mode": "ari_rqgm",
           "rqgm": _rqgm_layers(adversarial=True, governance=True,
                                frontier_repair=True),
           "proposal_router": _NO_VIRSCI},
    "B7": {"mode": "ari_rqgm",
           "rqgm": _rqgm_layers(adversarial=True, governance=True,
                                frontier_repair=True, prompt_evolution=True),
           "proposal_router": _NO_VIRSCI},
    "B8": {"mode": "ari_rqgm",
           "rqgm": _rqgm_layers(adversarial=True, governance=True,
                                frontier_repair=True, prompt_evolution=True,
                                meta_evolution=True),
           "proposal_router": _NO_VIRSCI},
}


@pytest.mark.parametrize("cid", CONDITION_IDS)
def test_expansion_pinned_exactly(cid):
    assert expand_condition(MATRIX, cid) == _EXPECTED[cid]


def test_overlay_maps_mode_to_ari_mode():
    overlay = condition_overlay(MATRIX, "B8")
    assert overlay["ari"] == {"mode": "ari_rqgm"}
    assert "mode" not in overlay
    assert overlay["rqgm"]["meta_evolution"]["enabled"] is True


# ── B0 == shipped defaults (regression-guard rung) ───────────────────────────


def test_b0_expansion_equals_shipped_defaults():
    overlay = condition_overlay(MATRIX, "B0")
    default = ARIConfig()
    assert overlay["ari"]["mode"] == default.ari.mode == "simple_bfts"
    assert overlay["rqgm"]["enabled"] is default.rqgm.enabled is False
    # Every leaf B0 sets must equal the shipped default value.
    cfg = ARIConfig.model_validate(overlay)
    assert cfg == default


def test_b1_only_adds_record_only():
    b0 = enabled_flag_paths(expand_condition(MATRIX, "B0"))
    b1 = enabled_flag_paths(expand_condition(MATRIX, "B1"))
    assert b1 - b0 == {"proposal_router.record_only"}


# ── ladder monotonicity + the B2/B3 VirSci fork ──────────────────────────────


@pytest.mark.parametrize("lo,hi", ADDITIVE_PAIRS)
def test_ladder_is_additive(lo, hi):
    lo_flags = enabled_flag_paths(expand_condition(MATRIX, lo))
    hi_flags = enabled_flag_paths(expand_condition(MATRIX, hi))
    assert lo_flags <= hi_flags
    assert lo_flags != hi_flags  # each rung adds something


def test_b2_b3_fork_only_on_virsci():
    b2 = flag_paths(expand_condition(MATRIX, "B2"))
    b3 = flag_paths(expand_condition(MATRIX, "B3"))
    differing = {
        key
        for key in set(b2) | set(b3)
        if b2.get(key) != b3.get(key)
    }
    assert differing
    prefix = "proposal_router.generators.virsci."
    assert all(key.startswith(prefix) for key in sorted(differing))


def test_marginal_layer_flags_match_owning_tasks():
    """Each rung's marginal flag is the owning task's real config switch."""
    marginals = {
        ("B3", "B4"): "rqgm.adversarial.enabled",         # Task 06
        ("B4", "B5"): "rqgm.governance.enabled",          # Task 05
        ("B5", "B6"): "rqgm.frontier_repair.enabled",     # Task 10
        ("B6", "B7"): "rqgm.prompt_evolution.enabled",    # Task 07
        ("B7", "B8"): "rqgm.meta_evolution.enabled",      # Task 11
    }
    for (lo, hi), flag in marginals.items():
        added = enabled_flag_paths(expand_condition(MATRIX, hi)) - \
            enabled_flag_paths(expand_condition(MATRIX, lo))
        assert added == {flag}, (lo, hi, added)


# ── effective Tier-3 config (§11.1: the ladder must survive load_config) ─────
#
# The five layer flags default TRUE in the typed config, and load_config
# fills every absent overlay key from those pydantic defaults — so the
# ladder only exists if each rung explicitly disables the layers above it.
# Pin the EFFECTIVE config the spawned `ari run --config` resolves, not
# just the preset dict.

#: cid -> (adversarial, governance, frontier_repair, prompt_evolution,
#: meta_evolution) in the EFFECTIVE config (plan 13 §5.1 feature sets).
_EFFECTIVE_LAYERS = {
    "B2": (False, False, False, False, False),
    "B3": (False, False, False, False, False),
    "B4": (True, False, False, False, False),
    "B5": (True, True, False, False, False),
    "B6": (True, True, True, False, False),
    "B7": (True, True, True, True, False),
    "B8": (True, True, True, True, True),
}


def _effective_layer_flags(cid: str) -> dict:
    cfg = ARIConfig.model_validate(condition_overlay(MATRIX, cid))
    return {
        "rqgm.adversarial.enabled": cfg.rqgm.adversarial.enabled,
        "rqgm.governance.enabled": cfg.rqgm.governance.enabled,
        "rqgm.frontier_repair.enabled": cfg.rqgm.frontier_repair.enabled,
        "rqgm.prompt_evolution.enabled": cfg.rqgm.prompt_evolution.enabled,
        "rqgm.meta_evolution.enabled": cfg.rqgm.meta_evolution.enabled,
    }


@pytest.mark.parametrize("cid", sorted(_EFFECTIVE_LAYERS))
def test_effective_config_realizes_the_ladder(cid):
    cfg = ARIConfig.model_validate(condition_overlay(MATRIX, cid))
    assert cfg.ari.mode == "ari_rqgm"
    assert cfg.rqgm.enabled is True
    adv, gov, repair, evo, meta = _EFFECTIVE_LAYERS[cid]
    assert cfg.rqgm.adversarial.enabled is adv
    assert cfg.rqgm.governance.enabled is gov          # §5.1 † (B2-B4 off)
    assert cfg.rqgm.frontier_repair.enabled is repair
    assert cfg.rqgm.prompt_evolution.enabled is evo
    assert cfg.rqgm.meta_evolution.enabled is meta


def test_effective_rungs_do_not_collapse_into_b8():
    """The regression this section pins: without explicit falses every
    ari_rqgm rung's effective config equals B8 and the marginal deltas
    (B5−B4, B6−B5, …) measure nothing."""
    b8 = ARIConfig.model_validate(condition_overlay(MATRIX, "B8")).rqgm
    for cid in ("B2", "B3", "B4", "B5", "B6", "B7"):
        cfg = ARIConfig.model_validate(condition_overlay(MATRIX, cid))
        assert cfg.rqgm != b8, cid


def test_effective_marginals_flip_exactly_one_layer():
    marginals = {
        ("B3", "B4"): "rqgm.adversarial.enabled",
        ("B4", "B5"): "rqgm.governance.enabled",
        ("B5", "B6"): "rqgm.frontier_repair.enabled",
        ("B6", "B7"): "rqgm.prompt_evolution.enabled",
        ("B7", "B8"): "rqgm.meta_evolution.enabled",
    }
    for (lo, hi), flag in marginals.items():
        lo_flags = _effective_layer_flags(lo)
        hi_flags = _effective_layer_flags(hi)
        changed = {k for k in lo_flags if lo_flags[k] != hi_flags[k]}
        assert changed == {flag}, (lo, hi, changed)
        assert lo_flags[flag] is False and hi_flags[flag] is True


def test_effective_b0_b1_stay_simple_bfts():
    for cid in ("B0", "B1"):
        cfg = ARIConfig.model_validate(condition_overlay(MATRIX, cid))
        assert cfg.ari.mode == "simple_bfts"
        assert cfg.rqgm.enabled is False


@pytest.mark.parametrize("cid", CONDITION_IDS)
def test_no_preset_engages_the_eval_harness(cid):
    """Doubles can never leak into a Tier-3 campaign via a shipped preset."""
    cfg = ARIConfig.model_validate(condition_overlay(MATRIX, cid))
    assert cfg.rqgm.eval.enabled is False
    assert cfg.rqgm.eval.scripted_components == {}


# ── typed-field guarantee (load_config filtering) ────────────────────────────


def _assert_typed(model_cls, path: str):
    segments = path.split(".")
    cls = model_cls
    for i, segment in enumerate(segments):
        fields = getattr(cls, "model_fields", None)
        assert fields is not None and segment in fields, (
            f"overlay key {path!r} is not a typed config field at "
            f"{'.'.join(segments[:i + 1])!r} — load_config would drop it"
        )
        annotation = fields[segment].annotation
        cls = annotation


@pytest.mark.parametrize("cid", CONDITION_IDS)
def test_every_overlay_key_is_a_typed_field(cid):
    overlay = condition_overlay(MATRIX, cid)
    for path in flag_paths(overlay):
        _assert_typed(ARIConfig, path)


# ── mode × VirSci matrix (plan 13 §9: all four combinations expressible) ─────


def test_four_mode_virsci_combinations_expressible():
    synthetic = {
        "conditions": {
            "sb_off": {"mode": "simple_bfts"},
            "sb_on": {"inherits": "sb_off",
                      "proposal_router": {"generators": {"virsci": {
                          "enabled": True}}}},
            "rq_off": {"mode": "ari_rqgm", "rqgm": {"enabled": True},
                       "proposal_router": {"generators": {"virsci": {
                           "enabled": False}}}},
            "rq_on": {"mode": "ari_rqgm", "rqgm": {"enabled": True},
                      "proposal_router": {"generators": {"virsci": {
                          "enabled": True}}}},
        }
    }
    combos = set()
    for cid in synthetic["conditions"]:
        overlay = condition_overlay(synthetic, cid)
        mode = overlay["ari"]["mode"]
        virsci = (
            overlay.get("proposal_router", {})
            .get("generators", {})
            .get("virsci", {})
            .get("enabled", False)
        )
        combos.add((mode, bool(virsci)))
    assert combos == {
        ("simple_bfts", False), ("simple_bfts", True),
        ("ari_rqgm", False), ("ari_rqgm", True),
    }


# ── the §5.2 VirSci-off assertion ────────────────────────────────────────────


def test_virsci_enabled_reads_the_overlay():
    assert virsci_enabled(condition_overlay(MATRIX, "B2")) is True
    for cid in ("B0", "B1", "B3", "B8"):
        assert virsci_enabled(condition_overlay(MATRIX, cid)) is False
    assert virsci_enabled({}) is False


def test_virsci_absence_clean_checkpoint(tmp_path):
    assert virsci_absence_violations(tmp_path) == []
    # A VirSci-free trace and proposal store stay clean.
    (tmp_path / "prompt_trace.jsonl").write_text(
        '{"prompt_name": "bfts/agent_query", "template_hash": "x"}\n'
        "not json\n",
        encoding="utf-8",
    )
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "proposal_records.jsonl").write_text(
        '{"record_id": "prop_000001", "generator": "cheap"}\n',
        encoding="utf-8",
    )
    assert virsci_absence_violations(tmp_path) == []


def test_virsci_absence_flags_artifacts_prompts_and_records(tmp_path):
    assert VIRSCI_ARTIFACTS == ("virsci_logs", "virsci_snapshot")
    (tmp_path / "virsci_logs").mkdir()
    (tmp_path / "prompt_trace.jsonl").write_text(
        '{"prompt_name": "virsci/team_discussion", "template_hash": "x"}\n',
        encoding="utf-8",
    )
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "proposal_records.jsonl").write_text(
        '{"record_id": "prop_000002", "generator": "virsci"}\n',
        encoding="utf-8",
    )
    problems = virsci_absence_violations(tmp_path)
    assert len(problems) == 3
    assert any("virsci_logs/" in p for p in problems)
    assert any("prompt_trace.jsonl" in p for p in problems)
    assert any("prop_000002" in p for p in problems)


# ── expansion machinery ──────────────────────────────────────────────────────


def test_unknown_condition_raises():
    with pytest.raises(KeyError):
        expand_condition(MATRIX, "B99")


def test_inheritance_cycle_raises():
    cyclic = {"conditions": {
        "X": {"inherits": "Y"}, "Y": {"inherits": "X"},
    }}
    with pytest.raises(ValueError, match="cycle"):
        expand_condition(cyclic, "X")


def test_deep_merge_is_pure_and_overlay_wins():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    overlay = {"a": {"b": 9}}
    merged = deep_merge(base, overlay)
    assert merged == {"a": {"b": 9, "c": 2}, "d": 3}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}       # inputs unmodified


def test_expansion_is_deterministic():
    first = [expand_condition(MATRIX, cid) for cid in CONDITION_IDS]
    second = [expand_condition(MATRIX, cid) for cid in CONDITION_IDS]
    assert first == second


# ── config parity (repo convention: defaults.yaml mirrors typed models) ─────


def test_rqgm_eval_block_mirrors_defaults_yaml():
    defaults = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1]
            / "ari" / "configs" / "defaults.yaml"
        ).read_text(encoding="utf-8")
    )
    block = defaults["rqgm"]["eval"]
    typed = RQGMEvalConfig()
    assert block["enabled"] is typed.enabled is False
    assert block["scripted_components"] == typed.scripted_components == {}
    assert block["injection_specs"] == typed.injection_specs == []
    # Nothing on by default: an absent rqgm.eval block stays inert.
    assert ARIConfig().rqgm.eval.enabled is False
