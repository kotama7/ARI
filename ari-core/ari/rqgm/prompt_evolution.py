"""Prompt evolution: candidates, validation pipeline, shadow, budgets
(RQGM Task 07 §5.3-§5.6, §6-§7).

The nine-state candidate lifecycle::

    candidate
      → static_validation          (deterministic, free)
      → constitutional_validation  (deterministic, free)
      → schema_dry_run             (1 injected-LLM call, terminal on failure)
      → replay_evaluation          (Task 06 AdversarialReplayPool, budgeted)
      → anchor_evaluation          (fixed anchor set, ties favor incumbent)
      → shadow                     (sampled side-by-side; observation-only)
      → probationary_active        (epoch-boundary adoption — Task 09 ONLY)
      → active

Hard prohibitions structurally enforced here (plan 07 §1):

* **PromptMutator never writes to the registry** — it emits
  :class:`PromptCandidate` records only; the sole public surface is
  ``propose``. Status changes are Task 09's RegistryTransitionEngine,
  validated by Task 04's kernel.
* **No instant activation** — :meth:`CandidateValidationPipeline.run_stage`
  rejects any out-of-order stage, and :func:`build_adoption_request` refuses
  to hand a candidate to the transition engine before all six stage records
  passed. Founding bootstrap (``ari.rqgm.prompt_spec``) is the sole
  documented ``active``-on-creation path.
* **No in-place mutation** — new ``prompt_id`` + write-once bodies
  (``ari.rqgm.prompt_loader``); static validation independently rejects a
  candidate that reuses an existing ``prompt_id`` with different bytes.

Persistence: ``{ckpt}/prompt_evolution.jsonl`` is the append-only truth
(fail-open writer modeled on ``ari/prompts/_provenance.record_prompt_use``);
``{ckpt}/prompt_specs.json`` is a derived rollup (the
``prompt_versions.json`` pattern). Under ``simple_bfts`` nothing constructs
these classes and neither file is ever created.

Deterministic decision logic (P2): the LLM-consuming stages take injectable
clients/evaluators (tests use deterministic fakes); the deterministic stages
are pure functions; timestamps are metadata only, never hashed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import string

from ari.rqgm.events import canonical_json, format_prompt_id, hash12
from ari.rqgm.prompt_loader import (
    _resolve_checkpoint_dir,
    evolved_prompt_path,
    write_evolved_prompt_body,
)

# Record shapes + persistence live in ari.rqgm.prompt_records; re-exported
# here so Task 07 consumers keep a single import home (plan 07 §7 module
# family). The split mirrors Task 06's adversarial/records.py layout.
from ari.rqgm.prompt_records import (  # noqa: F401  (re-exported)
    PROMPT_EVOLUTION_FILENAME,
    PROMPT_SPECS_FILENAME,
    PROMPT_SPECS_SCHEMA_VERSION,
    ComparisonObservation,
    PromptCandidate,
    PromptCandidateValidation,
    _now_iso,
    build_prompt_specs_rollup,
    candidate_from_dict,
    format_candidate_record_id,
    format_observation_record_id,
    format_validation_record_id,
    load_prompt_evolution_log,
    record_prompt_evolution_event,
    save_prompt_specs_snapshot,
)
from ari.rqgm.prompt_spec import (
    FORBIDDEN_PLACEHOLDERS,
    GENERATION_MODES,
    REQUIRED_CONSTRAINTS_BY_ROLE,
    TEMPLATE_REF_KINDS,
    PromptSpec,
)

log = logging.getLogger(__name__)

#: The six validation stages between ``candidate`` and
#: ``probationary_active`` (plan 07 §5.3). Order is monotonic; skipping is a
#: constitutional violation detectable from the record chain.
STAGES: tuple[str, ...] = (
    "static_validation",
    "constitutional_validation",
    "schema_dry_run",
    "replay_evaluation",
    "anchor_evaluation",
    "shadow",
)

#: Stages that are pure functions — no LLM, no budget (plan 07 §5.3).
DETERMINISTIC_STAGES: tuple[str, ...] = (
    "static_validation",
    "constitutional_validation",
)

#: The full nine-state lifecycle, for reference/validation.
LIFECYCLE_STATES: tuple[str, ...] = (
    ("candidate",) + STAGES + ("probationary_active", "active")
)

#: The five bounded PromptMutator output modes (plan 07 §5.4).
MUTATION_KINDS: tuple[str, ...] = (
    "freeform_mutation",
    "threshold_tuning",
    "schema_tightening",
    "specialization",
    "distillation",
)

#: Raw adjudication-material id prefixes a ``clean_room`` candidate may not
#: reference (Task 08 contamination rule; Task 06 id formats).
_CONTAMINATED_REF_PREFIXES: tuple[str, ...] = ("atk_", "def_", "jdg_")


# ── deterministic stage checks (pure functions; plan 07 §5.3 stages 1-2) ────


def _template_fields(text: str) -> set[str]:
    """``str.format`` root field names (the ``PromptRegistry`` extraction)."""
    names: set[str] = set()
    for _lit, field_name, _spec, _conv in string.Formatter().parse(text):
        if not field_name:
            continue
        root = field_name.replace("[", ".").split(".", 1)[0]
        if root:
            names.add(root)
    return names


def _numeric(value) -> bool:
    # bools count: the plan's threshold_tuning examples include the
    # all-accept/all-reject guard toggles (§5.4).
    return isinstance(value, (int, float, bool))


def _diff_only_numeric(old: dict, new: dict) -> list[str]:
    """Failures unless *new* differs from *old* only in numeric leaf values."""
    failures: list[str] = []
    if set(old) != set(new):
        failures.append(
            "threshold_tuning may not add or remove keys "
            f"(old={sorted(old)}, new={sorted(new)})"
        )
        return failures
    for key in sorted(old):
        if old[key] == new[key]:
            continue
        if isinstance(old[key], dict) and isinstance(new[key], dict):
            failures.extend(_diff_only_numeric(old[key], new[key]))
        elif not (_numeric(old[key]) and _numeric(new[key])):
            failures.append(f"threshold_tuning touched non-numeric key {key!r}")
    return failures


def static_validation_failures(
    candidate: PromptCandidate,
    template_text: str,
    *,
    incumbent: PromptSpec | None = None,
    known_specs: dict | None = None,
) -> list[str]:
    """Stage-1 deterministic checks (plan 07 §5.3 item 1). Empty == pass.

    *known_specs* is a ``prompt_id -> PromptSpec-or-entry`` view (duck-typed
    ``status`` / ``prompt_hash`` attributes or keys) used for lineage and
    in-place-mutation checks.
    """
    failures: list[str] = []
    spec = candidate.prompt_spec or {}
    body = dict(spec.get("spec") or {})

    # Template parses; placeholder contract matches the declaration.
    try:
        declared = set(
            (body.get("input_contract") or {}).get("required_fields") or ()
        )
        actual = _template_fields(template_text)
    except ValueError as exc:
        return [f"template does not parse: {exc}"]
    if actual != declared:
        failures.append(
            f"placeholder drift: template has {sorted(actual)}, "
            f"input_contract declares {sorted(declared)}"
        )
    forbidden = actual & FORBIDDEN_PLACEHOLDERS
    if forbidden:
        failures.append(f"forbidden placeholders: {sorted(forbidden)}")

    # Hash discipline: candidate identity is the template bytes.
    if hash12(template_text) != str(spec.get("prompt_hash", "")):
        failures.append("prompt_hash does not match template bytes")
    if candidate.prompt_hash != str(spec.get("prompt_hash", "")):
        failures.append("envelope prompt_hash disagrees with prompt_spec")

    # Externalized-template rule (scripts/check_prompts.py doctrine).
    ref = dict(spec.get("template_ref") or {})
    if str(ref.get("kind", "")) not in TEMPLATE_REF_KINDS:
        failures.append(f"unknown template_ref kind {ref.get('kind')!r}")
    if str(candidate.generation_mode) not in GENERATION_MODES:
        failures.append(
            f"unknown generation_mode {candidate.generation_mode!r}"
        )
    if candidate.mutation_kind and candidate.mutation_kind not in MUTATION_KINDS:
        failures.append(f"unknown mutation_kind {candidate.mutation_kind!r}")

    # Size within the declared token budget (~4 chars/token estimate).
    max_tokens = (body.get("budget_policy") or {}).get("max_tokens")
    if max_tokens is not None and len(template_text) // 4 > int(max_tokens):
        failures.append(
            f"template exceeds budget_policy.max_tokens={max_tokens} "
            f"(~{len(template_text) // 4} tokens)"
        )

    failures.extend(_lineage_failures(candidate, known_specs))
    if incumbent is not None:
        failures.extend(
            _mutation_family_failures(candidate, body, actual, incumbent)
        )
    return failures


def _spec_field(spec_or_dict, name: str) -> str:
    """Duck-typed field read over PromptSpec / GovernedPromptEntry / dict."""
    value = getattr(spec_or_dict, name, None)
    if value is None and isinstance(spec_or_dict, dict):
        value = spec_or_dict.get(name)
    return str(value or "")


def _lineage_failures(
    candidate: PromptCandidate, known_specs: dict | None
) -> list[str]:
    """Parent liveness + no-in-place-mutation clauses of stage 1."""
    failures: list[str] = []
    if candidate.generation_mode == "mutation":
        parent_id = candidate.source_prompt_id or ""
        if not parent_id:
            failures.append("mutation candidate lacks source_prompt_id")
        elif known_specs is not None:
            parent = known_specs.get(parent_id)
            if parent is None:
                failures.append(f"parent prompt {parent_id!r} is unknown")
            elif _spec_field(parent, "status") in ("retired", "banned"):
                failures.append(
                    f"parent prompt {parent_id!r} is "
                    f"{_spec_field(parent, 'status')}"
                )
        if candidate.candidate_id == candidate.source_prompt_id:
            failures.append(
                "candidate_id equals source_prompt_id (in-place mutation)"
            )
    # An existing prompt_id may never re-appear with different bytes.
    if known_specs is not None:
        existing = known_specs.get(candidate.candidate_id)
        if existing is not None:
            ehash = _spec_field(existing, "prompt_hash")
            if ehash and ehash != candidate.prompt_hash:
                failures.append(
                    f"prompt_id {candidate.candidate_id!r} already exists "
                    "with different bytes (in-place mutation is prohibited)"
                )
    return failures


def _mutation_family_failures(
    candidate: PromptCandidate,
    body: dict,
    actual: set[str],
    incumbent: PromptSpec,
) -> list[str]:
    """Incumbent-relative clauses of stage 1 (plan 07 §5.4-§5.5)."""
    failures: list[str] = []
    inc_body = dict(incumbent.spec or {})
    # Key-swap safety (§5.5): a candidate must accept the incumbent's
    # EXACT placeholder set for its key.
    inc_contract = set(
        (inc_body.get("input_contract") or {}).get("required_fields") or ()
    )
    if actual != inc_contract:
        failures.append(
            "candidate must accept the incumbent's exact placeholder "
            f"set (incumbent {sorted(inc_contract)}, candidate "
            f"{sorted(actual)})"
        )
    if candidate.mutation_kind == "threshold_tuning":
        for section in ("role_instruction", "input_contract",
                        "output_schema", "constitutional_constraints",
                        "budget_policy"):
            if body.get(section) != inc_body.get(section):
                failures.append(
                    f"threshold_tuning changed {section!r} (only "
                    "calibration_policy/rubric numerics may change)"
                )
        for section in ("calibration_policy", "rubric"):
            failures.extend(
                _diff_only_numeric(
                    dict(inc_body.get(section) or {}),
                    dict(body.get(section) or {}),
                )
            )
    if candidate.mutation_kind == "schema_tightening":
        old_schema = dict(inc_body.get("output_schema") or {})
        new_schema = dict(body.get("output_schema") or {})
        missing = set(old_schema) - set(new_schema)
        if missing:
            failures.append(
                "schema_tightening loosened output_schema (dropped "
                f"{sorted(missing)}); narrowing only"
            )
        for key in sorted(set(old_schema) & set(new_schema)):
            if old_schema[key] != new_schema[key]:
                failures.append(
                    f"schema_tightening changed type of {key!r} "
                    f"({old_schema[key]!r} -> {new_schema[key]!r})"
                )
    return failures


def constitutional_validation_failures(
    candidate: PromptCandidate,
    *,
    component_roles: dict | None = None,
) -> list[str]:
    """Stage-2 deterministic kernel-side checks (plan 07 §5.3 item 2).

    Task 04's ConstitutionalKernel remains the authority for registry-level
    transitions; these are the candidate-side clauses this task owns.
    *component_roles* maps ``component_id -> role`` (from Task 02's
    ComponentRegistry) for the same-role separation check.
    """
    failures: list[str] = []
    body = dict((candidate.prompt_spec or {}).get("spec") or {})
    constraints = list(body.get("constitutional_constraints") or ())
    for required in REQUIRED_CONSTRAINTS_BY_ROLE.get(candidate.role, ()):
        if required not in constraints:
            failures.append(
                f"missing mandatory constraint for role "
                f"{candidate.role!r}: {required!r}"
            )

    # Provenance legality (Task 08 contamination rule, kernel-checked).
    if candidate.generation_mode == "clean_room":
        if candidate.source_prompt_id:
            failures.append(
                "clean_room candidate carries source_prompt_id "
                "(contamination rule)"
            )
        tainted = [
            ref
            for ref in (*candidate.source_refs, *candidate.failure_summary_refs)
            if str(ref).startswith(_CONTAMINATED_REF_PREFIXES)
        ]
        if tainted:
            failures.append(
                f"clean_room candidate references raw adjudication "
                f"material: {tainted}"
            )
    elif candidate.generation_mode == "mutation":
        if not candidate.source_prompt_id:
            failures.append("mutation candidate lacks source_prompt_id")
    elif candidate.generation_mode == "founding":
        failures.append(
            "founding specs never enter the candidate pipeline "
            "(bootstrap-only path)"
        )

    # No instant activation: candidates are born `candidate`, full stop.
    if candidate.status != "candidate":
        failures.append(
            f"candidate status must be 'candidate', got {candidate.status!r}"
        )
    spec_status = str((candidate.prompt_spec or {}).get("status", "candidate"))
    if spec_status != "candidate":
        failures.append(
            f"prompt_spec.status must be 'candidate', got {spec_status!r}"
        )

    # Same-role separation: the generating component may not hold the target
    # role (a reviewer must not author reviewer prompts).
    gen_id = str(
        (candidate.generated_by or {}).get("component_id")
        or candidate.component_id
    )
    if component_roles is not None:
        gen_role = component_roles.get(gen_id)
        if gen_role is not None and gen_role not in (
            "prompt_mutator", "clean_room_generator"
        ):
            failures.append(
                f"generating component {gen_id!r} has role {gen_role!r}; "
                "only prompt_mutator/clean_room_generator may emit candidates"
            )
        if gen_role is not None and gen_role == candidate.role:
            failures.append(
                f"same-role generation: {gen_id!r} shares role "
                f"{candidate.role!r} with its candidate"
            )
    return failures


def role_instruction_constraint_failures(
    role: str, role_instruction: str
) -> list[str]:
    """The §5.4 constitutional clauses MISSING from a candidate's *resolved*
    ``role_instruction`` bytes (empty list == conformant).

    This is the TEXT-side companion to
    :func:`constitutional_validation_failures`. That check reads the declared
    ``constitutional_constraints`` metadata list — which
    :meth:`PromptMutator.propose` force-injects (prompt_evolution.py:648-653),
    so it can never catch a candidate whose ACTUAL instruction bytes dropped a
    clause the mutator meta-prompt requires *verbatim*
    (``rqgm/prompt_mutator.md:22-24``: "the following constitutional constraint
    lines must appear verbatim in the candidate's constraints"). A candidate
    whose resolved ``role_instruction`` no longer carries, e.g., a
    ``paper_reviewer``'s "Do not override the claim-evidence hard gate." is
    behaviourally un-bound even while its metadata still nominally lists it —
    the pillar-4 (constitutional binding) hole this closes (plan
    ari_rqgm_paper/03 §5.9 step 2, /05 §5.5).

    The clause source is the SAME single authority the metadata check uses
    (:data:`REQUIRED_CONSTRAINTS_BY_ROLE`), so there is one definition of the
    §5.4 clauses, never a divergent copy. Deterministic (P2): pure substring
    membership, no LLM, no I/O.
    """
    text = role_instruction or ""
    return [
        clause
        for clause in REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
        if clause not in text
    ]


def check_output_against_schema(reply_text: str, output_schema: dict) -> list[str]:
    """Deterministically check one LLM reply against an ``output_schema``
    (plan 07 §5.3 stage 3). Empty == conforms.

    ``__reply__`` selects the reply kind (``bare_index`` / ``json_array`` /
    ``json_object`` / ``freeform``); the remaining keys are required JSON
    fields with type names (``list`` / ``dict`` / ``string`` / ``float`` /
    ``int`` / ``bool``).
    """
    kind = str((output_schema or {}).get("__reply__", "json_object"))
    text = (reply_text or "").strip()
    if not text:
        return ["empty reply"]
    if kind == "freeform":
        return []
    if kind == "bare_index":
        try:
            int(text)
        except ValueError:
            return [f"reply is not a bare integer index: {text[:80]!r}"]
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"reply is not valid JSON: {exc}"]
    if kind == "json_array":
        if not isinstance(parsed, list):
            return ["reply is not a JSON array"]
        return []
    if not isinstance(parsed, dict):
        return ["reply is not a JSON object"]
    type_map = {
        "list": list, "dict": dict, "string": str, "str": str,
        "float": (int, float), "int": int, "bool": bool,
    }
    failures: list[str] = []
    for key, type_name in sorted((output_schema or {}).items()):
        if key == "__reply__":
            continue
        if key not in parsed:
            failures.append(f"missing required field {key!r}")
            continue
        expected = type_map.get(str(type_name))
        if expected is not None and not isinstance(parsed[key], expected):
            failures.append(
                f"field {key!r} is not of type {type_name!r}"
            )
    return failures


# ── budgets (plan 07 §5.4 caps; numbers owned by Task 12) ────────────────────


def _cfg_evolution(cfg):
    return getattr(getattr(cfg, "rqgm", None), "prompt_evolution", None)


#: The Task-14 policy-candidate record type and the role it targets. A
#: ``prompt_candidate`` names its target role directly in ``role``; a
#: ``utility_policy_candidate``'s ``role`` is its AUTHOR (``policy_mutator``
#: — a candidate is a proposal BY a component, plan 14 §6.2), so its target
#: role is fixed by its type.
_UTILITY_CANDIDATE_TYPE = "utility_policy_candidate"
_UTILITY_TARGET_ROLE = "utility_policy"


def candidate_budget_reason(
    records: list[dict], epoch_id: str, role: str, cfg=None
) -> str | None:
    """Why a new candidate may NOT be minted this epoch (``None`` == ok).

    Both caps come from ``rqgm.prompt_evolution`` for both candidate
    channels — one schema home, no forked budget keys (plan 14 §5.4/§6.3).

    **Scope** (Task 14): the caps bound each CHANNEL's own per-epoch
    candidate volume; the two channels do not share one pot. Asking for
    ``role="utility_policy"`` counts ``utility_policy_candidate`` records;
    asking for any other role counts ``prompt_candidate`` records.

    This is load-bearing, not cosmetic. The Task 07 channel mints candidates
    for every evolvable role with an active incumbent and saturates
    ``max_total_candidates_per_epoch`` (4) on a default config BEFORE the
    PolicyMutator runs. Sharing one pot would therefore starve the utility
    rewrite in every default run — i.e. P1's cause half would be
    structurally unreachable again, which is the exact defect Task 14
    exists to remove. The utility channel is a SINGLETON role, so its
    effective cap is ``min(per_role, total) == 1`` candidate per epoch
    regardless; the prompt channel is byte-identical to pre-Task-14
    behavior, since ``utility_policy_candidate`` records did not exist.
    """
    evo = _cfg_evolution(cfg)
    per_role = int(getattr(evo, "max_candidates_per_role_per_epoch", 1))
    total_cap = int(getattr(evo, "max_total_candidates_per_epoch", 4))
    utility_channel = str(role) == _UTILITY_TARGET_ROLE
    want_type = (
        _UTILITY_CANDIDATE_TYPE if utility_channel else "prompt_candidate"
    )
    total = role_count = 0
    for rec in records:
        if str(rec.get("record_type", "")) != want_type:
            continue
        if str(rec.get("epoch_id", "")) != str(epoch_id):
            continue
        total += 1
        target = (
            _UTILITY_TARGET_ROLE if utility_channel
            else str(rec.get("role", ""))
        )
        if target == str(role):
            role_count += 1
    if role_count >= per_role:
        return (
            f"role {role!r} already has {role_count} candidate(s) in "
            f"{epoch_id} (cap {per_role})"
        )
    if total >= total_cap:
        return f"epoch {epoch_id} already has {total} candidates (cap {total_cap})"
    return None


# ── PromptMutator (meta tier; candidates only — plan 07 §5.4/§7) ─────────────


class PromptMutator:
    """Emits :class:`PromptCandidate` records ONLY.

    Deliberately exposes no registry/store write surface (pinned by the
    attribute test in ``tests/test_rqgm_prompt_lifecycle.py``): status
    changes are Task 09's engine, kernel-validated. The template-producing
    LLM is an injectable callable ``prompt -> str`` (tests use deterministic
    fakes); its meta-prompt is the committed ``rqgm/prompt_mutator.md``
    (externalized from day one, ``scripts/check_prompts.py`` doctrine).
    """

    ROLE = "prompt_mutator"
    META_PROMPT_KEY = "rqgm/prompt_mutator"

    def __init__(
        self,
        component_id: str = "prompt_mutator_v1",
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
        return loader.load_versioned("rqgm/prompt_mutator")

    def propose(
        self,
        role: str,
        incumbent: PromptSpec,
        failure_summaries=(),
        *,
        incumbent_text: str = "",
        mutation_kind: str = "freeform_mutation",
        epoch_id: str = "",
        record_seq: int = 0,
        existing_records: list[dict] | None = None,
        cfg=None,
        spec_overrides: dict | None = None,
        rationale: str = "",
    ) -> PromptCandidate | None:
        """Generate one mutation candidate for *role* from *incumbent*.

        Returns ``None`` (never raises) when over budget or when the
        template-producing LLM is unavailable for a text-rewriting kind.
        *failure_summaries* are abstract FailureSummary dicts (Task 06
        ``abstract_view`` — never raw attack text). *spec_overrides* patches
        the spec body for the knob-only kinds (threshold_tuning /
        schema_tightening).
        """
        if mutation_kind not in MUTATION_KINDS:
            log.warning("unknown mutation_kind %r; skipping", mutation_kind)
            return None
        if existing_records is not None:
            reason = candidate_budget_reason(
                existing_records, epoch_id, role, cfg
            )
            if reason is not None:
                log.info("prompt mutation skipped: %s", reason)
                return None

        if mutation_kind in ("threshold_tuning", "schema_tightening"):
            # Knob-only kinds keep the incumbent bytes.
            new_text = incumbent_text
        else:
            if self._llm is None:
                return None
            template, template_hash = self._meta_prompt()
            constraints = REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ())
            rendered = template.format(
                role=role,
                mutation_kind=mutation_kind,
                incumbent_instruction=incumbent_text,
                failure_summaries_block="\n".join(
                    f"- {canonical_json(s)}" for s in failure_summaries
                ) or "- (none this epoch)",
                required_constraints_block="\n".join(
                    f"  - {c}" for c in constraints
                ) or "  - (none for this role)",
            )
            try:
                from ari.prompts import record_prompt_use

                record_prompt_use(
                    self.META_PROMPT_KEY, template_hash,
                    rendered_text=rendered, phase="prompt_evolution",
                    checkpoint_dir=self._checkpoint_dir,
                )
            except Exception:  # pragma: no cover - best-effort provenance
                pass
            try:
                new_text = str(self._llm(rendered) or "")
            except Exception:
                log.warning("prompt mutator LLM call failed", exc_info=True)
                return None
            if not new_text.strip():
                return None

        candidate_id = format_prompt_id(role, int(incumbent.version) + 1)
        body = dict(incumbent.spec or {})
        if mutation_kind not in ("threshold_tuning", "schema_tightening"):
            # Text-rewriting kinds refresh the instruction copy and the
            # declared contract; knob-only kinds must leave both untouched
            # (static validation machine-checks the diff, §5.4).
            body["role_instruction"] = new_text
            body["constitutional_constraints"] = list(
                dict.fromkeys(
                    list(body.get("constitutional_constraints") or ())
                    + list(REQUIRED_CONSTRAINTS_BY_ROLE.get(role, ()))
                )
            )
            body["input_contract"] = {
                "required_fields": sorted(_template_fields(new_text)),
            }
        for key, value in (spec_overrides or {}).items():
            body[key] = value
        new_spec = PromptSpec(
            prompt_id=candidate_id,
            role=role,
            version=int(incumbent.version) + 1,
            status="candidate",
            generation_mode="mutation",
            parent_prompt_id=incumbent.prompt_id,
            template_ref={
                "kind": "checkpoint",
                "key": f"rqgm_prompts/{candidate_id}",
            },
            prompt_hash=hash12(new_text),
            full_sha256=hashlib.sha256(new_text.encode("utf-8")).hexdigest(),
            evolvable=True,
            epoch_introduced=epoch_id,
            spec=body,
        )
        candidate = PromptCandidate(
            record_id=format_candidate_record_id(record_seq),
            epoch_id=epoch_id,
            component_id=self.component_id,
            prompt_hash=new_spec.prompt_hash,
            candidate_id=candidate_id,
            role=role,
            generated_by={"component_id": self.component_id},
            generation_mode="mutation",
            mutation_kind=mutation_kind,
            source_prompt_id=incumbent.prompt_id,
            failure_summary_refs=tuple(
                str(s.get("summary_id", "")) if isinstance(s, dict) else str(s)
                for s in failure_summaries
            ),
            rationale=rationale,
            prompt_spec=new_spec.to_dict(),
            status="candidate",
        )
        # Persist the body write-once when a checkpoint is pinned (a body
        # file is prompt TEXT storage, not a registry write).
        ckpt = _resolve_checkpoint_dir(self._checkpoint_dir)
        if ckpt is not None:
            try:
                write_evolved_prompt_body(ckpt, candidate_id, new_text)
            except Exception:
                log.warning("evolved prompt body write failed", exc_info=True)
        return candidate


def resolve_candidate_text(candidate: PromptCandidate, checkpoint_dir=None) -> str:
    """Candidate template bytes: the write-once body file when present,
    else the spec's ``role_instruction`` copy (pre-persistence)."""
    ckpt = _resolve_checkpoint_dir(checkpoint_dir)
    if ckpt is not None:
        path = evolved_prompt_path(ckpt, candidate.candidate_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
    return str(
        ((candidate.prompt_spec or {}).get("spec") or {}).get(
            "role_instruction", ""
        )
    )


# ── validation pipeline (plan 07 §5.3/§7) ────────────────────────────────────


class CandidateValidationPipeline:
    """Drives a candidate through the six validation stages, one
    :class:`PromptCandidateValidation` per stage execution.

    Stage order is monotonic — :meth:`run_stage` rejects skipping, and a
    failed ``schema_dry_run`` is terminal. The deterministic stages are pure
    functions; ``schema_dry_run``/``replay_evaluation``/``anchor_evaluation``
    consume the injected *llm* / *case_evaluator*; the shadow stage
    summarizes the run-loop sampler's observations. The pipeline itself
    NEVER changes registry status — the end product is
    :func:`build_adoption_request` for Task 09's engine.
    """

    def __init__(
        self,
        *,
        checkpoint_dir=None,
        cfg=None,
        component_id: str = "governance_orchestrator",
        llm=None,
        case_evaluator=None,
        replay_pool=None,
        anchor_cases=(),
        known_specs: dict | None = None,
        component_roles: dict | None = None,
        run_id: str = "",
    ) -> None:
        self._ckpt = checkpoint_dir
        self._cfg = cfg
        self._run_id = str(run_id or "")
        self.component_id = component_id
        self._llm = llm
        self._case_evaluator = case_evaluator
        self._replay_pool = replay_pool
        self._anchor_cases = list(anchor_cases or ())
        self._known_specs = known_specs
        self._component_roles = component_roles
        self._records: list[dict] = list(
            load_prompt_evolution_log(checkpoint_dir)
            if checkpoint_dir is not None
            else ()
        )

    # ── record-chain introspection ────────────────────────────────────

    def records(self) -> list[dict]:
        return list(self._records)

    def stage_records(self, candidate_id: str) -> list[dict]:
        return [
            r
            for r in self._records
            if r.get("record_type") == "prompt_candidate_validation"
            and r.get("candidate_id") == candidate_id
        ]

    def passed_stages(self, candidate_id: str) -> list[str]:
        passed: list[str] = []
        for rec in self.stage_records(candidate_id):
            if rec.get("passed") and rec.get("stage") not in passed:
                passed.append(str(rec.get("stage")))
        return [s for s in STAGES if s in passed]

    def is_rejected(self, candidate_id: str) -> bool:
        """Terminal rejection: a failed schema_dry_run (plan 07 §5.3)."""
        return any(
            rec.get("stage") == "schema_dry_run" and not rec.get("passed")
            for rec in self.stage_records(candidate_id)
        )

    def next_stage(self, candidate_id: str) -> str | None:
        if self.is_rejected(candidate_id):
            return None
        passed = set(self.passed_stages(candidate_id))
        for stage in STAGES:
            if stage not in passed:
                return stage
        return None

    def ready_for_adoption(self, candidate_id: str) -> bool:
        return self.passed_stages(candidate_id) == list(STAGES)

    # ── stage execution ───────────────────────────────────────────────

    def run_stage(
        self,
        candidate: PromptCandidate,
        stage: str,
        *,
        template_text: str | None = None,
        incumbent: PromptSpec | None = None,
        fixture_kwargs: dict | None = None,
        incumbent_evaluator=None,
    ) -> PromptCandidateValidation:
        """Execute *stage* for *candidate* and append the stage record.

        Raises ``ValueError`` on an unknown or out-of-order stage — skipping
        lifecycle stages is a constitutional violation, not a soft failure.
        """
        if stage not in STAGES:
            raise ValueError(f"unknown lifecycle stage {stage!r}")
        expected = self.next_stage(candidate.candidate_id)
        if expected is None:
            raise ValueError(
                f"candidate {candidate.candidate_id!r} is terminal "
                "(rejected or fully validated); no further stages"
            )
        if stage != expected:
            raise ValueError(
                f"stage order is monotonic: expected {expected!r}, "
                f"got {stage!r} (skipping stages is a constitutional "
                "violation)"
            )
        if template_text is None:
            template_text = resolve_candidate_text(candidate, self._ckpt)

        case_results: list[dict] = []
        metrics: dict = {}
        if stage == "static_validation":
            failures = static_validation_failures(
                candidate, template_text,
                incumbent=incumbent, known_specs=self._known_specs,
            )
        elif stage == "constitutional_validation":
            failures = constitutional_validation_failures(
                candidate, component_roles=self._component_roles
            )
        elif stage == "schema_dry_run":
            failures, case_results = self._schema_dry_run(
                candidate, template_text, fixture_kwargs or {}
            )
        elif stage == "replay_evaluation":
            failures, case_results, metrics = self._case_evaluation(
                candidate,
                self._replay_cases(),
                incumbent=incumbent,
                incumbent_evaluator=incumbent_evaluator,
                pass_rate_key="replay_pass_rate",
            )
        elif stage == "anchor_evaluation":
            failures, case_results, metrics = self._case_evaluation(
                candidate,
                list(self._anchor_cases),
                incumbent=incumbent,
                incumbent_evaluator=incumbent_evaluator,
                pass_rate_key="anchor_pass_rate",
            )
            metrics["ties_favor_incumbent"] = True
        else:  # shadow
            observations = [
                r
                for r in self._records
                if r.get("record_type") == "comparison_observation"
                and r.get("candidate_id") == candidate.candidate_id
            ]
            metrics = {"observation_count": len(observations)}
            failures = (
                [] if observations else ["no shadow observations recorded"]
            )

        record = PromptCandidateValidation(
            record_id=format_validation_record_id(self._next_seq("pval")),
            epoch_id=candidate.epoch_id,
            component_id=self.component_id,
            candidate_id=candidate.candidate_id,
            role=candidate.role,
            prompt_hash=candidate.prompt_hash,
            stage=stage,
            passed=not failures,
            evaluated_by=self.component_id,
            case_results=tuple(case_results),
            metrics=metrics,
            details="; ".join(failures),
            source_refs=(candidate.record_id,),
        )
        self._append(record)
        return record

    # ── stage internals ───────────────────────────────────────────────

    def _schema_dry_run(
        self, candidate: PromptCandidate, template_text: str, kwargs: dict
    ) -> tuple[list[str], list[dict]]:
        body = dict((candidate.prompt_spec or {}).get("spec") or {})
        try:
            rendered = template_text.format(**kwargs) if kwargs else template_text
        except (KeyError, IndexError, ValueError) as exc:
            return [f"fixture render failed: {exc}"], []
        if self._llm is None:
            return ["no LLM client available for schema_dry_run"], []
        try:
            reply = str(self._llm(rendered) or "")
        except Exception as exc:
            return [f"dry-run LLM call failed: {exc}"], []
        failures = check_output_against_schema(
            reply, dict(body.get("output_schema") or {})
        )
        return failures, [
            {"case_id": "schema_dry_run", "met": not failures,
             "reply_hash": hash12(reply)}
        ]

    def _replay_cases(self) -> list:
        pool = self._replay_pool
        if pool is None:
            return []
        max_cases = int(
            getattr(
                getattr(getattr(self._cfg, "rqgm", None), "replay", None),
                "max_cases_per_epoch",
                8,
            )
        )
        try:
            return list(pool.select_for_replay(max_cases))
        except Exception:
            log.warning("replay-pool selection failed", exc_info=True)
            return []

    def _case_evaluation(
        self,
        candidate: PromptCandidate,
        cases: list,
        *,
        incumbent: PromptSpec | None,
        incumbent_evaluator,
        pass_rate_key: str,
    ) -> tuple[list[str], list[dict], dict]:
        """Shared replay/anchor mechanics (plan 07 §5.3 stages 4-5).

        *case_evaluator* is the injected prompt-defined component:
        ``evaluator(candidate, case) -> bool`` ("did the candidate meet the
        case's expected behavior?"). ``cache_key`` is stamped per Task 12's
        contract (deterministic content key; the cache itself lands there).
        """
        if self._case_evaluator is None:
            return (["no case evaluator available"], [], {})
        if not cases:
            # An empty pool/anchor set is a pass with zero coverage
            # (bootstrap epochs have no adjudicated cases yet).
            return ([], [], {pass_rate_key: 1.0, "case_count": 0})
        case_results: list[dict] = []
        met_count = 0
        inc_met = 0
        for case in cases:
            case_id = str(
                getattr(case, "case_id", None)
                or (case.get("case_id") if isinstance(case, dict) else "")
            )
            expected = (
                getattr(case, "replay_view", None)
                or (case if isinstance(case, dict) else {})
            )
            if hasattr(expected, "get"):
                expected = expected.get("expected_behavior", expected)
            try:
                met = bool(self._case_evaluator(candidate, case))
            except Exception:
                log.warning("case evaluation failed", exc_info=True)
                met = False
            met_count += met
            row = {
                "case_id": case_id,
                "expected": expected if isinstance(expected, (str, dict)) else "",
                "met": met,
                "cache_key": hash12(
                    canonical_json([candidate.prompt_hash, case_id])
                ),
                "cached": False,
            }
            if incumbent is not None and incumbent_evaluator is not None:
                try:
                    inc_ok = bool(incumbent_evaluator(incumbent, case))
                except Exception:
                    inc_ok = False
                inc_met += inc_ok
                row["incumbent_met"] = inc_ok
            case_results.append(row)
        rate = met_count / len(cases)
        metrics = {pass_rate_key: rate, "case_count": len(cases)}
        failures: list[str] = []
        if incumbent is not None and incumbent_evaluator is not None:
            inc_rate = inc_met / len(cases)
            metrics["incumbent_pass_rate"] = inc_rate
            metrics["beat_incumbent"] = rate > inc_rate
            if rate < inc_rate:
                failures.append(
                    f"candidate underperforms incumbent "
                    f"({rate:.3f} < {inc_rate:.3f})"
                )
        elif met_count < len(cases):
            failures.append(
                f"candidate failed {len(cases) - met_count}/{len(cases)} cases"
            )
        return failures, case_results, metrics

    # ── shadow attachment point (run-loop hook; plan 07 §5.3 stage 6) ─

    def shadow_budget_left(self, epoch_id: str) -> int:
        shadow_cfg = getattr(getattr(self._cfg, "rqgm", None), "shadow", None)
        if not bool(getattr(shadow_cfg, "enabled", True)):
            return 0  # rqgm.shadow.enabled=false zeroes this path (Task 12)
        cap = int(getattr(shadow_cfg, "max_shadow_calls_per_epoch", 10))
        used = sum(
            1
            for r in self._records
            if r.get("record_type") == "comparison_observation"
            and str(r.get("epoch_id", "")) == str(epoch_id)
        )
        return max(0, cap - used)

    def should_shadow(self, epoch_id: str, node_id: str) -> bool:
        """Deterministic sampling (P2: hash-based, no randomness).

        Delegates to ``GovernanceBudgetManager.shadow_sample`` — the single
        §5.6 hash rule (plan 12) — so this live sampler and the budget
        layer's ``select_shadow_nodes`` can never disagree, and
        ``rqgm.shadow.enabled: false`` zeroes both.
        """
        if self.shadow_budget_left(epoch_id) <= 0:
            return False
        from ari.rqgm.budget import GovernanceBudgetManager

        manager = GovernanceBudgetManager(
            self._cfg,
            epoch_state={"epoch_id": str(epoch_id), "run_id": self._run_id},
        )
        return manager.shadow_sample(str(node_id))

    def record_shadow_observation(
        self,
        candidate: PromptCandidate,
        incumbent_id: str,
        *,
        node_id: str = "",
        input_context: str = "",
        candidate_output: str = "",
        incumbent_output: str = "",
        divergence: dict | None = None,
    ) -> ComparisonObservation:
        """Append one shadow side-by-side observation.

        The candidate's output goes ONLY into this record — never into
        node metrics, the frontier, memory, or any downstream consumer.
        """
        obs = ComparisonObservation(
            record_id=format_observation_record_id(self._next_seq("cobs")),
            epoch_id=candidate.epoch_id,
            component_id=self.component_id,
            candidate_id=candidate.candidate_id,
            incumbent_id=incumbent_id,
            role=candidate.role,
            prompt_hash=candidate.prompt_hash,
            input_context_hash=hash12(input_context) if input_context else "",
            node_id=node_id,
            candidate_output_hash=(
                hash12(candidate_output) if candidate_output else ""
            ),
            incumbent_output_hash=(
                hash12(incumbent_output) if incumbent_output else ""
            ),
            divergence=dict(divergence or {}),
        )
        self._append(obs)
        return obs

    # ── plumbing ──────────────────────────────────────────────────────

    _SEQ_PREFIX = {"pval": "pval_", "cobs": "cobs_"}

    def _next_seq(self, kind: str) -> int:
        prefix = self._SEQ_PREFIX[kind]
        return sum(
            1
            for r in self._records
            if str(r.get("record_id", "")).startswith(prefix)
        )

    def _append(self, record) -> None:
        payload = record.to_dict()
        if not payload.get("created_at"):
            payload["created_at"] = _now_iso()
        self._records.append(payload)
        if self._ckpt is not None:
            record_prompt_evolution_event(self._ckpt, payload)

    def add_candidate(self, candidate: PromptCandidate) -> None:
        """Log a freshly proposed candidate (the mutator has no log access)."""
        self._append(candidate)


def candidate_registration_payload(candidate) -> dict:
    """The Task 07 candidate-intake ``prompt_registered`` payload
    (``status="candidate"``) for a minted candidate — the storage face of
    intake so that the next boundary's ``resolve_transition`` can iterate the
    entry through the T1–T6 spine (plan 07 §5.3, plan 09 T1). Accepts either
    a :class:`~ari.rqgm.prompt_records.PromptCandidate` or its
    ``prompt_evolution.jsonl`` record dict.

    Byte-identical to the ``registration_payload`` :func:`build_adoption_request`
    produces (single source of truth): checkpoint-scoped body under the
    write-once ``rqgm_prompts/<id>.md`` (plan 07 §5.6), ``prompt_hash`` /
    ``prompt_sha256`` reusing the one ``hash12``/sha256 scheme, and the
    envelope ``epoch_id`` / ``source_refs`` of the candidate record.
    """
    if isinstance(candidate, dict):
        candidate_id = str(candidate.get("candidate_id", ""))
        role = str(candidate.get("role", ""))
        prompt_hash = str(candidate.get("prompt_hash", ""))
        spec = dict(candidate.get("prompt_spec") or {})
        epoch_id = str(candidate.get("epoch_id", ""))
        record_id = str(candidate.get("record_id", ""))
    else:
        candidate_id = candidate.candidate_id
        role = candidate.role
        prompt_hash = candidate.prompt_hash
        spec = candidate.prompt_spec or {}
        epoch_id = candidate.epoch_id
        record_id = candidate.record_id
    return {
        "prompt_id": candidate_id,
        "role": role,
        "status": "candidate",
        "prompt_hash": prompt_hash,
        "prompt_sha256": str(spec.get("full_sha256", "")),
        "source": {
            "kind": "checkpoint_file",
            "path": f"rqgm_prompts/{candidate_id}.md",
        },
        "spec_ref": candidate_id,
        "epoch_id": epoch_id,
        "source_refs": [record_id] if record_id else [],
    }


def build_adoption_request(
    candidate: PromptCandidate, pipeline: CandidateValidationPipeline
) -> dict | None:
    """The Task 09 seam: an adoption request for the epoch-boundary
    transaction, or ``None`` unless EVERY stage record passed.

    This function never touches the registry — Task 09's
    RegistryTransitionEngine applies (and Task 04's kernel validates) the
    actual ``prompt_registered`` + ``prompt_status_change`` events.
    """
    if not pipeline.ready_for_adoption(candidate.candidate_id):
        return None
    validation_ids = [
        str(r.get("record_id", ""))
        for r in pipeline.stage_records(candidate.candidate_id)
        if r.get("passed")
    ]
    return {
        "request": "prompt_adoption",
        "candidate_id": candidate.candidate_id,
        "role": candidate.role,
        "prompt_hash": candidate.prompt_hash,
        "from_status": "candidate",
        "to_status": "probationary_active",
        "stages_passed": list(STAGES),
        "validation_record_ids": validation_ids,
        "registration_payload": candidate_registration_payload(candidate),
    }
