"""Explicit, diagnostic-only legacy Provider terminology mapping."""

from __future__ import annotations

from types import MappingProxyType


LEGACY_PROVIDER_NAMES = MappingProxyType(
    {
        "Skill package": "Capability Provider package",
        "SkillManifestV1": "CapabilityProviderManifest",
        "SkillConfig": "CapabilityProviderConfig",
        "SkillConnection": "MCPProviderConnection",
        "SKILLS.lock": "Provider Lock",
    }
)


def canonical_provider_term(legacy_term: str) -> str | None:
    """Return only exact reviewed mappings; no fuzzy terminology fallback."""

    return LEGACY_PROVIDER_NAMES.get(legacy_term)


__all__ = ["LEGACY_PROVIDER_NAMES", "canonical_provider_term"]
