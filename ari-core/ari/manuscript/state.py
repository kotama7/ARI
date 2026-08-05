"""Immutable attempt persistence and append-only manuscript state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ari.manuscript.contracts import ManuscriptTransitionV1
from ari.manuscript.digest import canonical_json_bytes


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

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    def write_once(self, relative_path: str, value: Any) -> Path:
        path = self.root / relative_path
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
        if not self.state_path.is_file():
            return {"schema_version": "ari.manuscript-state/v1", "state": "absent"}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("manuscript state is not an object")
        return value

    def _read_transitions(self) -> list[ManuscriptTransitionV1]:
        if not self.transitions_path.is_file():
            return []
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
