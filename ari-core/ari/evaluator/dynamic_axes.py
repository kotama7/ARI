"""Dynamic evaluation-axis derivation for ARI BFTS.

The legacy ``llm_evaluator`` ships five domain-agnostic axes
(measurement_validity, comparative_rigor, novelty, reproducibility,
clarity_of_contribution) used for *every* run regardless of venue or
research direction. That is right for a generic floor but it cannot
express:

  - venue-specific judgement criteria  (e.g. SC demands AD/AE +
    scaling; NeurIPS demands statistical rigor)
  - run-specific evaluation tasks      (e.g. an SpMM kernel paper
    needs a STREAM-measured Bmax, while a graph-algorithm paper
    needs different evidence)

This module derives *additional* axes from two sources:

  1. ``rubric.score_dimensions``   →  one axis per dimension (Layer 2)
  2. ``experiment_plan`` §-tags    →  one axis per plan section (Layer 3)

Layer 1 (the generic floor) lives in ``llm_evaluator.AXIS_NAMES`` and
is always kept — additional axes are *added* on top, never replace.

Design contract:
  - Adding an axis is safe: missing scores default to 0 and dragged-down
    composites are the natural penalty
  - Removing an axis when a rubric/plan disappears is also safe: callers
    fall back to the generic floor
  - The set of axes for a given run is fully determined by the
    (rubric_id, experiment_plan) pair — so it's reproducible and the
    evaluator can be tested deterministically without LLM calls
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Axis definition shape
# ---------------------------------------------------------------------------


@dataclass
class AxisDef:
    """Single evaluation axis seen by the judge LLM.

    ``name`` is the JSON key the judge must populate (e.g.
    ``model_calibration_present``). ``description`` is the prompt-side
    wording. ``source`` records *why* this axis exists so callers can
    reason about its provenance ("generic" / "rubric:<id>" / "plan:<...>").
    ``weight`` is the harmonic-mean weight; per-source defaults are
    chosen so the generic floor still dominates by default.

    Weight design (Phase 3 + lineage decisions R):
      - Generic floor axes: 0.2 each (5 axes × 0.2 = 1.0 — the dominant
        signal). They are the venue-independent baseline of "is this
        actually a piece of research?".
      - Rubric-derived: 0.05 each. Multiple venue dimensions are
        added but no individual rubric axis is allowed to outweigh
        the generic floor — otherwise switching ``ARI_RUBRIC`` would
        cause a non-HPC run's composite to collapse just because the
        ML/theory rubric has many score_dimensions.
      - Plan-derived: 0.05 each. Same as rubric-derived; activated
        only when the plan explicitly mentions the axis topic.
    """

    name: str
    description: str
    source: str
    weight: float = 0.05
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 1: generic floor (mirrors llm_evaluator.AXIS_NAMES exactly)
# ---------------------------------------------------------------------------

GENERIC_AXES: tuple[AxisDef, ...] = (
    AxisDef(
        name="measurement_validity",
        description="Are numeric measurements present and methodologically sound?",
        source="generic",
        weight=0.2,
    ),
    AxisDef(
        name="comparative_rigor",
        description="Are results compared against baselines or prior work?",
        source="generic",
        weight=0.2,
    ),
    AxisDef(
        name="novelty",
        description="Does the work advance beyond existing approaches?",
        source="generic",
        weight=0.2,
    ),
    AxisDef(
        name="reproducibility",
        description="Is there enough detail for someone else to reproduce the result?",
        source="generic",
        weight=0.2,
    ),
    AxisDef(
        name="clarity_of_contribution",
        description="Is the scientific claim stated clearly and specifically?",
        source="generic",
        weight=0.2,
    ),
    # Phase 6 #5 — added as a low-weight generic axis (kept outside the
    # 0.2 floor block so it cannot dominate). Captures an issue that
    # appears across domains: HPC kernels claim model assumptions
    # (e.g. RFO=0 under non-temporal stores) the implementation does
    # not actually satisfy; ML papers claim equivariance the model
    # code does not preserve; theory claims rely on input properties
    # never verified in proofs. The judge LLM is explicitly asked to
    # cross-reference the plan's stated assumptions against the code
    # / artifacts and flag mismatches.
    AxisDef(
        name="claim_implementation_alignment",
        description=(
            "Do the implementation / artifacts actually satisfy the "
            "preconditions, properties, and contracts that the plan or "
            "model claims? (e.g. an HPC kernel claiming RFO=0 must "
            "actually use store instructions that bypass RFO; a paper "
            "claiming a property must demonstrate it in code or proof)."
        ),
        source="generic",
        weight=0.05,
    ),
)


GENERIC_AXIS_NAMES: frozenset[str] = frozenset(a.name for a in GENERIC_AXES)


# ---------------------------------------------------------------------------
# Sanitiser (axis names must be valid JSON keys / Python identifiers-ish)
# ---------------------------------------------------------------------------


_NAME_NORMALISE = re.compile(r"[^a-z0-9]+")


def _sanitise_axis_name(raw: str, *, suffix: str = "") -> str:
    base = _NAME_NORMALISE.sub("_", (raw or "").strip().lower()).strip("_")
    if not base:
        base = "axis"
    if suffix and not base.endswith(suffix):
        base = f"{base}_{suffix}".strip("_")
    return base[:80]


# ---------------------------------------------------------------------------
# Layer 2: rubric-derived axes
# ---------------------------------------------------------------------------


def rubric_to_axes(rubric: Any) -> list[AxisDef]:
    """Derive one axis per ``rubric.score_dimensions`` entry.

    Accepts either a Rubric dataclass instance (with ``score_dimensions``
    attribute) or a parsed dict shaped like the YAML content. Returns
    ``[]`` when the input is empty / malformed — callers degrade to the
    generic floor in that case.
    """
    if rubric is None:
        return []
    rid = ""
    dims: Iterable = ()
    if isinstance(rubric, dict):
        rid = str(rubric.get("id") or rubric.get("venue") or "rubric")
        dims = rubric.get("score_dimensions") or ()
    else:
        rid = str(getattr(rubric, "id", "") or getattr(rubric, "venue", "") or "rubric")
        dims = getattr(rubric, "score_dimensions", ()) or ()

    out: list[AxisDef] = []
    for d in dims:
        # Tolerate both dataclass-like (.name / .description) and dict.
        if isinstance(d, dict):
            name = str(d.get("name") or "").strip()
            desc = str(d.get("description") or "").strip()
        else:
            name = str(getattr(d, "name", "") or "").strip()
            desc = str(getattr(d, "description", "") or "").strip()
        if not name:
            continue
        sanitised = _sanitise_axis_name(name)
        # Skip axes that the generic floor already covers under the same
        # name — avoid double-weighting the same dimension.
        if sanitised in GENERIC_AXIS_NAMES:
            continue
        # Score-only dimensions like "overall" / "confidence" are venue
        # bookkeeping, not BFTS exploration drivers — skip them so they
        # don't drag the composite down for non-LLM reasons.
        if sanitised in {"overall", "confidence", "ethical_concerns"}:
            continue
        out.append(
            AxisDef(
                name=sanitised,
                description=desc[:200] or f"{name} (from rubric {rid})",
                source=f"rubric:{rid}",
                weight=0.05,
                extra={"rubric_dim": name},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Layer 3: plan-derived axes (from VirSci experiment_plan §-tags)
# ---------------------------------------------------------------------------

# Plan-derived axes are split into two layers so the vocabulary stays
# faithful to a domain-general framework:
#
#   _CORE_PLAN_KEYWORD_AXES   — patterns any quantitative paper could meet
#                               (ablation, baselines, statistical tests,
#                               reproducibility artifacts). Always active.
#
#   _DOMAIN_PLAN_KEYWORD_AXES — patterns specific to a venue family.
#                               Activated only when ``rubric.domain``
#                               matches the family key. Adding a new
#                               domain = add one entry; no other code
#                               changes. Existing runs in unrelated
#                               domains are unaffected.
#
# Rubric files can also declare their own ``plan_keyword_axes`` field;
# those run in addition to the core+domain set (handled in
# ``plan_to_axes``). This is the preferred extension point — code-side
# vocabulary should stay minimal.

_CORE_PLAN_KEYWORD_AXES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(ablation|controlled experiment|sensitivity analysis)\b", re.I),
     "ablation_present",
     "Are controlled ablations reported isolating each design choice?"),
    (re.compile(r"\b(baselines?|reference implementations?|comparisons?|state[- ]of[- ]the[- ]art|sota)\b", re.I),
     "baseline_comparison_present",
     "Is the work compared against established baselines or prior art?"),
    (re.compile(r"\b(seed|determinism|reproduce|reproducible|build script|run script|artifact)\b", re.I),
     "reproducibility_artifact_present",
     "Are seeds, build scripts, and run scripts captured for replication?"),
    (re.compile(
        r"\b(statistical|t[- ]tests?|wilcoxon|confidence intervals?|mean ± std|stderr|p[ -]values?|bootstrap)\b",
        re.I,
    ),
     "statistical_test_present",
     "Are results reported with statistical confidence (CI / std / hypothesis test)?"),
    # Phase 6 #3 — cross-domain pattern. Captures the "report results
    # separately for each variant of the core design choice" expectation
    # that recurs across SC (temporal vs non-temporal store policies),
    # ML (Adam vs SGD vs AdamW), theory (algorithm variants), HCI (UI
    # variants), etc. Distinct from `ablation_present`: ablation drops
    # one component to measure its contribution; policy_variants compares
    # *equivalent* alternatives head-to-head.
    (re.compile(
        r"\b(policy variants?|configuration sweeps?|variant comparison|"
        r"policy comparison|variant table|head[- ]to[- ]head)\b",
        re.I,
    ),
     "policy_variants_compared",
     "Are alternative variants of the core design choice compared "
     "head-to-head with separately-reported metrics?"),
)


# Each entry: (vocab_tuple, domain_match_substrings)
# domain_match_substrings is matched (case-insensitive, substring) against
# rubric.domain. The first hit wins per axis name (no double-counting).

_HPC_PLAN_KEYWORD_AXES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(pmax|bmax|stream|bandwidth ceiling|peak compute)\b", re.I),
     "model_calibration_present",
     "Are Pmax/Bmax measured (e.g. STREAM) and the model fitted quantitatively?"),
    (re.compile(r"\b(roofline|loopline|predicted vs measured|model validation)\b", re.I),
     "model_validation_present",
     "Is the predictive model validated against measurements (predicted vs measured)?"),
    (re.compile(r"\b(strong scaling|weak scaling|core sweep|node scaling|MPI scaling)\b", re.I),
     "scaling_study_present",
     "Is a strong/weak scaling study reported across cores/sockets/nodes?"),
    (re.compile(r"\b(hardware counter|perf|likwid|vtune|cache miss|tlb|cycle accurate)\b", re.I),
     "hardware_counter_evidence",
     "Are hardware-counter measurements (cache misses, TLB, bandwidth) reported?"),
    (re.compile(r"\b(MKL|oneMKL|cuBLAS|cuSPARSE|MAGMA|Eigen|BLAS)\b", re.I),
     "optimised_library_baseline_present",
     "Is an optimised vendor/library baseline included as comparison?"),
)

_ML_PLAN_KEYWORD_AXES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(cross.?validation|k.?fold|leave.?one.?out)\b", re.I),
     "cross_validation_present",
     "Is k-fold or held-out cross-validation used to estimate generalisation?"),
    (re.compile(r"\b(hyperparameter (search|tuning|sweep)|grid search|random search|bayesian opt|optuna)\b", re.I),
     "hyperparameter_search_present",
     "Is a documented hyperparameter search performed (not ad-hoc tuning)?"),
    (re.compile(r"\b(ROC|PR curve|F1 score|precision[ -]?recall|AUC|AUROC)\b", re.I),
     "classification_metrics_present",
     "Are appropriate classification metrics (ROC/PR/F1/AUC) reported?"),
    (re.compile(r"\b(train.?test split|held.?out|test set|validation set|dev set)\b", re.I),
     "held_out_eval_present",
     "Is evaluation done on a held-out test set (not the training set)?"),
    (re.compile(r"\b(multiple seeds|N runs|run.?to.?run|stochastic variance|standard error)\b", re.I),
     "multi_seed_runs_present",
     "Are multiple seeds reported so stochastic variance is quantified?"),
)

_THEORY_PLAN_KEYWORD_AXES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(theorem|lemma|proposition|corollary)\b", re.I),
     "formal_proof_present",
     "Are formal claims stated as numbered theorems/lemmas with proofs?"),
    (re.compile(r"\b(complexity|big.?o|polynomial.?time|NP[- ]hard|np[- ]complete)\b", re.I),
     "complexity_analysis_present",
     "Is computational complexity (or hardness) analysed explicitly?"),
    (re.compile(r"\b(tight bound|lower bound|upper bound|asymptotic)\b", re.I),
     "bound_analysis_present",
     "Are matching upper/lower bounds (or tightness arguments) given?"),
)

_HCI_PLAN_KEYWORD_AXES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\b(user study|participant|between.?subjects|within.?subjects)\b", re.I),
     "user_study_present",
     "Is a user study with participants conducted?"),
    (re.compile(r"\b(IRB|ethics review|informed consent|ethics board)\b", re.I),
     "ethics_compliance_present",
     "Is IRB / ethics-board approval (or rationale for waiver) documented?"),
    (re.compile(r"\b(likert|survey|questionnaire|qualitative coding)\b", re.I),
     "subjective_measurement_present",
     "Are subjective measurements (Likert / survey / qualitative coding) reported?"),
)


# Domain → vocabulary mapping. The keys are matched (case-insensitive,
# substring) against ``rubric.domain``. First hit wins.
_DOMAIN_VOCABULARIES: tuple[tuple[tuple[str, ...], tuple[tuple[re.Pattern[str], str, str], ...]], ...] = (
    (("hpc", "supercomputing", "systems"), _HPC_PLAN_KEYWORD_AXES),
    (("ml ", "machine learning", "ai", "deep learning"), _ML_PLAN_KEYWORD_AXES),
    (("theor", "algorithms"), _THEORY_PLAN_KEYWORD_AXES),
    (("hci", "human-computer", "human computer", "interaction"), _HCI_PLAN_KEYWORD_AXES),
)


def _resolve_domain_vocabulary(
    rubric_domain: str | None,
) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    """Pick the domain-specific vocabulary for a given ``rubric.domain``."""
    if not rubric_domain:
        return ()
    dom = rubric_domain.lower()
    for keys, vocab in _DOMAIN_VOCABULARIES:
        for k in keys:
            if k in dom:
                return vocab
    return ()


def _rubric_custom_plan_axes(
    rubric: Any,
) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    """Read ``plan_keyword_axes:`` from a rubric (extension point).

    Each entry is a dict ``{pattern: str, axis: str, description: str}``.
    Bad entries are skipped silently — a malformed regex must not crash
    the evaluator.
    """
    if rubric is None:
        return ()
    raw = (rubric.get("plan_keyword_axes") if isinstance(rubric, dict)
           else getattr(rubric, "plan_keyword_axes", None))
    if not raw:
        return ()
    out: list[tuple[re.Pattern[str], str, str]] = []
    for entry in raw:
        if isinstance(entry, dict):
            pat_s = entry.get("pattern") or ""
            axis = entry.get("axis") or ""
            desc = entry.get("description") or ""
        else:
            pat_s = getattr(entry, "pattern", "") or ""
            axis = getattr(entry, "axis", "") or ""
            desc = getattr(entry, "description", "") or ""
        if not pat_s or not axis:
            continue
        try:
            pat = re.compile(pat_s, re.I)
        except re.error:
            continue
        out.append((pat, _sanitise_axis_name(axis), desc[:200] or axis))
    return tuple(out)


def plan_to_axes(
    experiment_plan: str,
    *,
    rubric: Any = None,
) -> list[AxisDef]:
    """Derive axes from the VirSci experiment_plan §-tag content.

    Layered vocabulary (most general first):
      1. ``_CORE_PLAN_KEYWORD_AXES``       — applies to all runs
      2. domain vocabulary (``rubric.domain``-gated)
      3. rubric-declared ``plan_keyword_axes`` (per-rubric extension)

    Domains the vocabulary doesn't cover (yet) simply produce no
    domain axes — the core layer still applies, so the result is
    domain-general by design.
    """
    if not experiment_plan:
        return []
    rubric_domain = ""
    if rubric is not None:
        rubric_domain = (
            rubric.get("domain") if isinstance(rubric, dict)
            else getattr(rubric, "domain", "")
        ) or ""
    vocabularies = (
        _CORE_PLAN_KEYWORD_AXES
        + _resolve_domain_vocabulary(rubric_domain)
        + _rubric_custom_plan_axes(rubric)
    )
    matched: list[AxisDef] = []
    seen: set[str] = set()
    for pat, axis_name, desc in vocabularies:
        if axis_name in seen:
            continue
        if pat.search(experiment_plan):
            matched.append(
                AxisDef(
                    name=axis_name,
                    description=desc,
                    source="plan",
                    weight=0.05,
                )
            )
            seen.add(axis_name)
    return matched


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def build_axes_for_run(
    *, rubric: Any = None, idea_data: dict | None = None
) -> list[AxisDef]:
    """Compose generic + rubric-derived + plan-derived axes for one run.

    Order of precedence: generic floor first (highest individual weights),
    then rubric, then plan. Duplicate names are collapsed into the first
    occurrence so the floor wins when names collide.

    The returned list is the source of truth for the BFTS evaluator's
    JSON schema — pass it to ``LLMEvaluator(axes=...)`` to opt into
    dynamic scoring while keeping legacy callers (which omit ``axes``)
    on the generic-floor path.
    """
    axes: list[AxisDef] = list(GENERIC_AXES)
    seen: set[str] = set(GENERIC_AXIS_NAMES)

    for a in rubric_to_axes(rubric):
        if a.name in seen:
            continue
        axes.append(a)
        seen.add(a.name)

    plan_text = ""
    if idea_data and isinstance(idea_data, dict):
        ideas = idea_data.get("ideas") or []
        if ideas and isinstance(ideas[0], dict):
            # Newer generate_ideas variants emit a structured plan
            # ({"Design Steps": [...], "Ideal Outcomes": ...}); flatten to
            # text so the regex-based plan_to_axes still finds keywords.
            _plan = ideas[0].get("experiment_plan") or ""
            plan_text = _plan if isinstance(_plan, str) else json.dumps(
                _plan, ensure_ascii=False, default=str
            )
    for a in plan_to_axes(plan_text, rubric=rubric):
        if a.name in seen:
            continue
        axes.append(a)
        seen.add(a.name)

    return axes


def axes_to_prompt_section(axes: list[AxisDef]) -> str:
    """Render an axis list as a JSON-schema-style prompt block."""
    if not axes:
        return ""
    lines = [
        "  axis_scores: dict with EXACTLY these keys, each a float in 0.0-1.0:",
    ]
    for a in axes:
        lines.append(f"    - {a.name}: {a.description}")
    lines.append(
        "    Score 0.0 on an axis when that dimension is absent or fatally weak. "
        "Score toward 1.0 as the dimension approaches publishable quality. "
        "These axes are combined via weighted harmonic mean, so a low score "
        "on ANY axis drags the overall score down — differentiate axes deliberately."
    )
    lines.append(
        "  axis_rationales: dict with the same keys; each value is one sentence "
        "explaining the score for that axis."
    )
    return "\n".join(lines)


def axes_to_weights(axes: list[AxisDef]) -> dict[str, float]:
    """Return ``{name: weight}`` extracted from an axis list."""
    return {a.name: float(a.weight) for a in axes}
