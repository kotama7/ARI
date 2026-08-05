"""Digest-bound pipeline segment transactions and freshness reuse."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ari.manuscript.contracts import (
    ManuscriptArtifactRefV1,
    ManuscriptSegmentRecordV1,
)
from ari.manuscript.digest import canonical_digest, file_digest, safe_relative_path
from ari.manuscript.state import ManuscriptStateStore


_SEGMENT_ORDER = {"evidence": 0, "authoring": 1, "verification": 2}
_BOUND_INPUT_ENV = (
    "ARI_MANUSCRIPT_PROFILE_PATH",
    "ARI_MANUSCRIPT_CONTEXT_PATH",
    "ARI_MANUSCRIPT_READINESS_PATH",
    "ARI_MANUSCRIPT_BRIEFS_PATH",
    "ARI_MANUSCRIPT_BINDING_PATH",
)
_VOLATILE_NAMES = {
    ".pipeline_started",
    "cost_trace.jsonl",
    "prompt_trace.jsonl",
    "prompt_versions.json",
    "run_integrity.json",
}


def _run_id(checkpoint: Path) -> str:
    try:
        value = json.loads((checkpoint / "tree.json").read_text(encoding="utf-8"))
        run_id = str(value.get("run_id") or "").strip()
        if run_id:
            return run_id
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return checkpoint.name or "unknown-run"


def _source_attempt_id(checkpoint: Path) -> str:
    binding_path = os.environ.get("ARI_MANUSCRIPT_BINDING_PATH", "").strip()
    if binding_path:
        try:
            value = json.loads(Path(binding_path).read_text(encoding="utf-8"))
            attempt = str(value.get("attempt_id") or "").strip()
            if attempt:
                return attempt
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
    try:
        value = json.loads(
            (checkpoint / ".ari-manuscript" / "state.json").read_text(
                encoding="utf-8"
            )
        )
        attempt = str(value.get("attempt_id") or "").strip()
        if attempt:
            return attempt
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return "precompile"


def _is_inventory_path(relative: str) -> bool:
    path = Path(relative)
    if not path.parts:
        return False
    if path.parts[0] == ".ari-manuscript":
        return False
    if path.name in _VOLATILE_NAMES or path.name.startswith("workflow.segment-"):
        return False
    if any(part in {"logs", "backups", "__pycache__"} for part in path.parts):
        return False
    return True


def _inventory(checkpoint: Path) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for path in sorted(checkpoint.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = safe_relative_path(path.relative_to(checkpoint).as_posix())
        except (OSError, ValueError):
            continue
        if not _is_inventory_path(relative):
            continue
        try:
            out[relative] = file_digest(path)
        except OSError:
            continue
    return out


def _bound_inputs(checkpoint: Path) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for env_name in _BOUND_INPUT_ENV:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        path = Path(raw).resolve()
        try:
            relative = safe_relative_path(path.relative_to(checkpoint).as_posix())
        except (OSError, ValueError):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        try:
            out[relative] = file_digest(path)
        except OSError:
            continue
    return out


def _output_paths(stages: Iterable[dict[str, Any]], segments: tuple[str, ...], checkpoint: Path) -> set[str]:
    minimum = min(_SEGMENT_ORDER[item] for item in segments)
    paths: set[str] = set()
    for stage in stages:
        segment = str(stage.get("segment") or "")
        if _SEGMENT_ORDER.get(segment, -1) < minimum:
            continue
        outputs = stage.get("outputs") or {}
        if not isinstance(outputs, dict):
            continue
        for raw in outputs.values():
            if not isinstance(raw, str) or not raw.strip():
                continue
            expanded = raw.replace("{{checkpoint_dir}}", str(checkpoint)).replace(
                "{{ckpt}}", str(checkpoint)
            )
            path = Path(expanded)
            try:
                relative = safe_relative_path(path.resolve().relative_to(checkpoint).as_posix())
            except (OSError, ValueError):
                continue
            paths.add(relative)
    return paths


def _refs(
    inventory: dict[str, tuple[str, int]],
    *,
    kind: str,
) -> tuple[ManuscriptArtifactRefV1, ...]:
    return tuple(
        ManuscriptArtifactRefV1(
            item_id=f"{kind}-{canonical_digest(relative).removeprefix('sha256:')[:24]}",
            kind=kind,
            relative_path=relative,
            digest=digest,
            size_bytes=size,
            status="present",
        )
        for relative, (digest, size) in sorted(inventory.items())
    )


def _ref_map(refs: Iterable[ManuscriptArtifactRefV1]) -> dict[str, tuple[str, int]]:
    return {
        str(item.relative_path): (str(item.digest), int(item.size_bytes or 0))
        for item in refs
        if item.status == "present"
        and item.relative_path is not None
        and item.digest is not None
        and item.size_bytes is not None
    }


def _fresh_outputs(checkpoint: Path, record: ManuscriptSegmentRecordV1) -> bool:
    for item in record.output_artifacts:
        if item.relative_path is None:
            return False
        path = checkpoint / item.relative_path
        if item.status == "missing":
            if path.exists():
                return False
            continue
        if item.status != "present" or not path.is_file() or path.is_symlink():
            return False
        try:
            if file_digest(path) != (item.digest, item.size_bytes):
                return False
        except OSError:
            return False
    return True


def _read_records(checkpoint: Path) -> list[ManuscriptSegmentRecordV1]:
    root = checkpoint / ".ari-manuscript" / "segments"
    if not root.is_dir():
        return []
    records: list[ManuscriptSegmentRecordV1] = []
    for path in sorted(root.glob("*.json")):
        try:
            records.append(
                ManuscriptSegmentRecordV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        except (OSError, ValueError):
            # A malformed immutable transaction is not reusable.  Enforce will
            # execute again and preserve the bad file for operator inspection.
            continue
    return records


@dataclass
class SegmentExecution:
    checkpoint: Path
    stages: tuple[dict[str, Any], ...]
    segments: tuple[str, ...]
    workflow_digest: str
    enabled_stages: tuple[str, ...]
    disabled_stages: tuple[str, ...]
    excluded_output_paths: set[str]
    before: dict[str, tuple[str, int]]
    reusable_record: ManuscriptSegmentRecordV1 | None = None

    @property
    def reusable(self) -> bool:
        return self.reusable_record is not None

    def finish(self, *, status: str, blocking_reason: str = "") -> ManuscriptSegmentRecordV1:
        after = _inventory(self.checkpoint)
        after.update(_bound_inputs(self.checkpoint))
        before = dict(self.before)
        before.update(_bound_inputs(self.checkpoint))
        logical_inputs = {
            path: value
            for path, value in before.items()
            if path not in self.excluded_output_paths
        }
        changed_paths = sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        logical_inputs = {
            path: value
            for path, value in before.items()
            if path not in self.excluded_output_paths and path not in changed_paths
        }
        output_refs: list[ManuscriptArtifactRefV1] = []
        for relative in changed_paths:
            current = after.get(relative)
            if current is None:
                output_refs.append(
                    ManuscriptArtifactRefV1(
                        item_id=(
                            "segment-output-"
                            + canonical_digest(relative).removeprefix("sha256:")[:24]
                        ),
                        kind="segment-output",
                        relative_path=relative,
                        status="missing",
                        metadata={"previous_digest": before.get(relative, (None, 0))[0]},
                    )
                )
            else:
                output_refs.append(
                    ManuscriptArtifactRefV1(
                        item_id=(
                            "segment-output-"
                            + canonical_digest(relative).removeprefix("sha256:")[:24]
                        ),
                        kind="segment-output",
                        relative_path=relative,
                        digest=current[0],
                        size_bytes=current[1],
                        status="present",
                        metadata={
                            "previous_digest": before.get(relative, (None, 0))[0]
                        },
                    )
                )
        input_refs = _refs(logical_inputs, kind="segment-input")
        invocation_id = "segment-" + canonical_digest(
            {
                "segments": self.segments,
                "workflow_digest": self.workflow_digest,
                "enabled_stages": self.enabled_stages,
                "disabled_stages": self.disabled_stages,
                "input_artifacts": [item.model_dump(mode="json") for item in input_refs],
            }
        ).removeprefix("sha256:")[:32]
        previous = [
            item
            for item in _read_records(self.checkpoint)
            if item.invocation_id == invocation_id
        ]
        record = ManuscriptSegmentRecordV1.create(
            run_id=_run_id(self.checkpoint),
            source_attempt_id=_source_attempt_id(self.checkpoint),
            invocation_id=invocation_id,
            execution_index=len(previous),
            segments=self.segments,
            workflow_digest=self.workflow_digest,
            enabled_stages=self.enabled_stages,
            disabled_stages=self.disabled_stages,
            input_artifacts=input_refs,
            output_artifacts=tuple(output_refs),
            status=status,
            blocking_reason=blocking_reason,
        )
        ManuscriptStateStore(self.checkpoint).write_once(
            f"segments/{invocation_id}-{record.execution_index:03d}.json",
            record,
        )
        return record


def prepare_segment_execution(
    checkpoint_dir: str | Path,
    workflow_path: str | Path,
    stages: Iterable[dict[str, Any]],
    segments: Iterable[str],
) -> SegmentExecution:
    checkpoint = Path(checkpoint_dir).resolve()
    stage_tuple = tuple(dict(item) for item in stages)
    try:
        import yaml

        document = yaml.safe_load(Path(workflow_path).read_text(encoding="utf-8")) or {}
        raw_stages = document.get("pipeline") or []
        if isinstance(raw_stages, list) and all(isinstance(item, dict) for item in raw_stages):
            stage_tuple = tuple(dict(item) for item in raw_stages)
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    segment_tuple = tuple(sorted(set(segments), key=_SEGMENT_ORDER.__getitem__))
    workflow_digest = file_digest(Path(workflow_path))[0]
    enabled = tuple(
        str(item.get("stage"))
        for item in stage_tuple
        if item.get("enabled", True) and item.get("segment") in segment_tuple
    )
    disabled = tuple(
        str(item.get("stage"))
        for item in stage_tuple
        if not item.get("enabled", True) or item.get("segment") not in segment_tuple
    )
    excluded = _output_paths(stage_tuple, segment_tuple, checkpoint)
    before = _inventory(checkpoint)
    before.update(_bound_inputs(checkpoint))
    logical = {path: value for path, value in before.items() if path not in excluded}

    reusable = None
    for record in reversed(_read_records(checkpoint)):
        recorded_outputs = {
            str(item.relative_path)
            for item in record.output_artifacts
            if item.relative_path is not None
        }
        candidate_inputs = {
            path: value for path, value in logical.items() if path not in recorded_outputs
        }
        if (
            record.status == "completed"
            and record.segments == segment_tuple
            and record.workflow_digest == workflow_digest
            and record.enabled_stages == enabled
            and record.disabled_stages == disabled
            and _ref_map(record.input_artifacts) == candidate_inputs
            and _fresh_outputs(checkpoint, record)
        ):
            reusable = record
            break
    return SegmentExecution(
        checkpoint=checkpoint,
        stages=stage_tuple,
        segments=segment_tuple,
        workflow_digest=workflow_digest,
        enabled_stages=enabled,
        disabled_stages=disabled,
        excluded_output_paths=excluded,
        before=before,
        reusable_record=reusable,
    )


__all__ = ["SegmentExecution", "prepare_segment_execution"]
