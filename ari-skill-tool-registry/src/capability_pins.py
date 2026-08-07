"""Resolve a capability contract digest from ARI's ontology, not from here.

A promotion that records `capability_ref` without `capability_contract_digest`
claims a capability but never says which contract it was verified against, so
nothing downstream can notice the contract moving underneath it. The pin has to
be the ontology's own digest -- a digest this package builds itself would agree
with nothing and could never go stale, which is indistinguishable from having no
pin at all.

This lives in its own module on purpose. Each promotion hashes its own source
file into `promotion_verifier_digest`, so putting the resolver in a shared
promotion module would move every provider's digest at once and invalidate
bundles that have nothing to do with the change.
"""

from __future__ import annotations

from pathlib import Path

from ari.public.capability_binding import load_capability_ontology
from providers import ProviderProtocolError


ONTOLOGY_PATH = (
    Path(__file__).resolve().parents[2]
    / "ari-core"
    / "config"
    / "capabilities"
    / "ontology.yaml"
)


def capability_contract_digest(capability_ref: str) -> str:
    """Return the ontology's digest for `capability_ref`, or refuse."""

    ontology = load_capability_ontology(ONTOLOGY_PATH)
    contract = ontology.contract(capability_ref)
    if contract is None:
        raise ProviderProtocolError(
            f"capability ontology does not declare {capability_ref}"
        )
    return contract.contract_digest


__all__ = ["ONTOLOGY_PATH", "capability_contract_digest"]
