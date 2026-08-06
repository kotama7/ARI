"""Load and query the frozen Capability ontology and explicit aliases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ari.capability_binding.models import (
    CapabilityContractV1,
    CapabilityOntologySnapshotV1,
    LegacyCapabilityAliasV1,
)


class CapabilityOntologyError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityOntology:
    snapshot: CapabilityOntologySnapshotV1

    def contract(self, capability_ref: str) -> CapabilityContractV1 | None:
        return next(
            (item for item in self.snapshot.contracts if item.capability_ref == capability_ref),
            None,
        )

    def normalize(self, declared_ref: str) -> str | None:
        if self.contract(declared_ref) is not None:
            return declared_ref
        return next(
            (
                item.canonical_ref
                for item in self.snapshot.legacy_aliases
                if item.declared_ref == declared_ref
            ),
            None,
        )


@dataclass(frozen=True)
class ResourceDerivationV1:
    """One reviewed step from observed substrate facts to ontology vocabulary.

    A derivation cannot invent a fact.  It fires only when every requirement it
    names is already present, and what it emits carries the rationale that
    justified it, so a binding that depended on a derived resource class can be
    audited back to the sentence that allowed it.
    """

    emits: str
    kind: str
    requires_features: frozenset[str]
    requires_resource_types: frozenset[str]
    rationale: str


class ResourceDerivationError(ValueError):
    pass


def load_resource_derivations(path: str | Path) -> tuple[ResourceDerivationV1, ...]:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ResourceDerivationError("resource derivations must be a YAML mapping")
    rows: list[ResourceDerivationV1] = []
    for document in raw.get("derivations", ()) or ():
        kind = str(document.get("kind") or "")
        if kind not in {"feature", "resource_type"}:
            raise ResourceDerivationError(f"unknown derivation kind: {kind!r}")
        rationale = str(document.get("rationale") or "").strip()
        if not rationale:
            # A derivation without a reason is an alias, and an alias is the
            # thing this table exists to prevent.
            raise ResourceDerivationError(
                f"derivation for {document.get('emits')!r} states no rationale"
            )
        rows.append(
            ResourceDerivationV1(
                emits=str(document["emits"]),
                kind=kind,
                requires_features=frozenset(
                    str(item) for item in (document.get("requires_features") or ())
                ),
                requires_resource_types=frozenset(
                    str(item) for item in (document.get("requires_resource_types") or ())
                ),
                rationale=rationale,
            )
        )
    return tuple(rows)


def apply_resource_derivations(
    *,
    features: set[str],
    resource_types: set[str],
    derivations: tuple[ResourceDerivationV1, ...],
) -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    """Close the observed facts under the reviewed table and say which fired.

    Rows are applied to a fixpoint because one row may consume what another
    emitted.  The loop is bounded by the number of rows: each pass must add at
    least one name or it stops.
    """

    fired: list[str] = []
    for _ in range(len(derivations) + 1):
        added = False
        for row in derivations:
            target = features if row.kind == "feature" else resource_types
            if row.emits in target:
                continue
            if not row.requires_features <= features:
                continue
            if not row.requires_resource_types <= resource_types:
                continue
            target.add(row.emits)
            fired.append(f"{row.kind}:{row.emits}")
            added = True
        if not added:
            break
    return frozenset(features), frozenset(resource_types), tuple(sorted(set(fired)))


# Compatibility rules were a free-form string tuple: digest-bound, documented as
# what makes "a shared text label insufficient", and read by nothing. Every name
# below was inert. Closing the vocabulary means a contract can no longer invent a
# rule, and each name now has to say where it is checked -- including the ones
# that are not checked yet, which is at least visible instead of silent.
_COMPATIBILITY_RULES: dict[str, str] = {
    "measurement-envelope-v1": "core",
    # These have no core implementation. The shipped ontology declares no
    # semantic_inputs or semantic_outputs on any contract, so there is nothing
    # for a structural rule to compare against; populating them is separate work.
    "json-schema-structural-conformance": "unenforced",
    "artifact-result-v1": "unenforced",
    "async-handle-v1": "unenforced",
    "result-envelope-v1": "unenforced",
    # Checked by the Provider that supplies the capability, against its own
    # golden/replay evidence, not by the binder.
    "cuda-self-test-v1": "provider",
    "openroad-profile-result-v1": "provider",
    "qiskit-sampling-result-v1": "provider",
    "retrieval-record-v1": "provider",
}


def compatibility_rule_enforcement(rule: str) -> str:
    """Return where a reviewed compatibility rule is checked."""

    try:
        return _COMPATIBILITY_RULES[rule]
    except KeyError:
        raise CapabilityOntologyError(f"unknown compatibility rule: {rule!r}") from None


def _check_compatibility_rules(contract: CapabilityContractV1) -> None:
    for rule in contract.compatibility_rules:
        enforcement = compatibility_rule_enforcement(rule)
        if enforcement != "core":
            continue
        if rule == "measurement-envelope-v1" and not contract.nondeterminism_fields:
            # The rule says a measurement is only interpretable together with
            # the conditions it was taken under. A contract that claims it while
            # naming no conditions is not stating an envelope at all.
            raise CapabilityOntologyError(
                f"{contract.capability_ref} claims measurement-envelope-v1 but "
                "declares no nondeterminism_fields"
            )


def _contract(document: dict[str, Any]) -> CapabilityContractV1:
    payload = dict(document)
    payload.pop("contract_digest", None)
    contract = CapabilityContractV1.create(**payload)
    _check_compatibility_rules(contract)
    return contract


def load_capability_ontology(path: str | Path) -> CapabilityOntology:
    """Load a reviewed ontology file; no fuzzy aliasing is ever performed."""

    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise CapabilityOntologyError("ontology must be a YAML mapping")
    contracts = tuple(
        sorted(
            (_contract(item) for item in raw.get("contracts", [])),
            key=lambda item: item.capability_ref,
        )
    )
    alias_documents = list(raw.get("legacy_aliases", []))
    alias_path = source.with_name("legacy_aliases.yaml")
    if alias_path.is_file():
        alias_raw = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
        if not isinstance(alias_raw, dict):
            raise CapabilityOntologyError("legacy alias table must be a YAML mapping")
        alias_documents.extend(alias_raw.get("legacy_aliases", []))
    aliases = tuple(
        sorted(
            (LegacyCapabilityAliasV1.model_validate(item) for item in alias_documents),
            key=lambda item: item.declared_ref,
        )
    )
    snapshot = CapabilityOntologySnapshotV1.create(
        source_revision=str(raw.get("source_revision", "unknown")),
        property_vocabulary_version=str(
            raw.get("property_vocabulary_version", "ari.assurance-properties/v1")
        ),
        contracts=contracts,
        legacy_aliases=aliases,
    )
    return CapabilityOntology(snapshot)


__all__ = [
    "CapabilityOntology",
    "CapabilityOntologyError",
    "compatibility_rule_enforcement",
    "ResourceDerivationError",
    "ResourceDerivationV1",
    "apply_resource_derivations",
    "load_capability_ontology",
    "load_resource_derivations",
]
