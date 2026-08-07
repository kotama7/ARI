"""Adversarial evolution loop (RQGM Task 06; docs/concepts/rqgm_architecture.md,
"Key invariants" — raw attacks never touch scores).

The attack → defense → adjudication loop for ``ari_rqgm`` mode: an
AdversaryEngine that attacks research *artifacts* (never components), a
Defender that rebuts, an ArtifactJudge that adjudicates, and the
AdversarialReplayPool that accumulates Judge-validated failure cases for
next-epoch prompt evolution (Task 07) and clean-room regeneration (Task 08).

Two constitutional rules anchor the package (global invariants 8 and 9):

1. **Raw adversary attacks NEVER touch the BFTS score.** Only
   Judge-adjudicated :class:`~ari.rqgm.adversarial.records
   .ValidatedAttackRecord` s feed the bounded utility penalty; a
   RawAttackRecord/DefenderResponse/``invalid`` judgment has zero effect on
   ``_scientific_score``, frontier ranking, or pruning.
2. **Adversaries attack artifacts, never components.**
   ``target_artifact.type`` comes from the closed §5.2 set; component-target
   smuggling is schema-invalid by construction.

Internal package — never exported via ``ari.public.*``, never imported on the
default ``simple_bfts`` path. Under ``simple_bfts`` (or
``rqgm.adversarial.enabled: false``) nothing here is constructed and no file
is written. All prompt-defined actors ride the injectable ``llm`` seam
(deterministic fakes in tests, never a real LLM), and every decision that is
not an audited LLM call is deterministic (P2).
"""

from __future__ import annotations

from ari.rqgm.adversarial.engine import (
    AdversaryEngine,
    ArtifactJudge,
    Defender,
    UtilityPenaltyPolicy,
    apply_utility_penalty,
    should_attack,
)
from ari.rqgm.adversarial.pool import AdversarialCaseLog, AdversarialReplayPool
from ari.rqgm.adversarial.round import AdversarialRound

__all__ = [
    "AdversaryEngine",
    "Defender",
    "ArtifactJudge",
    "UtilityPenaltyPolicy",
    "apply_utility_penalty",
    "should_attack",
    "AdversarialCaseLog",
    "AdversarialReplayPool",
    "AdversarialRound",
]
