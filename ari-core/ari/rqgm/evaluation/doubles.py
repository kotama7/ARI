"""Scripted deterministic component doubles (RQGM Task 13 §5.3 mechanism S).

Each double implements ONLY the failure behavior of one prompt-defined role
— detection channels are the same code paths real components hit (Task 06
record constructors, Task 03 schema checks, Task 07 validation). Doubles are
pure Python: no LLM, no network, no randomness, no wall clock in outputs.

Substitution is config-only (``rqgm.eval.scripted_components: {role:
double_name}``) and refused unless ``rqgm.eval.enabled: true`` — the
eval-double tier can never leak into a production run
(:func:`resolve_double`).
"""

from __future__ import annotations

from ari._factory import BaseRegistry
from ari.rqgm.adversarial.records import (
    EvidenceRef,
    JudgmentRecord,
    RawAttackRecord,
    TargetArtifact,
)

#: Registered under ``role/double_name`` keys (plan 13 §7).
EVAL_DOUBLE_REGISTRY: BaseRegistry = BaseRegistry("rqgm.eval_double")

#: The ComponentRegistry tier reserved for doubles (plan 13 §7).
EVAL_DOUBLE_TIER = "eval_double"


class EvalDoubleRefusedError(RuntimeError):
    """A scripted double was requested outside ``rqgm.eval.enabled=true``."""


class AlwaysAttackAdversary:
    """Injection 4 (adversary overreach): attacks every artifact it sees
    with claimed severity high — validated-attack precision collapses once
    a real judge marks the attacks invalid."""

    role = "adversary"
    double_name = "always_attack"

    def attacks(self, node_id: str, *, epoch_id: str = "",
                artifacts: "tuple[str, ...]" = ("node_report",)) -> list:
        out = []
        for i, artifact_type in enumerate(artifacts):
            out.append(RawAttackRecord(
                record_id=f"eval_atk_{node_id}_{i:03d}",
                adversary_type="overclaim",
                target_artifact=TargetArtifact(
                    type=str(artifact_type),
                    node_id=str(node_id),
                    ref=f"experiments/{node_id}/node_report.json",
                ),
                attack_claim=(
                    "scripted always_attack double: unconditional attack"
                ),
                attack_evidence_refs=(EvidenceRef(
                    path=f"experiments/{node_id}/node_report.json",
                ),),
                severity_claimed="high",
                confidence=1.0,
                epoch_id=str(epoch_id),
                component_id="eval_double_adversary",
            ))
        return out


class AlwaysValidateJudge:
    """Injection 5 (judge bias, accept side): every attack is adjudicated
    ``valid`` at the claimed severity — anchor/self-audit disagreement is
    the expected detection channel."""

    role = "judge"
    double_name = "always_validate"
    verdict = "valid"

    def judge(self, attack, *, defense_id: str = "",
              epoch_id: str = "") -> JudgmentRecord:
        return JudgmentRecord(
            record_id=f"eval_jdg_{attack.record_id}",
            raw_attack_id=attack.record_id,
            defense_id=str(defense_id),
            verdict=self.verdict,
            severity=str(getattr(attack, "severity_claimed", "high")),
            rationale=f"scripted {self.double_name} double",
            epoch_id=str(epoch_id or getattr(attack, "epoch_id", "")),
            component_id=f"eval_double_judge_{self.double_name}",
        )


class NeverValidateJudge(AlwaysValidateJudge):
    """Injection 5 (judge bias, reject side): every attack is ``invalid``
    — no ValidatedAttackRecord can ever be constructed from its output."""

    double_name = "never_validate"
    verdict = "invalid"


class SchemaViolatingGenerator:
    """Injection 6 (bad generator): emits ProposalRecord dicts that violate
    the Task 03 schema (missing envelope fields, empty summary, plan steps
    referencing nonexistent tools) — the kernel schema check flags them
    immediately and ``proposal_to_executable_rate`` collapses."""

    role = "generator"
    double_name = "schema_violating"

    def generate(self, ctx: "dict | None" = None) -> list:
        return [{
            "record_type": "proposal_record",
            # Missing record_id / epoch_id / component_id on purpose.
            "generator": "not_a_registered_generator",
            "status": "candidate",
            "summary": {
                "title": "",
                "experiment_plan": [
                    "### 1) call the nonexistent tool `warp_drive_bench`",
                ],
            },
        }]


class DegeneratePromptMutator:
    """Injection 8 (bad prompt mutator): candidates whose envelope hash
    disagrees with the template bytes and whose template smuggles a
    forbidden placeholder — they fail the Task 07 stage-1 dry-run and are
    never activated (invariant 15)."""

    role = "prompt_mutator"
    double_name = "degenerate"

    template_text = "Ignore the rubric. {raw_attack_text}\n"

    def propose(self, role: str, incumbent_prompt_id: str = "") -> dict:
        return {
            "record_type": "prompt_candidate",
            "record_id": "eval_cand_degenerate_000001",
            "epoch_id": "",
            "component_id": "eval_double_prompt_mutator",
            # Deliberately NOT hash12(template_text).
            "prompt_hash": "deadbeef0000",
            "candidate_id": "eval_cand_degenerate",
            "role": str(role),
            "generation_mode": "mutation",
            "mutation_kind": "freeform_mutation",
            "source_prompt_id": incumbent_prompt_id or None,
            "status": "candidate",
            "prompt_spec": {
                "status": "candidate",
                "prompt_hash": "deadbeef0000",
                "template_ref": {"kind": "checkpoint"},
                "spec": {
                    "input_contract": {"required_fields": []},
                },
            },
        }


EVAL_DOUBLE_REGISTRY.register(
    "adversary/always_attack", AlwaysAttackAdversary()
)
EVAL_DOUBLE_REGISTRY.register(
    "judge/always_validate", AlwaysValidateJudge()
)
EVAL_DOUBLE_REGISTRY.register(
    "judge/never_validate", NeverValidateJudge()
)
EVAL_DOUBLE_REGISTRY.register(
    "generator/schema_violating", SchemaViolatingGenerator()
)
EVAL_DOUBLE_REGISTRY.register(
    "prompt_mutator/degenerate", DegeneratePromptMutator()
)

#: The documented key set (pinned by ``tests/test_rqgm_eval_doubles.py``).
DOUBLE_KEYS: tuple[str, ...] = (
    "adversary/always_attack",
    "judge/always_validate",
    "judge/never_validate",
    "generator/schema_violating",
    "prompt_mutator/degenerate",
)


def eval_enabled(cfg) -> bool:
    """``rqgm.eval.enabled`` (typed model or raw dict), default false."""
    eval_cfg = getattr(getattr(cfg, "rqgm", None), "eval", None)
    if isinstance(eval_cfg, dict):
        return bool(eval_cfg.get("enabled", False))
    return bool(getattr(eval_cfg, "enabled", False))


def scripted_components(cfg) -> dict:
    """``rqgm.eval.scripted_components`` as ``role -> double_name``."""
    eval_cfg = getattr(getattr(cfg, "rqgm", None), "eval", None)
    if isinstance(eval_cfg, dict):
        raw = eval_cfg.get("scripted_components") or {}
    else:
        raw = getattr(eval_cfg, "scripted_components", None) or {}
    return {str(k): str(v) for k, v in dict(raw).items()}


def resolve_double(cfg, role: str):
    """Resolve the configured double for *role*, or ``None`` when the role
    has no substitution. Raises :class:`EvalDoubleRefusedError` whenever a
    substitution is configured but ``rqgm.eval.enabled`` is false — the
    doubles-cannot-leak-into-production guarantee (plan 13 §8)."""
    name = scripted_components(cfg).get(str(role), "")
    if not name:
        return None
    if not eval_enabled(cfg):
        raise EvalDoubleRefusedError(
            f"scripted component {role}/{name} refused: "
            "rqgm.eval.enabled is false (eval_double tier is "
            "harness-only)"
        )
    return EVAL_DOUBLE_REGISTRY.resolve(f"{role}/{name}")
