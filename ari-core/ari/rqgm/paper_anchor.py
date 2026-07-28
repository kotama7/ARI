"""APReS-equivalent ground-truth anchor for the paper reviewer (paper-archive
Task 04, docs/plans/ari_rqgm_paper/04).

The co-evolving ``paper_reviewer`` (a governed EVALUATOR role, plan 03) earns
trust the way the RQGM paper's APReS evaluator does: by AGREEING with a
held-out, human-labelled accept/reject anchor corpus. The manuscript WRITER is
ALSO anchored (§5.1, revised 2026-07-16) — but to a ground truth the RQGM
paper's writer never had: ARI writes about REAL experiments, so the Layer-0
claim-evidence hard gate scores a draft's faithfulness DETERMINISTICALLY
(:func:`writer_faithfulness_score`). A writer whose drafts regress on that
faithfulness is a real SANCTION SOURCE (over-accepted-AND-unfaithful drafts
bind the writer, docs/plans/ari_rqgm_paper/05), its role OPENS, and its PROMPT
co-evolves via the existing T6 — the coding-domain shape (a deterministic
verifier + the co-evolving reviewer), not the paper's anchor-less writer. The
curated human corpus is still the REVIEWER's anchor; the writer's anchor is the
gate ARI already computes for free (zero extra data). This module owns:

* the ``paper_anchor_corpus.jsonl`` schema (accept/reject reference
  manuscripts, each declaring a REQUIRED ``label_source``);
* the deterministic, run-fixed held-out split (:func:`assign_split`, P2-pure);
* the machine-enforced ``max_bootstrap_label_fraction`` cap over the corpus
  AND the held-out subset — a breach REFUSES the corpus (returns ``None`` =>
  the §5.9 degraded on-ramp), NEVER raises into the run;
* the held-out agreement metric (:func:`paper_reviewer_agreement`) wired into
  the EXISTING ``anchor_evaluation`` stage / ``AnchorBoard.board_score``;
* the ``paper_utility_policy`` freeze (:func:`capture_paper_utility_policy`),
  mirroring ``state.capture_utility_policy`` and adding the anchor identity +
  both label-source mixes to the paper epoch fingerprint.

This module invents NO utility machinery of its own: the cross-epoch REWRITE
of the utility policy rides parent Task 14 (governed utility evolution)
topology-agnostically; ``capture_paper_utility_policy`` is the paper-phase
INSTANCE of that governed capture (§5.5). Pure stdlib + ``ari.rqgm`` types:
no LLM calls, no network, no randomness (P2). ``load_anchor_corpus`` NEVER
raises into the run — every integrity failure degrades to ``None`` (no anchor
gate), never a crash and never a silently weaker anchor.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ari.rqgm.events import canonical_json, hash12

log = logging.getLogger(__name__)

PAPER_ANCHOR_CORPUS_FILENAME = "paper_anchor_corpus.jsonl"
PAPER_ANCHOR_CASE_RECORD_TYPE = "PaperAnchorCase"

#: The WRITER's anchor-board case type (§5.1, revised 2026-07-16). Distinct
#: from :data:`PAPER_ANCHOR_CASE_RECORD_TYPE`: a ``PaperAnchorCase`` is a
#: human-labelled REFERENCE manuscript (the reviewer's ground truth), whereas
#: this case carries the Layer-0 claim gate's deterministic faithfulness score
#: for the writer's OWN draft. Both ride the ONE pool the governance audit
#: hands to ``adjudicate_motion`` (``runtime.py`` ``audit_pool``), and
#: ``board_score`` is subject-keyed, so each subject only ever reads its own
#: evidence. The two are kept as SEPARATE cases (never a writer result stamped
#: onto a reference-manuscript case) so the ImpeachmentOutcome's
#: ``anchor_refs`` cite the writer's real draft — a writer sanction may never
#: cite a manuscript the writer never wrote.
WRITER_FAITHFULNESS_CASE_RECORD_TYPE = "PaperWriterFaithfulnessCase"

#: The fixed, non-evolving origin marker so ``governance_cache`` caches anchor
#: scores correctly across paper epochs (``case_origin_epoch`` reads it).
ANCHOR_STATIC_ORIGIN = "anchor_static"

#: The four-level ``accept_recommendation`` scale (academic_reviewer.md:7)
#: binarized to accept/reject. weak_accept papers ARE accepted (conference
#: semantics, §5.4).
_ACCEPT: frozenset[str] = frozenset({"strong_accept", "accept", "weak_accept"})
_REJECT: frozenset[str] = frozenset({"reject"})

#: ``label_source`` records WHO authored the ground truth (§5.2). A case with a
#: missing/unknown value is an integrity error (there is no default: unlabelled
#: provenance is exactly the state that lets a self-labelled corpus pass as
#: ground truth).
VALID_LABEL_SOURCES: frozenset[str] = frozenset(
    {"human_curated", "gate_bootstrap"}
)

#: The metric id frozen into the utility policy so a future binarization change
#: (e.g. a three-way scale) is a versioned, fingerprint-visible policy change.
AGREEMENT_METRIC_ID = "binary_accept_reject_v1"

#: The writer's faithfulness-anchor metric id (§5.1, revised 2026-07-16). The
#: writer IS anchored — to the deterministic claim-evidence hard gate the run
#: already computes for free — so its role can be OPENED by a real sanction and
#: its PROMPT co-evolves (the coding-domain shape: a deterministic verifier +
#: the co-evolving reviewer), NOT the RQGM paper's anchor-less writer.
WRITER_FAITHFULNESS_METRIC_ID = "claim_evidence_faithfulness_v1"

#: A draft whose faithfulness score is strictly below this bar (or that carries
#: any Layer-0 gate error finding) is UNFAITHFUL — the writer that produced it
#: is a culpable component for the over-accepted-AND-unfaithful draft (§5.1 /
#: docs/plans/ari_rqgm_paper/05 §5.4). A conservative bar: a faithful draft that
#: grounds every claim and reproduces every number scores 1.0.
WRITER_FAITHFULNESS_THRESHOLD = 0.75

#: The writer-anchor descriptor frozen into ``paper_utility_policy`` in place of
#: the interim ``writer_anchor: None``. It records WHAT the writer is anchored to
#: (the Layer-0 claim-evidence hard gate, read-only) and the three deterministic
#: gate rates it composes — so the paper epoch fingerprint reflects that the
#: writer is anchored, and a future metric change is a versioned, diffable policy
#: change. The gate is NEVER wrapped/evolved: RQGM only READS its findings.
WRITER_ANCHOR_DESCRIPTOR: dict = {
    "metric": WRITER_FAITHFULNESS_METRIC_ID,
    "source": "claim_evidence_hard_gate",   # Layer-0, deterministic, read-only
    "components": [
        "execution_grounded_claim_rate",
        "numeric_claim_reproducible_rate",
        "numeric_coverage_rate",
    ],
    "threshold": WRITER_FAITHFULNESS_THRESHOLD,
}


def writer_faithfulness_score(gate_report: "dict | None") -> float:
    """Deterministic faithfulness score ∈ [0,1] of a draft, folded from the
    Layer-0 claim-evidence hard gate's three rates (§5.1). Pure — reads only the
    gate report ``run_hard_gate(write=False)`` already returns; no LLM, no wall
    clock, no gate re-run.

    Only rates with a live denominator are averaged (a paper with no numeric
    claims is not penalised for a vacuous ``numeric_claim_reproducible_rate``);
    a draft with nothing to verify scores 1.0 (vacuously faithful). This is the
    writer's cross-epoch-comparable anchor — objective, independent of any
    evolving reviewer."""
    m = (gate_report or {}).get("metrics") or {}
    parts: list[float] = []
    if int(m.get("total_claims", 0) or 0) > 0:
        parts.append(float(m.get("execution_grounded_claim_rate", 0.0) or 0.0))
    if int(m.get("numeric_assertions_total", 0) or 0) > 0:
        parts.append(
            float(m.get("numeric_claim_reproducible_rate", 0.0) or 0.0)
        )
    if int(m.get("targeted_result_claims", 0) or 0) > 0:
        parts.append(float(m.get("numeric_coverage_rate", 1.0) or 0.0))
    if not parts:
        return 1.0
    return round(sum(parts) / len(parts), 6)


def draft_is_unfaithful(
    gate_report: "dict | None",
    *,
    threshold: float = WRITER_FAITHFULNESS_THRESHOLD,
) -> bool:
    """``True`` iff the draft is unfaithful per the Layer-0 gate: any error
    finding present OR the faithfulness score below *threshold* (§5.1). Pure —
    the writer-culpability signal is the writer's OWN drafts' claim-gate
    faithfulness, never the reviewer's leniency."""
    report = gate_report or {}
    if report.get("errors"):
        return True
    return writer_faithfulness_score(report) < float(threshold)


# ── the agreement metric (§5.4) ─────────────────────────────────────────────


def binarize_recommendation(rec: str) -> "str | None":
    """``strong_accept/accept/weak_accept -> accept``, ``reject -> reject``;
    an unparseable verdict -> ``None`` (a MISS, never silently agreement)."""
    r = (rec or "").strip().lower()
    if r in _ACCEPT:
        return "accept"
    if r in _REJECT:
        return "reject"
    return None


#: The REVIEWER's anchor-case view (§4 "one reference manuscript + no leakage
#: of its label"; §10 R4). Exactly the manuscript-side fields — everything that
#: identifies WHAT is under review, and nothing that reveals how it was
#: labelled. The whitelist is the enforcement: any field not named here (the
#: label itself, ``expected_behavior``'s binarized restatement of it,
#: ``label_source``, ``split``, ``results``, and ``authorship`` — an ai/human
#: tag correlates with the label in an AI-vs-human corpus) simply does not exist
#: in the dict the judge receives.
ANCHOR_CASE_VIEW_FIELDS: frozenset[str] = frozenset({
    "case_id", "venue", "manuscript_ref", "manuscript_sha256", "manuscript_text",
})


def anchor_case_view(case: dict) -> dict:
    """The leak-free projection of one anchor case for the reviewer's judgement
    (§4, §10 R4).

    Structural, not advisory: the reviewer's utility IS its agreement with the
    label (§5.1), so a judge that can read the label scores 1.0 by copying it
    and the entire anchor measures nothing. Handing the judge a dict that has no
    label FIELD makes that unreachable for every verdict source — the founding
    heuristic, an injected test double, and an LLM render alike — rather than
    asking each not to look. ``case[<label field>]`` raises ``KeyError``.

    Pure and deterministic (P2): a fixed key set, values copied by value."""
    return {k: (case or {}).get(k, "") for k in sorted(ANCHOR_CASE_VIEW_FIELDS)}


def _case_target_label(case: dict) -> str:
    exp = case.get("expected_behavior")
    if isinstance(exp, dict) and exp.get("accept_recommendation_binary"):
        return str(exp["accept_recommendation_binary"])
    return str(case.get("ground_truth_label", ""))


def paper_reviewer_agreement(candidate_verdict: dict, case: dict) -> bool:
    """``case_evaluator(candidate, case) -> bool`` for the ``anchor_evaluation``
    stage: did the reviewer candidate's accept/reject verdict on this reference
    manuscript match the anchor label? An unparseable verdict is a miss (never
    counted as agreement) — conservative, and it penalises reviewers that
    violate the output schema."""
    got = binarize_recommendation(
        str((candidate_verdict or {}).get("accept_recommendation", ""))
    )
    want = _case_target_label(case)
    return got is not None and got == want


# ── corpus schema + digest (§5.2) ───────────────────────────────────────────


@dataclass(frozen=True)
class PaperAnchorCase:
    """One ``paper_anchor_corpus.jsonl`` line (§5.2). Frozen field set; the
    read-only anchor is never authored/mutated by a governed role."""

    case_id: str
    ground_truth_label: str        # accept | reject
    label_source: str              # human_curated | gate_bootstrap
    manuscript_sha256: str = ""
    manuscript_ref: str = ""
    manuscript_text: str = ""
    venue: str = ""
    authorship: str = ""           # human | ai (plan 05's shared dimension)
    split: str = ""                # train | held_out (assigned at load)
    origin_epoch_id: str = ANCHOR_STATIC_ORIGIN
    expected_behavior: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    record_type: str = PAPER_ANCHOR_CASE_RECORD_TYPE

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "record_type": self.record_type,
            "venue": self.venue,
            "manuscript_ref": self.manuscript_ref,
            "manuscript_sha256": self.manuscript_sha256,
            "manuscript_text": self.manuscript_text,
            "ground_truth_label": self.ground_truth_label,
            "label_source": self.label_source,
            "authorship": self.authorship,
            "split": self.split,
            "origin_epoch_id": self.origin_epoch_id,
            "expected_behavior": dict(self.expected_behavior),
            "results": dict(self.results),
        }


def corpus_digest(cases: list[dict]) -> str:
    """``hash12`` over the sorted ``(case_id, manuscript_sha256)`` pairs
    (§5.5). Content-only, deterministic, no wall clock (P2)."""
    pairs = sorted(
        (str(c.get("case_id", "")), str(c.get("manuscript_sha256", "")))
        for c in cases
    )
    return hash12(canonical_json(pairs))


def _is_self_label(case: dict) -> bool:
    """The acute self-labelling loop (§5.3): an ARI-authored draft that ARI's
    own gate passed and ARI then labelled ``accept``. Pure — labels only."""
    return (
        str(case.get("label_source", "")) == "gate_bootstrap"
        and str(case.get("ground_truth_label", "")) == "accept"
        and str(case.get("authorship", "")) == "ai"
    )


# ── deterministic held-out split (§5.3) ─────────────────────────────────────


def _count_held(cases: list[dict]) -> int:
    return sum(1 for c in cases if c.get("split") == "held_out")


def assign_split(
    cases: list[dict], *, sample_size: int, corpus_digest: str
) -> list[dict]:
    """Deterministically mark ``sample_size`` cases as ``held_out`` (the rest
    ``train``).

    Pure (P2): the choice is a hash of ``(case_id, corpus_digest)`` — no wall
    clock, no RNG, no epoch input (epoch-independent so the held-out set is
    stable across the whole run). Cases with a pre-pinned ``split`` are honored
    as-is; a case pinned ``train`` (e.g. an accept+ai self-label, §5.3) can
    never be selected into ``held_out``."""
    pinned = [c for c in cases if c.get("split") in ("train", "held_out")]
    pinned_ids = {id(c) for c in pinned}
    free = [c for c in cases if id(c) not in pinned_ids]
    ranked = sorted(
        free, key=lambda c: hash12(f"{c.get('case_id', '')}:{corpus_digest}")
    )
    remaining = max(0, int(sample_size) - _count_held(pinned))
    held = {str(c.get("case_id", "")) for c in ranked[:remaining]}
    out: list[dict] = []
    for c in cases:
        if c.get("split") in ("train", "held_out"):
            out.append(dict(c))
            continue
        split = "held_out" if str(c.get("case_id", "")) in held else "train"
        out.append({**c, "split": split})
    return out


# ── the pool adapter (§7) ───────────────────────────────────────────────────


class PaperAnchorPool:
    """Pool-shaped adapter (§7) exposing ``.anchor_cases`` (the held-out cases)
    and an empty ``.cases``, so ``anchor_cases(pool)`` / ``board_score`` and
    ``CandidateValidationPipeline(anchor_cases=...)`` consume it unchanged.

    Carries the ``corpus_digest`` / ``held_out_ids`` and the two label-source
    mixes so :func:`capture_paper_utility_policy` can freeze them."""

    def __init__(
        self,
        held_out_cases: list[dict],
        *,
        corpus_digest: str,
        label_source_mix: dict,
        held_out_label_source_mix: dict,
    ) -> None:
        self.anchor_cases = list(held_out_cases)
        self.cases = []
        self.corpus_digest = str(corpus_digest)
        self.held_out_ids = sorted(
            str(c.get("case_id", "")) for c in held_out_cases
        )
        self.label_source_mix = dict(label_source_mix)
        self.held_out_label_source_mix = dict(held_out_label_source_mix)

    def record_writer_faithfulness(
        self, *, prompt_hash: str, score: float, epoch_id: str = ""
    ) -> "dict | None":
        """Land the ACTIVE writer's Layer-0 gate faithfulness on the anchor
        board as its OWN case (§5.1, revised 2026-07-16) — the step that makes
        the writer's anchor OPERATIVE rather than merely computed.

        Without this the writer's faithfulness was scored and thrown away:
        ``adjudicate_motion``'s ``board_score(anchor_cases(pool), writer keys)``
        found no case carrying a writer key, so ``incumbent_board`` was ``None``,
        ``_bounded_outcome`` could not clamp, and every writer impeachment motion
        was dismissed "in favor of the incumbent" — the writer's role never
        opened and its waiting shadow successor never adopted.

        Keyed on the writer's ``prompt_hash`` ALONE, never its ``component_id``:
        one component id spans successive prompt versions (an adoption rewrites
        the prompt, not the component), so a component-keyed score would leak
        the incumbent's faithfulness onto its successor and make the fresh
        writer instantly impeachable. Hash-keying is the same "anchor evidence
        never leaks across versions" rule ``replay_lookup_key`` applies to the
        reviewer (P-D: erase, don't re-scale).

        One case per ``(epoch_id, prompt_hash)``: re-recording within an epoch
        UPDATES in place (idempotent, resume-safe), so ``board_score`` averages
        one honest observation per epoch the writer was active. Pure + P2: no
        wall clock, no LLM, no gate re-run — the score is already computed.
        Never raises (the anchor is a trust signal, never a crash source)."""
        try:
            phash = str(prompt_hash or "")
            if not phash:
                return None
            case_id = f"writer_faithfulness_{epoch_id}_{phash}"
            for case in self.anchor_cases:
                if str(case.get("case_id", "")) == case_id:
                    case.setdefault("results", {})[phash] = float(score)
                    return case
            case = {
                "case_id": case_id,
                "record_type": WRITER_FAITHFULNESS_CASE_RECORD_TYPE,
                "metric": WRITER_FAITHFULNESS_METRIC_ID,
                "origin_epoch_id": str(epoch_id),
                # The board reads `results` subject-keyed; the writer's own
                # prompt_hash is the only key, so no other subject can ever
                # read this case (and the reviewer's board is untouched).
                "results": {phash: float(score)},
            }
            self.anchor_cases.append(case)
            return case
        except Exception:      # pragma: no cover - defensive (never raises)
            log.warning("writer faithfulness board record failed", exc_info=True)
            return None

    def save_snapshot(self, *args, **kwargs) -> None:  # pool-shape parity
        """The anchor corpus is read-only (``anchor_static``); there is no
        snapshot to write. Present so the pool shape matches the replay pool."""
        return None


def reviewer_anchor_cases(pool) -> list[dict]:
    """The REVIEWER's held-out reference-manuscript cases off a pool.

    The pool's ``anchor_cases`` carries two anchor sources since §5.1 (revised
    2026-07-16): the human-labelled corpus (the reviewer's ground truth) and
    the writer's claim-gate faithfulness cases. ``board_score`` separates them
    by subject key on its own, but the REVIEWER-side consumers (anchor scoring,
    the over-acceptance pre-signal, the candidate evaluator) iterate the cases
    directly and must never score the reviewer against a writer case — a case
    with no ``ground_truth_label`` would count as a miss and dilute the
    reviewer's agreement with evidence that is not its anchor. Filters IN the
    corpus cases (not OUT the writer's) so any future third source is excluded
    by default."""
    out: list[dict] = []
    for case in list(getattr(pool, "anchor_cases", None) or ()):
        if not isinstance(case, dict):
            continue
        if str(case.get("record_type", PAPER_ANCHOR_CASE_RECORD_TYPE)) == (
            PAPER_ANCHOR_CASE_RECORD_TYPE
        ):
            out.append(case)
    return out


def _label_source_mix(cases: list[dict]) -> dict:
    mix = {"human_curated": 0, "gate_bootstrap": 0}
    for c in cases:
        src = str(c.get("label_source", ""))
        if src in mix:
            mix[src] += 1
    return mix


def _bootstrap_fraction(mix: dict) -> float:
    total = int(mix.get("human_curated", 0)) + int(mix.get("gate_bootstrap", 0))
    if total <= 0:
        return 0.0
    return int(mix.get("gate_bootstrap", 0)) / total


def _resolve_corpus_path(corpus_path: str, checkpoint_dir) -> "Path | None":
    if not corpus_path:
        return None
    p = Path(corpus_path)
    if not p.is_absolute() and checkpoint_dir is not None:
        p = Path(checkpoint_dir) / corpus_path
    return p


def load_anchor_corpus(cfg, checkpoint_dir=None) -> "PaperAnchorPool | None":
    """Load + validate the anchor corpus, or ``None`` for the §5.9 on-ramp.

    Absence-tolerant AND integrity-strict, but it NEVER raises into the run
    (§7). Returns ``None`` — the degraded on-ramp (reviewer not anchor-gated) —
    when: ``anchor.enabled`` is false; the corpus is missing/empty; every case
    is dropped for a missing/unknown ``label_source``; an ``eval_*`` case
    leaks into the ``anchor_*`` namespace; OR the ``gate_bootstrap`` fraction
    EXCEEDS ``max_bootstrap_label_fraction`` over the corpus OR the held-out
    subset (§5.3). Refusing to anchor is strictly safer than anchoring on
    self-labels: the on-ramp merely withholds a trust signal.

    Also returns (on the pool) the corpus digest, held-out ids, and the two
    label-source mixes for :func:`capture_paper_utility_policy` (§5.5).
    """
    try:
        anchor = _anchor_cfg(cfg)
        if not bool(getattr(anchor, "enabled", False)):
            return None
        path = _resolve_corpus_path(
            str(getattr(anchor, "corpus_path", "") or ""), checkpoint_dir
        )
        if path is None or not path.exists():
            log.info("paper anchor corpus absent (%s); on-ramp (no anchor gate)",
                     path)
            return None
        raw = _read_jsonl(path)
        if not raw:
            log.info("paper anchor corpus empty; on-ramp (no anchor gate)")
            return None

        # label_source is REQUIRED (§5.2): drop cases without a valid one.
        cases: list[dict] = []
        dropped = 0
        for c in raw:
            if str(c.get("label_source", "")) in VALID_LABEL_SOURCES:
                cases.append(c)
            else:
                dropped += 1
        if dropped:
            log.warning(
                "paper anchor: dropped %d case(s) with missing/unknown "
                "label_source (§5.2 required field)", dropped,
            )
        if not cases:
            log.warning("paper anchor: no case has a valid label_source; "
                        "on-ramp (no anchor gate)")
            return None

        # No-leakage guard (§5.3): the anchor namespace must be disjoint from
        # Task 13's eval_* injection set.
        if any(str(c.get("case_id", "")).startswith("eval_") for c in cases):
            log.warning("paper anchor: eval_* case in the anchor namespace; "
                        "on-ramp (no anchor gate)")
            return None

        cases = sorted(cases, key=lambda c: str(c.get("case_id", "")))
        digest = corpus_digest(cases)

        # Self-label self-certification loop (§5.3): accept+ai+gate_bootstrap
        # cases are barred from held_out (pin train) AND counted against the
        # corpus cap. Pure — labels only.
        prepared: list[dict] = []
        for c in cases:
            c2 = dict(c)
            if _is_self_label(c2) and c2.get("split") != "held_out":
                c2["split"] = "train"
            prepared.append(c2)

        sample_size = int(getattr(anchor, "sample_size", 8))
        split_cases = assign_split(
            prepared, sample_size=sample_size, corpus_digest=digest
        )
        held_out = [c for c in split_cases if c.get("split") == "held_out"]

        corpus_mix = _label_source_mix(split_cases)
        held_mix = _label_source_mix(held_out)
        cap = float(getattr(anchor, "max_bootstrap_label_fraction", 0.5))
        corpus_frac = _bootstrap_fraction(corpus_mix)
        held_frac = _bootstrap_fraction(held_mix)
        # Strict-exceed test (§5.3): exactly-at-cap loads.
        if corpus_frac > cap or held_frac > cap:
            log.warning(
                "paper anchor: gate_bootstrap fraction exceeds cap %.3f "
                "(corpus=%.3f, held_out=%.3f); corpus REFUSED => on-ramp (no "
                "anchor gate), not a self-certifying anchor", cap, corpus_frac,
                held_frac,
            )
            return None

        return PaperAnchorPool(
            held_out,
            corpus_digest=digest,
            label_source_mix=corpus_mix,
            held_out_label_source_mix=held_mix,
        )
    except Exception:
        # Absolute never-raises contract (§7): any integrity failure degrades
        # to "no anchor gate", never a crash into the paper phase.
        log.warning("paper anchor load failed (fail-open => on-ramp)",
                    exc_info=True)
        return None


def _anchor_cfg(cfg):
    return getattr(
        getattr(getattr(cfg, "rqgm", None), "paper", None), "anchor", None
    )


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# ── utility-policy freeze (§5.5) ────────────────────────────────────────────


def capture_paper_utility_policy(
    cfg,
    *,
    corpus_digest: str,
    held_out_ids: list[str],
    label_source_mix: dict,
    held_out_label_source_mix: dict,
) -> dict:
    """The paper-phase ``paper_utility_policy`` (§5.5), mirroring
    ``state.capture_utility_policy``: content-only, ``canonical_json`` +
    ``hash12`` (P2, no wall clock). Frozen into the paper epoch fingerprint.

    The writer IS anchored (``writer_anchor`` = the claim-evidence faithfulness
    descriptor, §5.1 revised 2026-07-16): ARI writes about REAL experiments, so
    the Layer-0 hard gate scores a draft's faithfulness deterministically and
    the writer's role can be OPENED by a real sanction — its PROMPT co-evolves
    (the coding-domain shape), it no longer only improves via epoch-local draft
    selection. Both label-source mixes ride the hash (§5.5): the fingerprint
    MOVES when the ground truth becomes more self-labelled, so a drift toward
    "ARI grading its own homework" cannot happen without a visible, diffable
    epoch-identity change. This doc invents NO utility machinery — the payload's
    cross-epoch rewrite is parent Task 14's; the gate stays Layer-0 (read-only)."""
    a = _anchor_cfg(cfg)
    policy = {
        "reviewer_score_source": "paper_reviewer",   # who provides draft utility
        # The writer's cross-epoch anchor: the deterministic claim-evidence gate
        # (§5.1). No longer None — the writer co-evolves via a real sanction.
        "writer_anchor": dict(WRITER_ANCHOR_DESCRIPTOR),
        "anchor_enabled": bool(getattr(a, "enabled", False)),
        "anchor_corpus_digest": str(corpus_digest),
        "anchor_sample_size": int(getattr(a, "sample_size", 8)),
        "anchor_held_out_ids": sorted(str(i) for i in held_out_ids),
        "anchor_label_source_mix": {
            k: int((label_source_mix or {}).get(k, 0))
            for k in ("human_curated", "gate_bootstrap")
        },
        "anchor_held_out_label_source_mix": {
            k: int((held_out_label_source_mix or {}).get(k, 0))
            for k in ("human_curated", "gate_bootstrap")
        },
        "anchor_max_bootstrap_label_fraction": float(
            getattr(a, "max_bootstrap_label_fraction", 0.5)
        ),
        "agreement_metric": AGREEMENT_METRIC_ID,
        "ties_favor_incumbent": True,
    }
    policy["paper_utility_policy_hash"] = hash12(canonical_json(policy))
    return policy


# ── held-out scoring helper (used by the paper boundary, §5.4) ──────────────


def score_reviewer_on_anchor(pool, verdict_fn) -> "tuple[float | None, list]":
    """Held-out accept/reject accuracy of a reviewer over ``pool.anchor_cases``.

    *verdict_fn* maps an anchor case dict -> the reviewer's raw
    ``accept_recommendation`` string, or ``None`` meaning NO VERDICT SOURCE.
    Agreement is the §5.4 binary metric.

    Returns ``(accuracy | None, sorted_case_refs)`` — ``None`` when there are
    zero held-out cases OR no case could be judged (the on-ramp's zero-coverage
    pass). A ``None`` verdict is an ABSENCE and the case is skipped: it is never
    scored, because ``binarize_recommendation(str(None))`` is a MISS and would
    turn "no verdict source wired" into a 0.0 anchor board — impeaching a
    reviewer on evidence nobody produced. Accuracy is over the cases actually
    JUDGED, and ``case_refs`` cites only those.

    Deterministic (the cases are already sorted by ``case_id``). Reads the
    REVIEWER's corpus cases only (:func:`reviewer_anchor_cases`) — the pool's
    writer faithfulness cases are a different subject's anchor and never score
    the reviewer."""
    cases = reviewer_anchor_cases(pool)
    if not cases:
        return None, []
    hits = 0
    refs: list[str] = []
    for case in sorted(cases, key=lambda c: str(c.get("case_id", ""))):
        rec = verdict_fn(case)
        if rec is None:
            continue                    # no verdict source -> abstain
        if paper_reviewer_agreement({"accept_recommendation": rec}, case):
            hits += 1
        refs.append(str(case.get("case_id", "")))
    if not refs:
        return None, []
    return round(hits / len(refs), 6), refs
