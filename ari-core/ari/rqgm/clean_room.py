"""Clean-room regeneration of retired-role prompts (RQGM Task 08).

When a prompt is impeached and retired (Task 09), ARI-RQGM never patches the
retired prompt: a successor for the same role is generated FROM SCRATCH out
of abstract inputs only (``docs/concepts/rqgm_architecture.md``, "Key
invariants" — clean-room contamination rules). This module
implements the whole sanctioned path:

* :class:`CleanRoomGenerationRequest` / :class:`CleanRoomInputBundle` —
  the §6.1/§6.2 record shapes (JSON schemas beside
  ``ari/schemas/node_report.schema.json``);
* :class:`CleanRoomInputBundleAssembler` — deterministic, fixed tier, the
  ONLY writer of bundles: reads committed catalogs and abstract summaries,
  never registries' prompt text (Layer A, constructive containment);
* :class:`CleanRoomPromptGenerator` — meta tier, ONE injectable LLM
  completion over the committed ``rqgm/clean_room_generator.md`` meta-prompt
  plus the canonical bundle serialization. No tool loop, no filesystem, no
  MCP (§5.4 D1/D2: a ReAct rollout could read checkpoint files; MCP retries
  re-execute non-idempotent generation). Emits candidates only — it cannot
  activate them (invariant 15);
* :class:`RetiredPromptAccessGuard` — Layer B: the sanctioned read path for
  retired prompt text. Every non-exempt actor is denied via the kernel's
  ``validate_capability`` (CK-ACC-002) and the violation is appended to the
  Task 02 audit log. Only the kernel's own contamination checker and the
  human-facing audit CLI are exempt (the documented kernel-reader
  exemption — fixed tier, deterministic, only booleans/hashes flow onward);
* the ``{ckpt}/rqgm_cleanroom.jsonl`` append-only event log (fail-open
  writer, the ``prompt_evolution.jsonl`` posture);
* :class:`CleanRoomCoordinator` — the epoch-boundary processor invoked
  after ``RegistryTransitionEngine.apply`` commits: budget-capped by
  ``rqgm.prompt_evolution.max_clean_room_generations_per_epoch``, pre/post
  kernel screens (Layer C, blocking at admission, fail-open for the run),
  Task 07 lifecycle handoff at ``status: candidate``, and the §5.6
  no-vacancy baseline fallback.

Honest limitation (§5.3): any process holding ``ARI_CHECKPOINT_DIR`` can
read checkpoint files directly; Layers A and C make the *sanctioned* path
structurally clean and contamination detectable/blocking before a candidate
can be evaluated or activated.

Never imported under ``simple_bfts`` (``build_runtime`` conditional);
VirSci-independent. Only the generator's single injected LLM call is
non-deterministic; every decision around it is P2-pure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import string
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from ari.rqgm import clean_room_rules as rules
from ari.rqgm.events import (
    EVOLVABLE_ROLES,
    canonical_json,
    format_prompt_id,
    hash12,
    payload_hash,
)
from ari.rqgm.prompt_loader import (
    _resolve_checkpoint_dir,
    write_evolved_prompt_body,
)
from ari.rqgm.prompt_records import (
    PromptCandidate,
    format_candidate_record_id,
    load_prompt_evolution_log,
    record_prompt_evolution_event,
)
from ari.rqgm.prompt_spec import (
    FOUNDING_PROMPT_TABLE,
    REQUIRED_CONSTRAINTS_BY_ROLE,
    PromptSpec,
)

log = logging.getLogger(__name__)

CLEANROOM_FILENAME = "rqgm_cleanroom.jsonl"

#: Read-only §5.5 forbidden-corpus sources. Filename literals (the same
#: frozen names ari/paths.py registers) because the write-surface audit
#: test pins this module free of the ari.rqgm store/registry import
#: surface — reading these logs must not drag in any registry writer.
_AUDIT_FILENAME = "rqgm_audit.jsonl"
_ADVERSARIAL_CASES_FILENAME = "rqgm_adversarial_cases.jsonl"

#: Retired-side statuses whose prompt text forms the forbidden corpus.
_RETIRED_STATUSES: tuple[str, ...] = ("retired", "banned")

#: Layer-B exempt readers (plan 08 §5.3): the kernel's own contamination
#: checker and the human-facing audit CLI — both fixed tier. Everyone else
#: is denied at the sanctioned path.
EXEMPT_RETIRED_READERS: frozenset = frozenset({
    ("constitutional_kernel", "fixed"),
    ("audit_cli", "fixed"),
})

#: Committed role-spec catalog (plan 08 §5.2 allowed input 1): what each
#: evolvable role must DO, written from the role contract — never derived
#: from any retired prompt text.
ROLE_SPECS: dict[str, str] = {
    "generator": (
        "Propose concrete next research steps for the current experiment "
        "tree node, grounded in the recorded evidence and the run goal."
    ),
    "reviewer": (
        "Review a research artifact against its recorded evidence: detect "
        "unsupported claims, cite evidence refs, separate major from minor "
        "issues, and calibrate confidence."
    ),
    "adversary": (
        "Construct falsifiable challenges against research artifacts "
        "(never against components), each anchored to checkpoint evidence."
    ),
    "defender": (
        "Answer a challenge against an artifact strictly from the recorded "
        "evidence, conceding points the evidence cannot support."
    ),
    "judge": (
        "Adjudicate between a challenge and its defense using only the "
        "presented evidence, issuing a verdict with severity."
    ),
    "router": (
        "Select the next node or proposal to expand from bounded summaries, "
        "returning exactly the requested selection format."
    ),
    "prompt_mutator": (
        "Produce one candidate prompt template for a role from its "
        "incumbent and abstract failure summaries; candidates only."
    ),
    "clean_room_generator": (
        "Produce one successor prompt template for a retired role from "
        "abstract inputs only; candidates only."
    ),
    "replay_selector": (
        "Select regression replay cases for candidate evaluation from "
        "bounded case metadata."
    ),
    # plan 11 §5.2 item 4. The role was in the vocabulary and the capability
    # matrix but had no spec here, so ``assemble_filtered_inputs`` handed its
    # invoker an empty ``role_spec`` — a meta agent told nothing about its own
    # job. The wording mirrors the sibling specs: what it MAY produce, from
    # WHICH inputs, and the non-binding qualifier that is its whole contract.
    "failure_summary_compressor": (
        "Compress validated failure evidence into abstract failure summaries "
        "from bounded case metadata; summaries only, never raw evidence."
    ),
}

_VERSION_RE = re.compile(r"_v(\d+)$")


def role_output_schema(role: str) -> dict:
    """The role's output-schema contract from the committed founding table
    (plan 07 §6; the role's PRIMARY template row wins — last in table
    order). A committed catalog read, never a retired-prompt read."""
    out: dict = {}
    for _, _, table_role, _, schema in FOUNDING_PROMPT_TABLE:
        if table_role == role:
            out = dict(schema)
    return out


# ── CleanRoomGenerationRequest (plan 08 §6.1) ───────────────────────────────


def default_allowed_inputs() -> dict:
    """The §6.1 flag block: six allowed trues + five const-false forbidden."""
    flags = {key: True for key in rules.ALLOWED_INPUT_KEYS}
    flags.update({key: False for key in rules.FORBIDDEN_INPUT_KEYS})
    return flags


@dataclass(frozen=True)
class CleanRoomGenerationRequest:
    """One clean-room regeneration request (envelope + §6.1 fields).

    Produced from Task 09's ``EpochTransition.clean_room_requests`` entries;
    persisted to ``rqgm_cleanroom.jsonl`` so pending requests survive resume
    (BFTS in-memory state is never relied on).
    """

    record_id: str
    epoch_id: str = ""
    component_id: str = "registry_transition_engine"
    prompt_hash: str | None = None
    role: str = ""
    created_at: str = ""
    source_refs: tuple[str, ...] = ()
    status: str = "pending"
    trigger: str = "retirement_event"
    retirement_event_id: str = ""
    target_role: str = ""
    allowed_inputs: dict = field(default_factory=default_allowed_inputs)
    requirements: tuple[str, ...] = ()
    replay_case_ids: tuple[str, ...] = ()
    budget_policy: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "record_type": rules.REQUEST_RECORD_TYPE,
            "record_id": self.record_id,
            "epoch_id": self.epoch_id,
            "component_id": self.component_id,
            "prompt_hash": self.prompt_hash,
            "role": self.role,
            "created_at": self.created_at,
            "source_refs": list(self.source_refs),
            "status": self.status,
            "trigger": self.trigger,
            "retirement_event_id": self.retirement_event_id,
            "target_role": self.target_role,
            "allowed_inputs": dict(self.allowed_inputs),
            "requirements": list(self.requirements),
            "replay_case_ids": list(self.replay_case_ids),
            "budget_policy": dict(self.budget_policy),
        }


def request_from_dict(d: dict) -> CleanRoomGenerationRequest:
    return CleanRoomGenerationRequest(
        record_id=str(d.get("record_id", "")),
        epoch_id=str(d.get("epoch_id", "")),
        component_id=str(
            d.get("component_id", "registry_transition_engine")
        ),
        prompt_hash=d.get("prompt_hash"),
        role=str(d.get("role", "")),
        created_at=str(d.get("created_at", "")),
        source_refs=tuple(d.get("source_refs") or ()),
        status=str(d.get("status", "pending")),
        trigger=str(d.get("trigger", "retirement_event")),
        retirement_event_id=str(d.get("retirement_event_id", "")),
        target_role=str(d.get("target_role", "")),
        allowed_inputs=dict(d.get("allowed_inputs") or default_allowed_inputs()),
        requirements=tuple(d.get("requirements") or ()),
        replay_case_ids=tuple(d.get("replay_case_ids") or ()),
        budget_policy=dict(d.get("budget_policy") or {}),
    )


def request_from_transition_entry(
    entry: dict,
    *,
    epoch_id: str,
    transition_id: str = "",
    requirements=(),
    replay_case_ids=(),
    budget_policy: dict | None = None,
) -> CleanRoomGenerationRequest:
    """Materialize the full §6.1 record from one Task 09
    ``clean_room_requests`` entry (``request_id`` / ``target_role`` /
    ``retirement_event_id``)."""
    role = str(entry.get("target_role", ""))
    refs = [
        str(r)
        for r in (entry.get("retirement_event_id"), transition_id)
        if r
    ]
    return CleanRoomGenerationRequest(
        record_id=str(entry.get("request_id", "")),
        epoch_id=str(epoch_id),
        role=role,
        source_refs=tuple(refs),
        status="pending",
        retirement_event_id=str(entry.get("retirement_event_id", "")),
        target_role=role,
        requirements=tuple(requirements),
        replay_case_ids=tuple(replay_case_ids),
        budget_policy=dict(
            budget_policy or {"max_tokens": 4000, "max_attempts": 1}
        ),
    )


def request_schema_failures(request) -> list[str]:
    """Deterministic mirror of ``clean_room_request.schema.json`` (empty
    list == valid). The kernel blocks a failing request before assembly."""
    d = request.to_dict() if hasattr(request, "to_dict") else dict(request)
    out: list[str] = []
    for name in (
        "record_id", "epoch_id", "component_id", "prompt_hash", "role",
        "created_at", "source_refs", "status",
    ):
        if name not in d:
            out.append(f"missing envelope field {name!r}")
    for name in ("record_id", "target_role", "retirement_event_id"):
        if not str(d.get(name) or ""):
            out.append(f"field {name!r} is empty")
    rtype = d.get("record_type", rules.REQUEST_RECORD_TYPE)
    if rtype != rules.REQUEST_RECORD_TYPE:
        out.append(f"record_type {rtype!r} is not {rules.REQUEST_RECORD_TYPE!r}")
    if str(d.get("status", "")) not in rules.REQUEST_STATUSES:
        out.append(f"status {d.get('status')!r} is outside the closed enum")
    if str(d.get("trigger", "")) not in rules.REQUEST_TRIGGERS:
        out.append(f"trigger {d.get('trigger')!r} is outside the closed enum")
    if d.get("target_role") and str(d.get("target_role")) not in EVOLVABLE_ROLES:
        out.append(
            f"target_role {d.get('target_role')!r} is not an evolvable role"
        )
    flags = d.get("allowed_inputs")
    if not isinstance(flags, dict):
        out.append("allowed_inputs is missing or not an object")
    else:
        for key in rules.FORBIDDEN_INPUT_KEYS:
            if flags.get(key, None) is not False:
                out.append(
                    f"allowed_inputs[{key!r}] must be const-false"
                )
        for key in rules.ALLOWED_INPUT_KEYS:
            if key not in flags:
                out.append(f"allowed_inputs[{key!r}] is missing")
        for key in sorted(
            set(flags)
            - set(rules.ALLOWED_INPUT_KEYS)
            - set(rules.FORBIDDEN_INPUT_KEYS)
        ):
            out.append(f"allowed_inputs[{key!r}] is not a known input flag")
    if not isinstance(d.get("budget_policy"), dict):
        out.append("budget_policy is missing or not an object")
    return out


# ── CleanRoomInputBundle (plan 08 §6.2) ─────────────────────────────────────


@dataclass(frozen=True)
class CleanRoomInputBundle:
    """The materialized, CLOSED input set handed to the generator.

    ``bundle_hash`` covers the canonical serialization (sorted keys, no
    timestamps) of every field except itself, so the exact input surface is
    auditable after the fact (Layer A provenance)."""

    bundle_id: str
    request_id: str
    role_spec: str
    output_schema: dict = field(default_factory=dict)
    constitutional_constraints: tuple[str, ...] = ()
    abstract_failure_summary: dict = field(default_factory=dict)
    replay_requirements: tuple[str, ...] = ()
    cost_budget: dict = field(default_factory=dict)
    bundle_hash: str = ""

    def payload_dict(self) -> dict:
        """The hashed payload (everything but ``bundle_hash``)."""
        return {
            "bundle_id": self.bundle_id,
            "request_id": self.request_id,
            "role_spec": self.role_spec,
            "output_schema": dict(self.output_schema),
            "constitutional_constraints": list(self.constitutional_constraints),
            "abstract_failure_summary": dict(self.abstract_failure_summary),
            "replay_requirements": list(self.replay_requirements),
            "cost_budget": dict(self.cost_budget),
        }

    def to_dict(self) -> dict:
        out = self.payload_dict()
        out["bundle_hash"] = self.bundle_hash
        return out


def compute_bundle_hash(bundle: CleanRoomInputBundle) -> str:
    """``hash12(canonical_json(payload))`` — the single RQGM hash scheme,
    no wall clock (P2)."""
    return payload_hash(bundle.payload_dict())


def fold_failure_summaries(summaries, extra_source_refs=()) -> dict:
    """Deterministic fold of abstract failure views into the §6.3 shape.

    Accepts Task 06 ``abstract_view`` dicts (``case_type`` /
    ``violated_expectation``) and Task 11-shaped summaries
    (``failure_classes`` / ``behavioral_requirements``). Categorical classes,
    counts, and short imperative strings only — ids, never quoted text.
    """
    classes: list[str] = []
    behavioral: set[str] = set()
    refs: set[str] = {str(r) for r in extra_source_refs or () if r}
    for summary in summaries or ():
        if not isinstance(summary, dict):
            continue
        if summary.get("failure_classes") is not None:
            classes.extend(str(c) for c in summary.get("failure_classes") or ())
            behavioral.update(
                str(b) for b in summary.get("behavioral_requirements") or ()
            )
        else:
            case_type = str(summary.get("case_type", ""))
            if case_type:
                classes.append(case_type)
            expectation = str(summary.get("violated_expectation", ""))
            if expectation:
                behavioral.add(expectation)
        refs.update(str(r) for r in summary.get("source_refs") or () if r)
    counts: dict[str, int] = {}
    for cls in classes:
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "failure_classes": sorted(set(classes)),
        "class_counts": {c: counts[c] for c in sorted(counts)},
        "severity_histogram": {},
        "behavioral_requirements": sorted(behavioral),
        "source_refs": sorted(refs),
        "contamination_screen": {
            "passed": True,
            "screen_version": rules.SCREEN_VERSION,
        },
    }


class CleanRoomInputBundleAssembler:
    """Deterministic, fixed tier — the ONLY writer of bundles (plan 08 §7).

    Assembly reads exclusively the committed catalogs (role specs, founding
    output schemas, constitutional constraints) and the abstract failure
    summaries handed in; it NEVER dereferences prompt text through the
    registries, which are accepted only for interface parity with the plan
    and future guards. That is what makes Layer A constructive: forbidden
    material cannot enter a bundle unless this assembler itself is broken —
    which the kernel's detective screen (Layer C) blocks at admission.
    """

    def __init__(self, *, role_specs: dict | None = None) -> None:
        self._role_specs = dict(role_specs or ROLE_SPECS)

    def assemble(
        self,
        request: CleanRoomGenerationRequest,
        *,
        prompt_registry=None,
        component_registry=None,
        failure_summaries=(),
    ) -> CleanRoomInputBundle:
        role = request.target_role
        summary = fold_failure_summaries(
            failure_summaries,
            extra_source_refs=list(request.replay_case_ids),
        )
        replay_requirements = sorted(
            set(request.requirements)
            | set(summary.get("behavioral_requirements") or ())
        )
        suffix = request.record_id
        if suffix.startswith("cleanroom_req_"):
            suffix = suffix[len("cleanroom_req_"):]
        bundle = CleanRoomInputBundle(
            bundle_id=f"cleanroom_bundle_{suffix}",
            request_id=request.record_id,
            role_spec=str(self._role_specs.get(role, "")),
            output_schema=role_output_schema(role),
            constitutional_constraints=tuple(
                REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
            ),
            abstract_failure_summary=summary,
            replay_requirements=tuple(replay_requirements),
            cost_budget={
                "max_tokens": int(
                    (request.budget_policy or {}).get("max_tokens", 4000)
                ),
            },
        )
        return replace(bundle, bundle_hash=compute_bundle_hash(bundle))


def bundle_allowlist_corpus(bundle: CleanRoomInputBundle) -> list[str]:
    """The §5.5 allowlist corpus: the allowed inputs themselves — text the
    candidate legitimately shares with them must never trigger a hit."""
    docs = [bundle.role_spec]
    docs.extend(bundle.constitutional_constraints)
    docs.extend(bundle.replay_requirements)
    docs.extend(
        str(b)
        for b in bundle.abstract_failure_summary.get(
            "behavioral_requirements"
        ) or ()
    )
    docs.append(" ".join(sorted(str(k) for k in bundle.output_schema)))
    return [d for d in docs if d]


# ── CleanRoomPromptGenerator (plan 08 §5.3 Layer A / §7) ────────────────────


class CleanRoomPromptGenerator:
    """Meta tier; emits :class:`~ari.rqgm.prompt_records.PromptCandidate`
    records ONLY — no registry write surface, no activation surface (pinned
    by the write-surface audit test, the PromptMutator discipline).

    The harness is a SINGLE completion (D1): context = the committed
    meta-prompt + the canonical bundle serialization, nothing else. The
    template-producing LLM is injectable in either shape: the runtime's
    ``LLMClient`` (``.complete(messages, ...)`` — the ``build_runtime``
    injection, cost-tagged ``phase="governance", skill="clean_room"``) or a
    bare ``prompt -> str`` callable (tests use deterministic fakes; never a
    real LLM in tests). The rendered context is provenance-logged via
    ``record_prompt_use`` with ``phase="governance"``.
    """

    ROLE = "clean_room_generator"
    META_PROMPT_KEY = "rqgm/clean_room_generator"

    def __init__(
        self,
        component_id: str = "clean_room_generator_v1",
        *,
        llm=None,
        loader=None,
        checkpoint_dir=None,
    ) -> None:
        self.component_id = component_id
        self._llm = llm
        self._loader = loader
        self._checkpoint_dir = checkpoint_dir

    def _meta_prompt(self) -> tuple[str, str]:
        loader = self._loader
        if loader is None:
            from ari.prompts import FilesystemPromptLoader

            loader = FilesystemPromptLoader()
        # Literal key (== META_PROMPT_KEY) so the reference analyzer's
        # dynamic overlay sees the template edge (scripts/analyze_references).
        return loader.load_versioned("rqgm/clean_room_generator")

    def _complete(self, prompt: str) -> str:
        """The one completion, over either injectable LLM shape: an
        ``LLMClient``-style object (``.complete(messages, ...)``) or a bare
        ``prompt -> str`` callable. Sibling discipline
        (``adversarial._PromptedActor``): governance cost metadata with the
        duck-typed TypeError fallback for metadata-less stubs."""
        complete = getattr(self._llm, "complete", None)
        if callable(complete):
            messages = [{"role": "user", "content": prompt}]
            try:
                resp = complete(
                    messages,
                    require_tool=False,
                    phase="governance",
                    skill="clean_room",
                )
            except TypeError:
                resp = complete(messages, require_tool=False)
            return str(getattr(resp, "content", "") or "")
        return str(self._llm(prompt) or "")

    def render_context(self, bundle: CleanRoomInputBundle, role: str) -> str:
        """The EXACT one-shot generation context (pure function): committed
        meta-prompt + canonical bundle JSON. Exposed so tests and the audit
        trail can prove no extra context reached the LLM."""
        template, _ = self._meta_prompt()
        return template.format(
            target_role=role,
            bundle_json=canonical_json(bundle.payload_dict()),
        )

    def generate(
        self,
        bundle: CleanRoomInputBundle,
        *,
        role: str,
        version: int,
        epoch_id: str = "",
        record_seq: int = 0,
        request_id: str = "",
        retirement_event_id: str = "",
    ) -> PromptCandidate | None:
        """One LLM call → one ``status="candidate"`` record (never active).

        Returns ``None`` (never raises) when the LLM is unavailable, fails,
        or returns empty text — the caller falls back per §5.6.
        """
        if self._llm is None:
            return None
        _, template_hash = self._meta_prompt()
        rendered = self.render_context(bundle, role)
        try:
            from ari.prompts import record_prompt_use

            record_prompt_use(
                self.META_PROMPT_KEY, template_hash,
                rendered_text=rendered, phase="governance",
                checkpoint_dir=self._checkpoint_dir,
            )
        except Exception:  # pragma: no cover - best-effort provenance
            pass
        try:
            new_text = self._complete(rendered)
        except Exception:
            log.warning("clean-room generator LLM call failed", exc_info=True)
            return None
        if not new_text.strip():
            return None

        candidate_id = format_prompt_id(role, int(version))
        placeholders = sorted(
            name
            for _, name, _, _ in string.Formatter().parse(new_text)
            if name is not None
        )
        new_spec = PromptSpec(
            prompt_id=candidate_id,
            role=role,
            version=int(version),
            status="candidate",
            generation_mode="clean_room",
            # No lineage on purpose: a clean-room successor has no parent
            # (plan 08 §5.2 — the retired spec is a forbidden input).
            parent_prompt_id=None,
            template_ref={
                "kind": "checkpoint",
                "key": f"rqgm_prompts/{candidate_id}",
            },
            prompt_hash=hash12(new_text),
            full_sha256=hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
            evolvable=True,
            epoch_introduced=epoch_id,
            spec={
                "role_instruction": new_text,
                "constitutional_constraints": list(
                    bundle.constitutional_constraints
                ),
                "input_contract": {"required_fields": placeholders},
                "output_schema": dict(bundle.output_schema),
                "rubric": {},
                "calibration_policy": {},
                "budget_policy": dict(bundle.cost_budget),
            },
        )
        candidate = PromptCandidate(
            record_id=format_candidate_record_id(record_seq),
            epoch_id=epoch_id,
            component_id=self.component_id,
            prompt_hash=new_spec.prompt_hash,
            candidate_id=candidate_id,
            role=role,
            generated_by={
                "component_id": self.component_id,
                "clean_room_request_id": request_id,
                "bundle_hash": bundle.bundle_hash,
            },
            generation_mode="clean_room",
            mutation_kind="",
            source_prompt_id=None,
            failure_summary_refs=tuple(
                bundle.abstract_failure_summary.get("source_refs") or ()
            ),
            rationale=(
                f"clean-room regeneration after {retirement_event_id}"
                if retirement_event_id else "clean-room regeneration"
            ),
            prompt_spec=new_spec.to_dict(),
            status="candidate",
            source_refs=tuple(
                r for r in (request_id, retirement_event_id) if r
            ),
        )
        ckpt = _resolve_checkpoint_dir(self._checkpoint_dir)
        if ckpt is not None:
            try:
                write_evolved_prompt_body(ckpt, candidate_id, new_text)
            except Exception:
                log.warning("clean-room body write failed", exc_info=True)
        return candidate


# ── Layer B: the sanctioned retired-prompt-text read path ───────────────────


class RetiredPromptAccessGuard:
    """Capability denial at the sanctioned registry read API (plan 08 §5.3).

    ``get_retired_text`` is the ONLY supported way to read retired prompt
    text. Non-exempt actors are denied via the kernel's pure capability
    check (CK-ACC-002 — unconditional for ``retired_prompt_text``) and the
    violation is appended to the immutable audit log before the
    ``PermissionError`` is raised. Selective erasure deletes nothing
    (invariant 13); only access is guarded.
    """

    def __init__(
        self, registry, kernel=None, *, audit_log=None, checkpoint_dir=None
    ) -> None:
        self._registry = registry
        self._kernel = kernel
        self._audit_log = audit_log
        self._ckpt = checkpoint_dir

    def get_retired_text(self, actor, prompt_id: str) -> tuple[str, str]:
        from ari.rqgm.kernel import _actor_role_tier

        role, tier = _actor_role_tier(actor)
        if (role, tier) in EXEMPT_RETIRED_READERS:
            # The documented kernel-reader exemption: fixed tier,
            # deterministic, emits only booleans/hashes onward.
            return self._registry.resolve_text(
                prompt_id, checkpoint_dir=self._ckpt
            )
        report = None
        if self._kernel is not None:
            report = self._kernel.validate_capability(
                actor, "read", "retired_prompt_text"
            )
        if self._audit_log is not None:
            try:
                self._audit_log.append("clean_room_violation", {
                    "violation": "retired_prompt_text_read_denied",
                    "actor": f"{role}|{tier}",
                    "prompt_id": str(prompt_id),
                    "kernel_report": (
                        report.to_dict() if report is not None else None
                    ),
                })
            except Exception:  # pragma: no cover - best-effort logging
                log.warning("audit append failed for retired-text denial",
                            exc_info=True)
        raise PermissionError(
            f"actor {role}|{tier} may not read retired prompt text "
            f"({prompt_id}); clean-room regeneration receives abstract "
            "inputs only (invariant 14)"
        )


# ── {ckpt}/rqgm_cleanroom.jsonl (plan 08 §6.4) ──────────────────────────────

# Serialises appends (boundary thread + best-effort callers) — the
# ``record_prompt_use`` lock discipline.
_LOCK = threading.Lock()


def _now_iso() -> str:
    """UTC metadata timestamp (never hashed, never read by decisions — P2)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_cleanroom_event(checkpoint_dir, event: dict) -> bool:
    """Append one event line; ``False`` == not written.

    Fail-open like every ARI provenance writer: no resolvable checkpoint →
    no-op; I/O failure is logged, never raised into the run loop.
    """
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return False
    payload = dict(event)
    if not payload.get("created_at"):
        payload["created_at"] = _now_iso()
    try:
        with _LOCK:
            Path(ckpt).mkdir(parents=True, exist_ok=True)
            with open(
                Path(ckpt) / CLEANROOM_FILENAME, "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception:
        log.warning("clean-room event append failed", exc_info=True)
        return False


def _read_jsonl(path: Path) -> list[dict]:
    """Absence-tolerant JSONL reader (raw line dicts, oldest first)."""
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def read_cleanroom_log(checkpoint_dir) -> list[dict]:
    """Absence-tolerant reader (raw line dicts, oldest first)."""
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is None:
        return []
    return _read_jsonl(Path(ckpt) / CLEANROOM_FILENAME)


def pending_requests(checkpoint_dir) -> list[CleanRoomGenerationRequest]:
    """Replay the event log into the still-``pending`` request list
    (first-seen order). Resume-safe: a resumed run re-reads pending requests
    from here, never from BFTS in-memory state (plan 08 §8)."""
    requests: dict[str, dict] = {}
    status: dict[str, str] = {}
    for event in read_cleanroom_log(checkpoint_dir):
        kind = str(event.get("event", ""))
        rid = str(event.get("request_id", ""))
        if kind == "request_created" and isinstance(
            event.get("request"), dict
        ):
            rid = rid or str(event["request"].get("record_id", ""))
            if rid and rid not in requests:
                requests[rid] = event["request"]
                status[rid] = str(event["request"].get("status", "pending"))
        elif kind == "request_status" and rid in requests:
            status[rid] = str(event.get("status", status.get(rid, "")))
    return [
        request_from_dict(requests[rid])
        for rid in requests
        if status.get(rid) == "pending"
    ]


# ── §5.5 forbidden-corpus resolution (kernel-checker exemption reads) ───────


def _collect_strings(node, sink: list) -> None:
    """Every string in *node*'s subtree, deterministic (sorted-key) order."""
    if isinstance(node, str):
        if node:
            sink.append(node)
    elif isinstance(node, dict):
        for key in sorted(node):
            _collect_strings(node[key], sink)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_strings(item, sink)


def _texts_under_prompt_hash(node, hashes: set, sink: list) -> None:
    """Strings of every record subtree stamped with a retired
    ``prompt_hash`` — the §5.5 "audit-log outputs produced under the
    retired prompt_hash" (forbidden input 3: the retired prompt's own
    reasoning/review/attack/defense text in the audit log)."""
    if isinstance(node, dict):
        if str(node.get("prompt_hash") or "") in hashes:
            _collect_strings(node, sink)
            return
        for key in sorted(node):
            _texts_under_prompt_hash(node[key], hashes, sink)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _texts_under_prompt_hash(item, hashes, sink)


def _case_record_body(record: dict) -> str:
    """The §5.2 forbidden bodies out of one Task 06 case-log line:
    ``RawAttackRecord.attack_claim`` (forbidden input 4) and
    ``DefenderResponse.rebuttal_text``/``proposed_fix`` (forbidden input 5).
    ``""`` for every other record type."""
    record_type = str(record.get("record_type", ""))
    if record_type == "raw_attack":
        parts = [str(record.get("attack_claim") or "")]
    elif record_type == "defender_response":
        parts = [
            str(record.get("rebuttal_text") or ""),
            str(record.get("proposed_fix") or ""),
        ]
    else:
        return ""
    return "\n".join(p for p in parts if p)


# ── epoch-boundary coordinator (plan 08 §5.1 timing / §5.6 fallback) ────────


class CleanRoomCoordinator:
    """Processes clean-room requests inside the epoch-boundary window, on
    the main thread, right after ``RegistryTransitionEngine.apply`` commits
    (codebase reality: the store's boundary transaction closes AND opens the
    epoch inside ``apply``, so "after apply" IS the §5.1 window).

    Fail-closed for candidate admission, fail-open for the run: any
    violation or failure records its event, the role falls back to its
    committed baseline template (§5.6 — baselines are never ``banned``, so
    a retirement can never leave a role vacant), and the BFTS loop
    continues.
    """

    def __init__(
        self,
        rqgm_cfg=None,
        kernel=None,
        *,
        llm=None,
        loader=None,
        checkpoint_dir=None,
        assembler: CleanRoomInputBundleAssembler | None = None,
        generator: CleanRoomPromptGenerator | None = None,
    ) -> None:
        self._cfg = rqgm_cfg
        self._kernel = kernel
        self._ckpt = checkpoint_dir
        self.assembler = assembler or CleanRoomInputBundleAssembler()
        self.generator = generator or CleanRoomPromptGenerator(
            llm=llm, loader=loader, checkpoint_dir=checkpoint_dir,
        )

    # ── config views ──────────────────────────────────────────────────

    def max_generations_per_epoch(self) -> int:
        pe = getattr(self._cfg, "prompt_evolution", None)
        if pe is None and isinstance(self._cfg, dict):
            pe = self._cfg.get("prompt_evolution")
        raw = (
            pe.get("max_clean_room_generations_per_epoch")
            if isinstance(pe, dict)
            else getattr(pe, "max_clean_room_generations_per_epoch", 1)
        )
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1

    # ── forbidden / allowlist corpora (kernel-checker exemption read) ─

    def forbidden_corpus(self, request, prompts) -> dict:
        """The full §5.5 forbidden corpus, resolved ON BEHALF OF the
        kernel's contamination checker (the §5.3 exemption: fixed-tier
        deterministic screen; only booleans/hashes flow onward, never the
        text): retired/banned prompt texts for the target role (through
        the governed registry), ``RawAttackRecord``/``DefenderResponse``
        bodies from the checkpoint case log, and audit-log outputs
        produced under a retired ``prompt_hash``.

        Deviation from §5.5 noted: case bodies are included for ALL
        recorded cases, not only the retirement's triggering cases — the
        triggering-case linkage is not resolvable from the transition
        entry alone, and over-screening is the safe direction (a blocked
        clean candidate costs one epoch; the §5.6 fallback covers the
        role, and the allowlist keeps legitimate overlap hit-free)."""
        out: dict = {}
        retired_hashes: set[str] = set()
        entries = getattr(prompts, "entries", None)
        entries = entries() if callable(entries) else {}
        for prompt_id in sorted(entries):
            entry = entries[prompt_id]
            if (
                str(getattr(entry, "role", "")) != request.target_role
                or str(getattr(entry, "status", "")) not in _RETIRED_STATUSES
            ):
                continue
            declared = str(getattr(entry, "prompt_hash", "") or "")
            if declared:
                retired_hashes.add(declared)
            try:
                text, version = prompts.resolve_text(
                    prompt_id, checkpoint_dir=self._ckpt
                )
            except Exception:
                # Unlike every other (intentional, benign) swallow in this
                # module, dropping a retired prompt's BODY silently weakens
                # CK-CLN-001/002: a k-gram-sharing near/byte copy of this
                # retired prompt could then evade the screen. Name it so the
                # weakened screen stays auditable. The exact-copy guard is
                # retained: ``declared`` (the retired prompt's registered
                # hash) was already added to ``retired_hashes`` above.
                log.warning(
                    "forbidden-corpus: retired prompt %s body could not be "
                    "resolved for role %s; its TEXT is excluded from the "
                    "contamination screen this boundary (exact-copy guard "
                    "via its declared hash retained)",
                    prompt_id, request.target_role, exc_info=True,
                )
                continue
            if text:
                out[prompt_id] = text
                retired_hashes.add(hash12(text))
            if version:
                retired_hashes.add(str(version))
        ckpt = _resolve_checkpoint_dir(self._ckpt)
        if ckpt is None:
            return out
        for i, record in enumerate(
            _read_jsonl(Path(ckpt) / _ADVERSARIAL_CASES_FILENAME)
        ):
            body = _case_record_body(record)
            if body:
                doc_id = str(record.get("record_id") or "case_%05d" % i)
                out.setdefault(doc_id, body)
        if retired_hashes:
            for i, line in enumerate(
                _read_jsonl(Path(ckpt) / _AUDIT_FILENAME)
            ):
                sink: list = []
                _texts_under_prompt_hash(
                    line.get("payload"), retired_hashes, sink
                )
                if sink:
                    out.setdefault("audit_%05d" % i, "\n".join(sink))
        return out

    # ── the boundary pass ─────────────────────────────────────────────

    def process_boundary(
        self,
        transition=None,
        *,
        epoch_id: str = "",
        prompts=None,
        failure_summaries=(),
    ) -> list[dict]:
        """Persist new requests, then execute up to the per-epoch budget of
        pending ones. Returns one outcome dict per executed request; excess
        requests remain ``pending`` and retry at the next boundary."""
        self._persist_new_requests(transition, epoch_id)
        outcomes: list[dict] = []
        budget = self.max_generations_per_epoch()
        for request in pending_requests(self._ckpt)[:budget]:
            outcomes.append(
                self._execute(
                    request,
                    epoch_id=epoch_id,
                    prompts=prompts,
                    failure_summaries=failure_summaries,
                )
            )
        return outcomes

    def _persist_new_requests(self, transition, epoch_id: str) -> None:
        if transition is None:
            return
        t = (
            transition
            if isinstance(transition, dict)
            else getattr(transition, "to_dict", lambda: {})()
        )
        known = {
            str(e.get("request_id", ""))
            or str((e.get("request") or {}).get("record_id", ""))
            for e in read_cleanroom_log(self._ckpt)
            if e.get("event") == "request_created"
        }
        for entry in t.get("clean_room_requests") or ():
            request = request_from_transition_entry(
                dict(entry),
                epoch_id=epoch_id,
                transition_id=str(
                    t.get("epoch_transition_id", "")
                ),
            )
            if not request.record_id or request.record_id in known:
                continue
            append_cleanroom_event(self._ckpt, {
                "event": "request_created",
                "request_id": request.record_id,
                "request": request.to_dict(),
            })

    def _execute(
        self, request, *, epoch_id: str, prompts, failure_summaries
    ) -> dict:
        outcome = {"request_id": request.record_id, "status": "failed"}

        def finish(status: str, **extra) -> dict:
            append_cleanroom_event(self._ckpt, {
                "event": "request_status",
                "request_id": request.record_id,
                "status": status,
            })
            outcome.update(status=status, **extra)
            return outcome

        schema_failures = request_schema_failures(request)
        if schema_failures:
            append_cleanroom_event(self._ckpt, {
                "event": "clean_room_violation",
                "request_id": request.record_id,
                "stage": "request_schema",
                "detail": schema_failures[:5],
            })
            return finish("failed", detail="request schema invalid")

        bundle = self.assembler.assemble(
            request, failure_summaries=failure_summaries,
        )
        append_cleanroom_event(self._ckpt, {
            "event": "bundle_assembled",
            "request_id": request.record_id,
            "bundle_id": bundle.bundle_id,
            "bundle_hash": bundle.bundle_hash,
        })

        forbidden = self.forbidden_corpus(request, prompts)
        allowlist = bundle_allowlist_corpus(bundle)
        if self._kernel is not None:
            pre = self._kernel.validate_clean_room_bundle(
                bundle.to_dict(), request.to_dict(),
                {"forbidden_texts": forbidden, "allowlist_texts": allowlist},
            )
            if pre.blocking:
                append_cleanroom_event(self._ckpt, {
                    "event": "clean_room_violation",
                    "request_id": request.record_id,
                    "stage": "pre_generation",
                    "kernel_report": pre.to_dict(),
                })
                self._fallback(request, prompts)
                return finish("failed", detail="bundle blocked by kernel")

        candidate = self.generator.generate(
            bundle,
            role=request.target_role,
            version=self._next_version(request.target_role, prompts),
            epoch_id=epoch_id,
            record_seq=self._next_candidate_seq(),
            request_id=request.record_id,
            retirement_event_id=request.retirement_event_id,
        )
        append_cleanroom_event(self._ckpt, {
            "event": "generation_attempted",
            "request_id": request.record_id,
            "bundle_hash": bundle.bundle_hash,
            "rendered_prompt_hash": hash12(
                self.generator.render_context(bundle, request.target_role)
            ) if candidate is not None else "",
            "succeeded": candidate is not None,
        })
        if candidate is None:
            self._fallback(request, prompts)
            return finish("failed", detail="generation unavailable")

        candidate_text = str(
            (candidate.prompt_spec.get("spec") or {}).get(
                "role_instruction", ""
            )
        )
        if self._kernel is not None:
            post = self._kernel.validate_contamination_free(
                candidate_text,
                {
                    "retirement_event_id": request.retirement_event_id,
                    "forbidden_texts": forbidden,
                    "allowlist_texts": allowlist,
                },
                (),
            )
            if post.blocking:
                append_cleanroom_event(self._ckpt, {
                    "event": "candidate_rejected_contaminated",
                    "request_id": request.record_id,
                    "candidate_id": candidate.candidate_id,
                    "kernel_report": post.to_dict(),
                })
                self._fallback(request, prompts)
                return finish(
                    "rejected_contaminated",
                    candidate_id=candidate.candidate_id,
                )

        # Task 07 lifecycle entry at the VERY BEGINNING (status=candidate;
        # any skip toward `active` is kernel-rejected — invariant 15).
        record_prompt_evolution_event(self._ckpt, candidate)
        append_cleanroom_event(self._ckpt, {
            "event": "candidate_registered",
            "request_id": request.record_id,
            "candidate_id": candidate.candidate_id,
            "prompt_hash": candidate.prompt_hash,
            "bundle_hash": bundle.bundle_hash,
        })
        return finish("generated", candidate_id=candidate.candidate_id)

    def _fallback(self, request, prompts) -> None:
        """§5.6 no-vacancy rule: when the role has no active prompt and no
        admissible candidate, it reverts to its committed baseline template
        for the next epoch (recorded, never a crash)."""
        active = {}
        getter = getattr(prompts, "active_prompt_hashes", None)
        if callable(getter):
            try:
                active = dict(getter())
            except Exception:
                active = {}
        if request.target_role in active:
            return
        append_cleanroom_event(self._ckpt, {
            "event": "fallback_to_baseline",
            "request_id": request.record_id,
            "role": request.target_role,
        })

    def _next_version(self, role: str, prompts) -> int:
        """Successor version = 1 + the role's max version across BOTH the
        governed registry AND this boundary's ``prompt_evolution.jsonl``
        candidate log (id format ``{role}_prompt_v{N}``); metadata only, no
        text read.

        Consulting the log is the cross-channel candidate-id dedup: FIX-A
        (``_generate_prompt_candidates``) and the meta channel mint
        ``format_prompt_id(role, incumbent.version + 1)`` and persist it to
        the same log BEFORE the boundary commit, so folding the log's
        candidate ids in here makes the clean-room channel skip past any id
        another channel already minted this boundary — a clean-room
        successor never reuses (orphans) a FIX-A/meta id, and the three
        channels never emit the same ``candidate_id`` (nor, after intake, a
        duplicate ``prompt_registered``)."""
        version = 1

        def _bump(candidate_id: str) -> None:
            nonlocal version
            m = _VERSION_RE.search(str(candidate_id))
            if m:
                version = max(version, int(m.group(1)))

        entries = getattr(prompts, "entries", None)
        entries = entries() if callable(entries) else {}
        for prompt_id, entry in entries.items():
            if str(getattr(entry, "role", "")) == role:
                _bump(prompt_id)
        for rec in load_prompt_evolution_log(self._ckpt):
            if (
                rec.get("record_type") == "prompt_candidate"
                and str(rec.get("role", "")) == role
            ):
                _bump(rec.get("candidate_id", ""))
        return version + 1

    def _next_candidate_seq(self) -> int:
        records = load_prompt_evolution_log(self._ckpt)
        return sum(
            1 for r in records if r.get("record_type") == "prompt_candidate"
        )
