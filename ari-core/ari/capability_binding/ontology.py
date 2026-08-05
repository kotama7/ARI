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


def _contract(document: dict[str, Any]) -> CapabilityContractV1:
    payload = dict(document)
    payload.pop("contract_digest", None)
    return CapabilityContractV1.create(**payload)


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


__all__ = ["CapabilityOntology", "CapabilityOntologyError", "load_capability_ontology"]
