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


def capability_contract(capability_ref: str):
    """Return the ontology's contract for `capability_ref`, or refuse."""

    ontology = load_capability_ontology(ONTOLOGY_PATH)
    contract = ontology.contract(capability_ref)
    if contract is None:
        raise ProviderProtocolError(
            f"capability ontology does not declare {capability_ref}"
        )
    return contract


def capability_contract_digest(capability_ref: str) -> str:
    """Return the ontology's digest for `capability_ref`, or refuse."""

    return capability_contract(capability_ref).contract_digest


def capability_environment_requirements(capability_ref: str) -> list[str]:
    """Return the features the contract demands of the substrate.

    A promotion that writes this list by hand keeps a second copy of something
    the contract already states, and the copies drift silently: the CUDA
    promotion still named `exclusive-node` and `slurm` long after both were
    retired from the contract, and nothing compared them.
    """

    return list(capability_contract(capability_ref).environment_requirements)


__all__ = [
    "ONTOLOGY_PATH",
    "capability_contract",
    "capability_contract_digest",
    "capability_environment_requirements",
]
