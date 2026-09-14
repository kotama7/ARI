"""Stable public read/validate Provider terminology facade."""

from ari.providers.catalog import (
    build_provider_catalog_snapshot,
    describe_provider,
    search_providers,
)
from ari.providers.compatibility import LEGACY_PROVIDER_NAMES, canonical_provider_term
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
    "LEGACY_PROVIDER_NAMES",
    "MCPProviderConnection",
    "ProviderCatalogEntryV1",
    "ProviderCatalogSnapshotV1",
    "ProviderLock",
    "build_provider_catalog_snapshot",
    "canonical_provider_term",
    "derive_provider_identity",
    "describe_provider",
    "search_providers",
]
