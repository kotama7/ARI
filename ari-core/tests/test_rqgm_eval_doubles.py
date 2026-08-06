"""RQGM Task 13 — scripted component doubles (docs/plans/ari_rqgm/13 §5.3/§9).

The eval-double registry carries exactly the documented key set; doubles are
LLM-free and deterministic; ``resolve_double`` refuses any substitution
unless ``rqgm.eval.enabled`` (the doubles-cannot-leak-into-production
guarantee, §8); and each double's failure output is caught by the SAME
deterministic checks production components face (Task 06 record validation,
Task 03/04 schema checks, Task 07 dry-run).
"""

from __future__ import annotations

import pytest

from ari.config import ARIConfig
from ari.rqgm.evaluation.doubles import (
    DOUBLE_KEYS,
    EVAL_DOUBLE_REGISTRY,
    EVAL_DOUBLE_TIER,
    EvalDoubleRefusedError,
    eval_enabled,
    resolve_double,
    scripted_components,
)


def _cfg(enabled: bool, components: dict) -> ARIConfig:
    return ARIConfig.model_validate({
        "rqgm": {"eval": {"enabled": enabled,
                          "scripted_components": components}},
    })


# ── registry surface ─────────────────────────────────────────────────────────


def test_registry_keys_match_documented_set():
    assert DOUBLE_KEYS == (
        "adversary/always_attack",
        "judge/always_validate",
        "judge/never_validate",
        "generator/schema_violating",
        "prompt_mutator/degenerate",
    )
    for key in DOUBLE_KEYS:
        double = EVAL_DOUBLE_REGISTRY.resolve(key)
        role, name = key.split("/")
        assert double.role == role
        assert double.double_name == name


def test_unknown_double_raises_with_valid_keys():
    with pytest.raises(KeyError):
        EVAL_DOUBLE_REGISTRY.resolve("judge/fair_and_balanced")


def test_eval_double_tier_is_reserved():
    assert EVAL_DOUBLE_TIER == "eval_double"


def test_eval_double_tier_denied_by_kernel_capability_check():
    """Plan 13 §7: the eval_double tier holds NO constitutional authority —
    the deny-by-default CAPABILITY_MATRIX has no eval_double entry, so the
    kernel refuses any (action, resource) for an eval-double actor."""
    from ari.rqgm.kernel import ConstitutionalKernel
    from ari.rqgm.kernel_rules import CAPABILITY_MATRIX

    assert not [key for key in CAPABILITY_MATRIX
                if key[1] == EVAL_DOUBLE_TIER]
    report = ConstitutionalKernel().validate_capability(
        ("adversary", EVAL_DOUBLE_TIER), "write", "frontier"
    )
    assert not report.ok
    assert report.blocking
    assert {v.code for v in report.violations} == {"CK-ACC-001"}


# ── production-leak refusal (plan 13 §8) ─────────────────────────────────────


def test_resolve_refused_when_eval_disabled():
    cfg = _cfg(False, {"judge": "always_validate"})
    assert eval_enabled(cfg) is False
    assert scripted_components(cfg) == {"judge": "always_validate"}
    with pytest.raises(EvalDoubleRefusedError):
        resolve_double(cfg, "judge")


def test_resolve_none_without_substitution():
    assert resolve_double(_cfg(True, {}), "judge") is None
    # And the shipped default config never resolves a double.
    assert resolve_double(ARIConfig(), "judge") is None


def test_resolve_returns_double_when_enabled():
    cfg = _cfg(True, {"adversary": "always_attack"})
    double = resolve_double(cfg, "adversary")
    assert double is EVAL_DOUBLE_REGISTRY.resolve("adversary/always_attack")


def test_helpers_accept_raw_dict_config():
    cfg = ARIConfig()
    raw = type("Cfg", (), {"rqgm": type("R", (), {
        "eval": {"enabled": True,
                 "scripted_components": {"judge": "never_validate"}},
    })()})()
    assert eval_enabled(raw) is True
    assert resolve_double(raw, "judge").double_name == "never_validate"
    assert eval_enabled(cfg) is False


# ── failure behavior hits the real detection code paths ──────────────────────


def test_always_attack_records_are_schema_valid_and_deterministic():
    from ari.rqgm.adversarial.records import raw_attack_violations

    adversary = EVAL_DOUBLE_REGISTRY.resolve("adversary/always_attack")
    first = adversary.attacks("n1", epoch_id="ep_000001")
    second = adversary.attacks("n1", epoch_id="ep_000001")
    assert [a.to_dict() for a in first] == [a.to_dict() for a in second]
    for attack in first:
        # The overreach is unconditional attacking, not malformed records:
        # the schema check must PASS so the judge is what catches it.
        assert raw_attack_violations(attack) == []
        assert attack.severity_claimed == "high"


def test_judge_doubles_split_on_validated_record_construction():
    from ari.rqgm.adversarial.records import (
        AdversarialRuleError,
        make_validated_attack_record,
    )

    adversary = EVAL_DOUBLE_REGISTRY.resolve("adversary/always_attack")
    attack = adversary.attacks("n1", epoch_id="ep_000001")[0]

    always = EVAL_DOUBLE_REGISTRY.resolve("judge/always_validate")
    judgment = always.judge(attack)
    validated = make_validated_attack_record(
        judgment, attack, record_id="vat_000000"
    )
    assert validated.source_node_id == "n1"
    assert validated.verdict == "valid"

    never = EVAL_DOUBLE_REGISTRY.resolve("judge/never_validate")
    with pytest.raises(AdversarialRuleError):
        # Invariant 9: an invalid verdict can never mint a validated record.
        make_validated_attack_record(
            never.judge(attack), attack, record_id="vat_000001"
        )


def test_schema_violating_generator_caught_by_kernel():
    from ari.rqgm.kernel import ConstitutionalKernel

    generator = EVAL_DOUBLE_REGISTRY.resolve("generator/schema_violating")
    proposals = generator.generate()
    assert proposals == generator.generate()      # deterministic
    kernel = ConstitutionalKernel()
    for proposal in proposals:
        report = kernel.validate_record_schema(proposal)
        assert not report.ok
        assert any("missing envelope fields" in v.detail
                   for v in report.violations)


def test_degenerate_mutator_fails_stage1_dry_run():
    from ari.rqgm.prompt_evolution import static_validation_failures
    from ari.rqgm.prompt_records import candidate_from_dict

    mutator = EVAL_DOUBLE_REGISTRY.resolve("prompt_mutator/degenerate")
    candidate = candidate_from_dict(mutator.propose("reviewer"))
    failures = static_validation_failures(candidate, mutator.template_text)
    assert any("prompt_hash does not match" in f for f in failures)
    assert any("forbidden placeholders" in f for f in failures)
    # Never activated: the candidate is born (and stays) a candidate.
    assert candidate.status == "candidate"


# ── offline guard (P2) ───────────────────────────────────────────────────────


def test_doubles_module_is_llm_free():
    import ari.rqgm.evaluation.doubles as mod

    text = open(mod.__file__, encoding="utf-8").read()
    for forbidden in ("import litellm", "import requests", "import urllib",
                      "import socket", "import http", "import random",
                      "llm_complete", "completion("):
        assert forbidden not in text, forbidden
