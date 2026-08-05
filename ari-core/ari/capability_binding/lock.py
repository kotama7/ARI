"""Persistence helpers for immutable Capability Binding locks."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from ari.capability_binding.models import CapabilityBindingLockV1
from ari.protocols.integrity import canonical_json_bytes


class CapabilityBindingLockError(RuntimeError):
    pass


def load_binding_lock(path: str | Path) -> CapabilityBindingLockV1:
    lock_path = Path(path)
    if lock_path.is_symlink():
        raise CapabilityBindingLockError("binding lock symbolic links are refused")
    try:
        return CapabilityBindingLockV1.model_validate_json(lock_path.read_bytes())
    except (OSError, ValidationError, ValueError) as exc:
        raise CapabilityBindingLockError(f"invalid binding lock: {exc}") from exc


def write_or_verify_binding_lock(
    path: str | Path, lock: CapabilityBindingLockV1
) -> CapabilityBindingLockV1:
    lock_path = Path(path)
    expected = canonical_json_bytes(lock) + b"\n"
    if lock_path.exists():
        if lock_path.is_symlink() or lock_path.read_bytes() != expected:
            raise CapabilityBindingLockError("immutable binding lock mismatch")
        return load_binding_lock(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".binding-lock-", dir=lock_path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, lock_path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return lock


__all__ = [
    "CapabilityBindingLockError",
    "load_binding_lock",
    "write_or_verify_binding_lock",
]
