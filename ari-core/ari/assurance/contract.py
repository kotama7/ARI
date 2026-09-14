"""Mint-once Verification Contract construction from fixed requirements."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ari.assurance.models import (
    VerificationContractV1,
    VerificationRequirementV1,
    VerificationScopeV1,
)
from ari.protocols.integrity import canonical_digest


class PropertyVocabulary(dict):
    """The property->methods mapping, plus what each property is verified ON.

    A ``dict`` subclass so every existing reader keeps working: membership, item
    access and ``sorted()`` over the keys are unchanged. ``target_kinds`` is
    additive and partial -- a property with no entry keeps the caller's
    parameter, because only two of them are settled by evidence and this is not
    a place to guess the rest.
    """

    def __init__(self, properties, target_kinds=None, correctness_properties=None):
        super().__init__(properties)
        self.target_kinds: dict[str, str] = dict(target_kinds or {})
        #: What "correctness is required" asks for. Unset keeps the single
        #: hardcoded property this replaced.
        self.correctness_properties: tuple[str, ...] = tuple(
            correctness_properties or ("artifact-correctness",))

    def target_kind_for(self, property_id: str, default: str) -> str:
        return self.target_kinds.get(property_id, default)


def load_tolerance_policy(path: str | Path) -> tuple[str, str]:
    """Resolve a named tolerance policy file to ``(ref, digest)``.

    The digest is sha256 over the file's BYTES, because that is what a Harness
    manifest pins for the same policy. Hashing the parsed document instead
    yields a different digest for the identical policy, and coverage compares
    these two digests for equality -- so the mismatch would not be an error,
    it would silently cover nothing.
    """
    file = Path(path)
    raw = file.read_bytes()
    document = yaml.safe_load(raw.decode("utf-8")) or {}
    policy_id = str(document.get("id") or "").strip()
    if not policy_id:
        raise ValueError(f"tolerance policy {file.name} declares no id")
    return policy_id, "sha256:" + hashlib.sha256(raw).hexdigest()


def load_property_vocabulary(path: str | Path) -> tuple[PropertyVocabulary, str]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    properties = {
        str(property_id): tuple(sorted(str(method) for method in methods))
        for property_id, methods in dict(raw.get("properties") or {}).items()
    }
    if any(not methods for methods in properties.values()):
        raise ValueError("every assurance property requires a default method")
    target_kinds = {str(k): str(v)
                    for k, v in dict(raw.get("target_kinds") or {}).items()}
    unknown = sorted(set(target_kinds) - set(properties))
    if unknown:
        # A target kind for a property that does not exist is a typo that would
        # otherwise sit inert and be read as a decision.
        raise ValueError(
            f"target_kinds names properties the vocabulary does not define: {unknown}")
    correctness = tuple(str(p) for p in (raw.get("correctness_properties") or ()))
    missing = sorted(set(correctness) - set(properties))
    if missing:
        raise ValueError(
            f"correctness_properties names properties the vocabulary does not "
            f"define: {missing}")
    return (PropertyVocabulary(properties, target_kinds, correctness or None),
            canonical_digest(raw))


def _correctness_properties(vocabulary) -> tuple[str, ...]:
    """The properties a correctness requirement is established BY.

    THE DEFECT THIS FIXES. One hardcoded property, ``artifact-correctness``, was
    emitted whenever a research contract required correctness -- and no shipped
    manifest declares it. Measured against the real catalog:
    ``artifact-correctness`` selected 0 manifests, ``numerical-equivalence``
    selected 1. So every correctness obligation resolved to nothing, silently.

    Declared in the vocabulary because which concrete properties establish
    correctness is a statement about the science, not about this function.
    """
    return tuple(getattr(vocabulary, "correctness_properties",
                         ("artifact-correctness",)))


def _artifact_kind_for(vocabulary, property_id: str, artifact_target_kind: str | None,
                       fallback: str) -> str:
    """The artifact kind, when the run knows it, for the properties ABOUT it.

    THE DEFECT THIS FIXES. ``target_kinds`` in the vocabulary is one scalar per
    property, and its own comment records why: the three registered correctness
    harnesses all verify a ``shared-library``, so one value was the whole truth.
    A correctness harness over a pinned problem's own C contract verifies a
    submission, and the same property is now honestly verified on two different
    kinds of artifact. Measured against the shipped catalog with the new
    manifest present: an atom stamped ``shared-library`` selected it 0 times and
    one stamped ``benchmark-submission`` selected it once, so it would have been
    registered, promoted, and never chosen.

    Only the CORRECTNESS properties take the override, because only those are
    claims about the artifact under test. A run that does not name a pinned
    problem passes nothing here and every atom is stamped exactly as before.
    """
    if artifact_target_kind and property_id in _correctness_properties(vocabulary):
        return artifact_target_kind
    return _target_kind_for(vocabulary, property_id, fallback)


def _target_kind_for(vocabulary, property_id: str, fallback: str) -> str:
    """What this property is verified ON, or the caller's value.

    THE DEFECT THIS FIXES. Every requirement in a run used to carry the caller's
    one ``target_kind``. A run carries a correctness obligation over a compiled
    library and a performance obligation over a kernel submitted to a benchmark;
    those are different kinds of thing, and ``resolver`` requires the atom's kind
    to be one the manifest declares. One value for all of them means at most one
    can resolve -- and with the default of ``workspace-artifact``, none did: the
    three registered correctness harnesses declare ``shared-library``.

    Partial on purpose. Only the properties whose kind is settled by evidence
    appear in the vocabulary; every other property behaves exactly as before.
    """
    getter = getattr(vocabulary, "target_kind_for", None)
    return getter(property_id, fallback) if getter else fallback


def build_verification_contract(
    *,
    run_id: str,
    research_contract,
    knowledge_obligations: tuple,
    property_vocabulary: dict[str, tuple[str, ...]],
    property_vocabulary_digest: str,
    target_kind: str = "workspace-artifact",
    tolerance_policy: tuple[str, str] | None = None,
    artifact_target_kind: str | None = None,
) -> VerificationContractV1:
    """Union Research Contract correctness and Knowledge obligations.

    Knowledge content supplies properties/methods only.  It cannot name a
    Harness, delete the Research Contract baseline, or relax its tolerance.

    ``tolerance_policy`` is the ``(ref, digest)`` of a named policy, supplied by
    the run the same way ``property_vocabulary`` is. Without it the correctness
    requirements below are stamped with the digest of the Research Contract's
    own ``{absolute, relative}`` pair, and that pair can never equal what a
    Harness pins: a Harness names a symbolic policy whose limits depend on the
    accumulation length and the unit roundoff, and pins the sha256 of that
    policy FILE. Two different kinds of object were being compared for string
    equality, so a governed run resolved zero Harness coverage no matter what
    numbers the Research Contract carried. The fallback is kept so callers that
    pass no policy behave exactly as before.

    ``artifact_target_kind`` is what the run's candidates ARE, when the run names
    a pinned problem and therefore knows. It overrides the vocabulary's
    per-property target kind for the correctness properties only; without it
    every requirement is stamped exactly as before. See ``_artifact_kind_for``.
    """

    metric_tolerance_digest = canonical_digest(
        research_contract.metric_contract.tolerance.model_dump(mode="json")
    )
    metric_tolerance_ref = (
        "research-contract:" + research_contract.metric_contract.contract_digest
    )
    if tolerance_policy is not None:
        tolerance_ref, tolerance_digest = tolerance_policy
    else:
        tolerance_ref, tolerance_digest = metric_tolerance_ref, metric_tolerance_digest
    requirements: list[VerificationRequirementV1] = []
    metric = research_contract.metric_contract
    for property_id in _correctness_properties(property_vocabulary):
        if not metric.correctness_required:
            break
        if property_id not in property_vocabulary:
            raise ValueError(
                f"correctness requires {property_id!r}, which the property "
                f"vocabulary does not define")
        methods = property_vocabulary[property_id]
        requirements.append(
            VerificationRequirementV1.create(
                property_id=property_id,
                target_kind=_artifact_kind_for(property_vocabulary, property_id,
                                               artifact_target_kind, target_kind),
                required_methods=methods,
                required_tier="screen",
                failure_policy="exclude-from-scientific-frontier",
                scope=VerificationScopeV1(values={}),
                tolerance_policy_ref=tolerance_ref,
                tolerance_policy_digest=tolerance_digest,
                source_requirement_refs=(
                    "research-contract:" + research_contract.contract_digest,
                ),
            )
        )
    obligation_refs: list[str] = []
    for obligation in knowledge_obligations:
        if obligation.property_id not in property_vocabulary:
            raise ValueError(
                f"unknown Knowledge evaluation property: {obligation.property_id}"
            )
        methods = obligation.required_methods or property_vocabulary[
            obligation.property_id
        ]
        source = "knowledge:" + str(obligation.source_skill_digest)
        obligation_refs.append(source)
        requirements.append(
            VerificationRequirementV1.create(
                property_id=obligation.property_id,
                # A Knowledge obligation over a correctness property is a claim
                # about the same artifact, so it takes the same override; every
                # other property keeps the vocabulary's answer.
                target_kind=_artifact_kind_for(property_vocabulary,
                                               obligation.property_id,
                                               artifact_target_kind, target_kind),
                required_methods=methods,
                required_tier=obligation.required_tier,
                failure_policy=(
                    "block-publication"
                    if obligation.required_tier == "certify"
                    else "exclude-from-scientific-frontier"
                ),
                scope=VerificationScopeV1(values=obligation.scope),
                tolerance_policy_ref=tolerance_ref,
                tolerance_policy_digest=tolerance_digest,
                source_requirement_refs=(source,),
            )
        )

    # Merge exact property/scope/tier requirements by unioning methods and
    # provenance; this can only add obligations.
    merged: dict[tuple, VerificationRequirementV1] = {}
    for requirement in requirements:
        key = (
            requirement.property_id,
            requirement.target_kind,
            requirement.required_tier,
            canonical_digest(requirement.scope),
            requirement.tolerance_policy_digest,
        )
        previous = merged.get(key)
        if previous is None:
            merged[key] = requirement
            continue
        merged[key] = VerificationRequirementV1.create(
            **previous.model_dump(
                mode="python",
                exclude={
                    "requirement_digest",
                    "required_methods",
                    "source_requirement_refs",
                },
            ),
            required_methods=tuple(
                sorted(set(previous.required_methods) | set(requirement.required_methods))
            ),
            source_requirement_refs=tuple(
                sorted(
                    set(previous.source_requirement_refs)
                    | set(requirement.source_requirement_refs)
                )
            ),
        )
    human_identity = None
    provenance = metric.formula_provenance
    if provenance.source == "human-admission":
        human_identity = provenance.source_digest
    return VerificationContractV1.create(
        run_id=run_id,
        research_contract_digest=research_contract.contract_digest,
        requirements=tuple(
            sorted(merged.values(), key=lambda item: item.requirement_digest)
        ),
        baseline_knowledge_obligation_refs=tuple(sorted(set(obligation_refs))),
        admission_confidence=metric.confidence,
        human_review_identity=human_identity,
        property_vocabulary_digest=property_vocabulary_digest,
    )


__all__ = ["build_verification_contract", "load_property_vocabulary"]
