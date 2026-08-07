"""Harness lock persistence and monotonic revision checks."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ari.assurance.models import (
    BaselineHarnessLockV1,
    HarnessLockRevisionV1,
)
from ari.protocols.integrity import canonical_json_bytes


def validate_harness_revision(
    *, baseline: BaselineHarnessLockV1, revision: HarnessLockRevisionV1
) -> None:
    if revision.baseline_lock_digest != baseline.lock_digest:
        raise ValueError("Harness revision refers to another baseline")
    old = {item.manifest_digest: item for item in baseline.harnesses}
    active = {item.manifest_digest: item for item in revision.active_harnesses}
    if not set(old).issubset(active):
        raise ValueError("Harness revision cannot remove a baseline Harness")
    for digest, item in old.items():
        if active[digest] != item:
            raise ValueError("Harness revision cannot replace pinned baseline bytes")
    for item in revision.added_or_strengthened_harnesses:
        previous = next(
            (old_item for old_item in baseline.harnesses if old_item.harness_id == item.harness_id),
            None,
        )
        if previous is None:
            continue
        if (
            item.dataset_digest != previous.dataset_digest
            or item.oracle_digest != previous.oracle_digest
            or item.driver_digest != previous.driver_digest
            or item.container_digest != previous.container_digest
            or item.tolerance_policy_digest != previous.tolerance_policy_digest
        ):
            raise ValueError("Harness strengthening cannot swap dataset/oracle/driver/container/tolerance")


def write_immutable_harness_lock(
    path: str | Path, lock: BaselineHarnessLockV1 | HarnessLockRevisionV1
) -> None:
    target = Path(path)
    expected = canonical_json_bytes(lock) + b"\n"
    if target.exists():
        if target.is_symlink() or target.read_bytes() != expected:
            raise ValueError("immutable Harness lock mismatch")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".harness-lock-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


__all__ = ["validate_harness_revision", "write_immutable_harness_lock"]
