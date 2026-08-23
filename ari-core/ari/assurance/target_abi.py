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
    #: Symbols the verifier resolves by name. Declaring conformance to an
    #: interface contract is a CLAIM about the artifact; unchecked, it is a
    #: claim the declaring side has no basis for. Observed: a candidate built
    #: from a problem whose scaffolding exports `gemm` was declared conformant
    #: to `gemm-c-abi/v1`, whose verifier resolves `ari_gemm_f32`/`ari_gemm_f64`
    #: -- 33 of 33 cases failed with "missing symbol" and every error was
    #: exactly 0.0, because the kernel was never entered.
    exported_symbols: tuple[str, ...] = ()


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


def _symbol_list(raw: object, source: Path) -> tuple[str, ...]:
    """Symbols the verifier resolves by name, in declaration order."""
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise TargetABIRegistryError(f"{source}: exported_symbols must be a list")
    out = tuple(str(item).strip() for item in raw if str(item).strip())
    if len(out) != len(set(out)):
        raise TargetABIRegistryError(f"{source}: exported_symbols must be unique")
    return out


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
            "language", "subject_type", "target_kind", "exported_symbols",
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
            exported_symbols=_symbol_list(raw.get("exported_symbols"), source),
        )
    return identities


def abi_identity(family: str) -> NativeABIIdentityV1 | None:
    return _load_identities().get(str(family))


#: What a candidate submitted against a PROBLEM's own contract header is. Not an
#: ABI record, because it is not one ABI: it is "whatever this problem's header
#: says", and the problem pins those bytes itself.
PROBLEM_SUBMISSION_TARGET_KIND = "benchmark-submission"


def problem_target_kind(entry_point: str, family: str) -> str:
    """The kind of artifact this problem's candidates ARE.

    THE DEFECT THIS EXISTS FOR. ``property_vocabulary.yaml`` stamps every
    correctness atom with one target kind per property -- ``shared-library`` for
    ``numerical-equivalence`` and ``interface-conformance`` -- which was true
    while the only correctness harnesses were the three ARI-native ones. A
    correctness harness over a problem's own C contract verifies a submission
    instead, so the resolver's ``_coverage`` rejected it on target kind alone:
    measured, the atom kind ``shared-library`` selected it 0 times and
    ``benchmark-submission`` selected it once. It would have been registered,
    promoted and never chosen -- the same "nothing happens" failure this
    subsystem keeps producing.

    Derived from the two pinned facts ``declare_target`` also reads -- the
    problem's declared entry point and its family's ABI record -- so the
    resolution side and the declaration side cannot come to disagree about what
    a run's artifacts are. A problem whose entry point IS one of the family's
    ABI symbols is verified as that shared library; anything else keeps its own
    header and is a submission.
    """
    identity = abi_identity(family)
    if identity is not None and str(entry_point) in identity.exported_symbols:
        return identity.target_kind
    return PROBLEM_SUBMISSION_TARGET_KIND


__all__ = [
    "NativeABIIdentityV1",
    "PROBLEM_SUBMISSION_TARGET_KIND",
    "TargetABIRegistryError",
    "abi_identity",
    "problem_target_kind",
    "target_abi_root",
]
