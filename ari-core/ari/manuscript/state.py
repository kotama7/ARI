"""Immutable attempt persistence and append-only manuscript state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ari.manuscript.contracts import ManuscriptTransitionV1
from ari.manuscript.digest import (
    canonical_json_bytes,
    path_has_symlink_component,
    safe_relative_path,
)


ROOT_NAME = ".ari-manuscript"

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "absent": frozenset({"source_bound"}),
    # A different digest-derived attempt may supersede an interrupted attempt.
    # Keeping that rebind as an explicit transition makes stale recovery
    # observable without mutating or deleting the prior attempt directory.
    "source_bound": frozenset({"source_bound", "compiled", "blocked_unavailable"}),
    "compiled": frozenset({"source_bound", "assessed", "blocked_unavailable"}),
    "assessed": frozenset({
        "source_bound", "ready", "ready_with_disclosures", "repair_pending",
        "blocked_unavailable"
    }),
    "ready": frozenset({"authoring", "publication_blocked", "source_bound"}),
    "ready_with_disclosures": frozenset({"authoring", "publication_blocked", "source_bound"}),
    "repair_pending": frozenset({"repairing", "authoring", "blocked_unavailable"}),
    "repairing": frozenset({"source_bound", "repair_pending", "blocked_unavailable"}),
    "authoring": frozenset({"authored", "publication_blocked", "source_bound"}),
    "authored": frozenset({"publication_blocked", "finalized", "source_bound"}),
    "publication_blocked": frozenset({"source_bound", "repair_pending"}),
    "blocked_unavailable": frozenset({"source_bound", "repair_pending", "authoring"}),
    "finalized": frozenset({"source_bound"}),
}


def attempt_id(snapshot_digest: str, profile_digest: str) -> str:
    return f"mca-{snapshot_digest[7:23]}-{profile_digest[7:15]}"


def _json_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


class ManuscriptStateStore:
    def __init__(self, checkpoint_dir: str | Path):
        self.checkpoint_dir = Path(checkpoint_dir).resolve()
        self.root = self.checkpoint_dir / ROOT_NAME
        self.attempts_root = self.root / "attempts"
        self.state_path = self.root / "state.json"
        self.transitions_path = self.root / "transitions.jsonl"

    def attempt_dir(self, value: str) -> Path:
        if not value.startswith("mca-") or "/" in value or ".." in value:
            raise ValueError("invalid manuscript attempt ID")
        return self.attempts_root / value

    def _assert_safe_namespace(self, path: Path | None = None) -> None:
        if self.root.is_symlink():
            raise ValueError("manuscript namespace cannot be a symlink")
        if path is not None and path_has_symlink_component(self.root, path):
            raise ValueError("manuscript artifact path traverses a symlink")

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    def write_once(self, relative_path: str, value: Any) -> Path:
        safe_relative_path(relative_path)
        path = self.root / relative_path
        self._assert_safe_namespace(path)
        payload = _json_bytes(value)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(f"immutable manuscript artifact already differs: {relative_path}")
            return path
        self._atomic_write(path, payload)
        return path

    def write_attempt_artifact(self, attempt: str, filename: str, value: Any) -> Path:
        if "/" in filename or ".." in filename:
            raise ValueError("invalid manuscript artifact filename")
        return self.write_once(f"attempts/{attempt}/{filename}", value)

    def read_state(self) -> dict[str, Any]:
        self._assert_safe_namespace()
        transitions = self._read_transitions()
        if not transitions:
            if self.state_path.exists() or self.state_path.is_symlink():
                raise ValueError("manuscript state exists without a transition chain")
            return {"schema_version": "ari.manuscript-state/v1", "state": "absent"}

        tail = transitions[-1]
        expected = {
            "schema_version": "ari.manuscript-state/v1",
            "run_id": tail.run_id,
            "attempt_id": tail.attempt_id,
            "state": tail.to_state,
            "last_transition_digest": tail.transition_digest,
            "sequence": tail.sequence,
            "artifact_digests": list(tail.artifact_digests),
        }
        if not self.state_path.is_file() or self.state_path.is_symlink():
            # The transition append is fsync'd before its mutable projection is
            # replaced. Recover the only safe crash window from the immutable
            # chain instead of inventing state.
            if self.state_path.is_symlink():
                raise ValueError("manuscript state projection cannot be a symlink")
            self._atomic_write(self.state_path, _json_bytes(expected))
            return expected
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manuscript state projection is unreadable") from exc
        if not isinstance(value, dict):
            raise ValueError("manuscript state is not an object")
        if value == expected:
            return value

        # Recover only the single-transition crash interval. Any other drift is
        # an external mutation or non-atomic writer and must fail closed.
        if len(transitions) >= 2:
            prior = transitions[-2]
            prior_projection = {
                "schema_version": "ari.manuscript-state/v1",
                "run_id": prior.run_id,
                "attempt_id": prior.attempt_id,
                "state": prior.to_state,
                "last_transition_digest": prior.transition_digest,
                "sequence": prior.sequence,
                "artifact_digests": list(prior.artifact_digests),
            }
            if value == prior_projection:
                self._atomic_write(self.state_path, _json_bytes(expected))
                return expected
        raise ValueError("manuscript state projection differs from transition chain")

    def _read_transitions(self) -> list[ManuscriptTransitionV1]:
        self._assert_safe_namespace(self.transitions_path)
        if not self.transitions_path.is_file():
            return []
        if self.transitions_path.is_symlink():
            raise ValueError("manuscript transition log cannot be a symlink")
        out: list[ManuscriptTransitionV1] = []
        for line in self.transitions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            out.append(ManuscriptTransitionV1.model_validate_json(line))
        for index, item in enumerate(out):
            if item.sequence != index:
                raise ValueError("manuscript transition sequence is not contiguous")
            if index and item.parent_transition_digest != out[index - 1].transition_digest:
                raise ValueError("manuscript transition hash chain is broken")
        return out

    def transition(
        self,
        *,
        run_id: str,
        attempt: str,
        to_state: str,
        reason_code: str,
        artifact_digests: tuple[str, ...] = (),
    ) -> ManuscriptTransitionV1:
        self._assert_safe_namespace()
        transitions = self._read_transitions()
        current = transitions[-1].to_state if transitions else "absent"
        if transitions and current == to_state and transitions[-1].attempt_id == attempt:
            return transitions[-1]
        if to_state not in LEGAL_TRANSITIONS.get(current, frozenset()):
            raise ValueError(f"illegal manuscript transition: {current} -> {to_state}")
        record = ManuscriptTransitionV1.create(
            sequence=len(transitions),
            run_id=run_id,
            attempt_id=attempt,
            from_state=current,
            to_state=to_state,
            reason_code=reason_code,
            artifact_digests=artifact_digests,
            parent_transition_digest=(
                transitions[-1].transition_digest if transitions else None
            ),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.transitions_path.open("ab") as handle:
            handle.write(canonical_json_bytes(record.model_dump(mode="json")) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._atomic_write(
            self.state_path,
            _json_bytes({
                "schema_version": "ari.manuscript-state/v1",
                "run_id": run_id,
                "attempt_id": attempt,
                "state": to_state,
                "last_transition_digest": record.transition_digest,
                "sequence": record.sequence,
                "artifact_digests": list(artifact_digests),
            }),
        )
        return record


__all__ = [
    "LEGAL_TRANSITIONS",
    "ManuscriptStateStore",
    "ROOT_NAME",
    "attempt_id",
]
