"""Semantic facade for executable Capability Providers.

The legacy ``Skill*`` objects remain the canonical serialized implementation.
These names are aliases, not replacement schemas or a second MCP runtime.
"""

from ari.providers.catalog import LoadedProviderCatalog, load_provider_catalog

from ari.providers.models import (
    CapabilityProviderConfig,
    CapabilityProviderIdentityV1,
    CapabilityProviderManifest,
    CapabilityProviderRegistrationReportV1,
    MCPProviderConnection,
    ProviderCatalogEntryV1,
    ProviderCatalogSnapshotV1,
    ProviderLock,
    derive_provider_identity,
)

__all__ = [
    "CapabilityProviderConfig",
    "CapabilityProviderIdentityV1",
    "CapabilityProviderManifest",
    "CapabilityProviderRegistrationReportV1",
    "MCPProviderConnection",
    "LoadedProviderCatalog",
    "ProviderCatalogEntryV1",
    "ProviderCatalogSnapshotV1",
    "ProviderLock",
    "derive_provider_identity",
    "load_provider_catalog",
]
