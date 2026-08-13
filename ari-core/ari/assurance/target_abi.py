"""Data-driven ABI identities used to author Harness target declarations.

The identity cannot be derived from the Harness that will judge the target:
that would make both sides agree by construction.  It also cannot live on the
native family classes, because those files are covered by the registered driver
digest.  Independent YAML records therefore describe the candidate side of the
contract.  Adding a family adds one record; core never enumerates task names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class NativeABIIdentityV1:
    """What a Harness must be told about a candidate before it will judge it."""

    interface_contract: str
    dtype: str
    language: str = "c"
    subject_type: str = "program"
    target_kind: str = "shared-library"


class TargetABIRegistryError(RuntimeError):
    """An ABI identity record is malformed or duplicates another family."""


def target_abi_root() -> Path:
    configured = os.environ.get("ARI_TARGET_ABI_REGISTRY")
    if configured:
        return Path(configured)
    return (Path(__file__).resolve().parents[2]
            / "config" / "harnesses" / "target_abis")


def _required_text(raw: dict, key: str, source: Path) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise TargetABIRegistryError(f"{source}: {key} must not be blank")
    return value


def _load_identities() -> dict[str, NativeABIIdentityV1]:
    root = target_abi_root()
    if not root.is_dir():
        return {}
    identities: dict[str, NativeABIIdentityV1] = {}
    for source in sorted(root.glob("*.yaml")):
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise TargetABIRegistryError(
                f"ABI identity {source} could not be read: {exc}") from exc
        if not isinstance(raw, dict):
            raise TargetABIRegistryError(f"{source}: identity must be a mapping")
        allowed = {
            "schema_version", "family", "interface_contract", "dtype",
            "language", "subject_type", "target_kind",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise TargetABIRegistryError(
                f"{source}: unknown target ABI identity fields: {unknown}")
        if raw.get("schema_version") != "ari.target-abi-identity/v1":
            raise TargetABIRegistryError(
                f"{source}: unsupported target ABI identity schema")
        family = _required_text(raw, "family", source)
        if family in identities:
            raise TargetABIRegistryError(
                f"two target ABI identities are registered for {family!r}")
        identities[family] = NativeABIIdentityV1(
            interface_contract=_required_text(raw, "interface_contract", source),
            dtype=_required_text(raw, "dtype", source),
            language=_required_text(raw, "language", source),
            subject_type=_required_text(raw, "subject_type", source),
            target_kind=_required_text(raw, "target_kind", source),
        )
    return identities


def abi_identity(family: str) -> NativeABIIdentityV1 | None:
    return _load_identities().get(str(family))


__all__ = [
    "NativeABIIdentityV1",
    "TargetABIRegistryError",
    "abi_identity",
    "target_abi_root",
]
