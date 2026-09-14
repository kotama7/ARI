"""Clean-room contamination policy tables + deterministic screen (RQGM Task 08).

Layer-0 pure-data/pure-function module (``docs/concepts/rqgm_architecture.md``,
"Key invariants" — clean-room contamination rules;
``docs/reference/rqgm_schemas.md``, "Clean-room schemas (Task 08)" for the
const-false forbidden-input flags): the closed allowed/forbidden input split
of the clean-room regeneration path, the closed ``CleanRoomInputBundle`` field
set, the closed FailureSummary class vocabulary, and the word-shingle
contamination screen.
Imported by BOTH the ConstitutionalKernel (CK-CLN-001/CK-CLN-002, Task 04's
entry points) and :mod:`ari.rqgm.clean_room` — single source of truth, the
``transition_rules`` layering precedent.

The split's rationale: allowed inputs describe *what the role
must do*; forbidden inputs describe *how the failed incumbent did it* or
*what specifically defeated it*. Excluding the latter prevents inheriting the
retired prompt's blind spots and overfitting the successor to the exact
attack strings.

Deterministic, pure stdlib: no LLM calls, no I/O, no randomness, no wall
clock (P2). Extending any closed vocabulary here is a reviewed code diff,
never a config change.
"""

from __future__ import annotations

import re

CLEAN_ROOM_SCHEMA_VERSION = 1

#: Version stamp of the deterministic contamination screen, recorded into
#: every ``abstract_failure_summary.contamination_screen`` so a bundle always
#: says which screen version cleared it.
SCREEN_VERSION = 1

#: Screen policy defaults — 8-token shingles, and a single overlapping
#: shingle fails the candidate (config-tunable via
#: ``rqgm.clean_room.contamination_screen``; the kernel receives them as
#: injected tolerances — the policy itself is code).
DEFAULT_SHINGLE_K = 8
DEFAULT_FAIL_ON_ANY_HIT = True

REQUEST_RECORD_TYPE = "clean_room_generation_request"

#: ``CleanRoomGenerationRequest.status`` values — the closed status enum of
#: ``clean_room_request.schema.json`` (``docs/reference/rqgm_schemas.md``,
#: "Clean-room schemas (Task 08)").
REQUEST_STATUSES: tuple[str, ...] = (
    "pending",
    "generating",
    "generated",
    "rejected_contaminated",
    "failed",
    "superseded",
)

#: The sole v1 trigger: a RetirementEvent is the only thing that opens a
#: clean-room regeneration request — nothing else may originate one.
REQUEST_TRIGGERS: tuple[str, ...] = ("retirement_event",)

#: The complete, closed allowed-input set — nothing else may cross into the
#: generator's context.
ALLOWED_INPUT_KEYS: tuple[str, ...] = (
    "role_spec",
    "output_schema",
    "constitutional_constraints",
    "abstract_failure_summary",
    "replay_requirements",
    "cost_budget",
)

#: The forbidden-input set: ``const: false`` flags in the request schema — a
#: request setting any of them true is schema-invalid and blocked by the
#: kernel before assembly.
FORBIDDEN_INPUT_KEYS: tuple[str, ...] = (
    "retired_prompt_text",
    "retired_fewshot_examples",
    "retired_prompt_reasoning",
    "raw_attack_text",
    "target_defense_text",
)

#: The closed ``CleanRoomInputBundle`` field set
#: (``additionalProperties: false``): the bundle is the ENTIRE generator
#: context besides the committed meta-prompt, so a closed field set is what
#: makes the Layer-A constructive-containment argument hold.
BUNDLE_FIELDS: tuple[str, ...] = (
    "bundle_id",
    "request_id",
    "bundle_hash",
    "role_spec",
    "output_schema",
    "constitutional_constraints",
    "abstract_failure_summary",
    "replay_requirements",
    "cost_budget",
)

#: Closed FailureSummary class vocabulary: the five reviewer-failure
#: classes plus Task 06's committed seven adversarial case types (the v1
#: compressor folds ``abstract_view.case_type`` straight into a class).
#: Extended ONLY by committing a new enum value here.
FAILURE_CLASSES: tuple[str, ...] = (
    "missed_metric_gaming",
    "overconfident_acceptance",
    "missing_evidence_refs",
    "overclaim_pass_through",
    "calibration_drift",
    "overclaim",
    "metric_gaming",
    "prior_art",
    "reproducibility",
    "evidence_gap",
    "cost_explosion",
    "prompt_injection",
)

#: ``source_refs`` entries must be record IDS — never quoted text, since a
#: quoted excerpt would smuggle the retired prompt's wording into the bundle.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ── deterministic contamination screen (word-shingle overlap) ───────────────


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace runs, drop punctuation-only tokens —
    normalization so case/whitespace/punctuation edits cannot evade the
    screen. Pure function (P2)."""
    return " ".join(_TOKEN_RE.findall(str(text).lower()))


def shingles(text: str, k: int = DEFAULT_SHINGLE_K) -> set:
    """Word *k*-shingles of the normalized text as tuples. Texts shorter
    than *k* tokens yield the empty set (the plan's exact semantics — an
    under-length fragment is not a match unit)."""
    toks = normalize_text(text).split(" ") if normalize_text(text) else []
    k = max(1, int(k))
    return {tuple(toks[i:i + k]) for i in range(max(0, len(toks) - k + 1))}


def contamination_hits(
    candidate_text: str,
    forbidden_docs: dict,
    allowlist_docs=(),
    *,
    k: int = DEFAULT_SHINGLE_K,
) -> dict:
    """Per-forbidden-doc shingle overlaps after allowlist subtraction.

    Returns ``{doc_id: [<= 5 evidence shingles, sorted]}``; the empty dict
    means clean. Text shared with the allowed inputs (*allowlist_docs*) is
    legitimate and never triggers a hit.
    """
    cand = shingles(candidate_text, k)
    if not cand:
        return {}
    allow: set = set()
    for doc in allowlist_docs or ():
        allow |= shingles(doc, k)
    hits: dict = {}
    for doc_id in sorted(forbidden_docs or {}):
        overlap = (cand & shingles(forbidden_docs[doc_id], k)) - allow
        if overlap:
            # Bounded, deterministic evidence sample.
            hits[str(doc_id)] = [" ".join(s) for s in sorted(overlap)[:5]]
    return hits


# ── FailureSummary admissibility (bundle-entry contract) ────────────────────


def failure_summary_failures(summary) -> list[str]:
    """Why *summary* is NOT bundle-admissible (empty list == admissible).

    Shape rules only — closed class vocabulary, numeric aggregates,
    ids-only ``source_refs``, and the mandatory contamination-screen stamp.
    Screening the text fields against a forbidden corpus is the kernel's
    job (``validate_clean_room_bundle``), which has the corpus in hand.
    """
    out: list[str] = []
    if not isinstance(summary, dict):
        return ["abstract_failure_summary is not an object"]
    classes = summary.get("failure_classes")
    if not isinstance(classes, (list, tuple)):
        out.append("failure_classes is missing or not a list")
    else:
        for value in classes:
            if str(value) not in FAILURE_CLASSES:
                out.append(
                    f"failure_classes value {value!r} is outside the closed "
                    "vocabulary"
                )
    for field in ("class_counts", "severity_histogram"):
        block = summary.get(field)
        if block is None:
            continue
        if not isinstance(block, dict) or any(
            not isinstance(v, (int, float)) or isinstance(v, bool)
            for v in block.values()
        ):
            out.append(f"{field} must contain numeric aggregates only")
    reqs = summary.get("behavioral_requirements")
    if reqs is not None and (
        not isinstance(reqs, (list, tuple))
        or any(not isinstance(r, str) for r in reqs)
    ):
        out.append("behavioral_requirements must be a list of strings")
    for ref in summary.get("source_refs") or ():
        if not _ID_RE.match(str(ref)):
            out.append(
                f"source_refs entry {str(ref)[:40]!r} is not a record id "
                "(ids only, never quoted text)"
            )
    screen = summary.get("contamination_screen")
    if not isinstance(screen, dict) or screen.get("passed") is not True:
        out.append(
            "contamination_screen.passed must be present and true "
            "(creation-time screening stamp)"
        )
    return out
