"""Read-only compatibility view for checkpoints created before Skill locks.

Legacy layouts remain replayable data, but they are not runtime registration
inputs.  This reader resolves the historical tree/paper locations into one
typed snapshot, records the digest of every consumed source, and never mutates
the checkpoint.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


LEGACY_CHECKPOINT_VIEW_V1 = "ari.legacy-checkpoint-view/v1"
_MAX_MIGRATION_FILE_BYTES = 10_000_000


class LegacyCheckpointError(ValueError):
    """Raised when a legacy checkpoint cannot be read safely and completely."""


class LegacyCheckpointViewV1(BaseModel):
    """Normalized, immutable view used by migration and replay tooling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.legacy-checkpoint-view/v1"] = (
        LEGACY_CHECKPOINT_VIEW_V1
    )
    checkpoint_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    tree_layout: Literal["tree.json", "nodes_tree.json", "node_*/tree.json"]
    tree: dict[str, Any]
    results: dict[str, Any] = Field(default_factory=dict)
    paper_source: str = ""
    paper_relative_path: str | None = None
    replay_inputs: dict[str, Any] = Field(default_factory=dict)
    source_digests: dict[str, str]


def _read_bytes(root: Path, path: Path) -> bytes:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LegacyCheckpointError(f"cannot resolve {path}: {exc}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise LegacyCheckpointError(f"checkpoint source escapes root: {path}") from exc
    if not resolved.is_file():
        raise LegacyCheckpointError(f"checkpoint source is not a file: {path}")
    size = resolved.stat().st_size
    if size > _MAX_MIGRATION_FILE_BYTES:
        raise LegacyCheckpointError(
            f"checkpoint source exceeds {_MAX_MIGRATION_FILE_BYTES} bytes: {path}"
        )
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise LegacyCheckpointError(f"cannot read {path}: {exc}") from exc


def _read_text(root: Path, path: Path) -> tuple[str, str]:
    payload = _read_bytes(root, path)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LegacyCheckpointError(f"checkpoint source is not UTF-8: {path}") from exc
    return text, f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _read_json(root: Path, path: Path) -> tuple[dict[str, Any], str]:
    text, digest = _read_text(root, path)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LegacyCheckpointError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacyCheckpointError(f"JSON root must be an object: {path}")
    return value, digest


def _tree_source(root: Path) -> tuple[Path, str]:
    for name in ("tree.json", "nodes_tree.json"):
        candidate = root / name
        if candidate.is_file():
            return candidate, name
    candidates = sorted(
        (path for path in root.glob("node_*/tree.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.as_posix()),
        reverse=True,
    )
    for candidate in candidates:
        if candidate.stat().st_size > 2:
            return candidate, "node_*/tree.json"
    raise LegacyCheckpointError(f"no legacy node tree found under {root}")


def load_legacy_checkpoint(path: str | Path) -> LegacyCheckpointViewV1:
    """Load a digest-bound compatibility snapshot without writing any files."""

    root = Path(path)
    if not root.is_dir():
        raise LegacyCheckpointError(f"checkpoint directory not found: {root}")
    digests: dict[str, str] = {}

    tree_path, layout = _tree_source(root)
    tree, tree_digest = _read_json(root, tree_path)
    tree_relative = tree_path.relative_to(root).as_posix()
    digests[tree_relative] = tree_digest
    if "nodes" not in tree:
        raise LegacyCheckpointError(f"legacy tree has no nodes field: {tree_path}")

    results: dict[str, Any] = {}
    results_path = root / "results.json"
    if results_path.is_file():
        results, digests["results.json"] = _read_json(root, results_path)

    replay_inputs: dict[str, Any] = {}
    experiment_path = root / "experiment.md"
    if experiment_path.is_file():
        experiment, digests["experiment.md"] = _read_text(root, experiment_path)
        replay_inputs["experiment_md"] = experiment
    for name in ("launch_config.json", "settings.json"):
        source = root / name
        if source.is_file():
            replay_inputs[name.removesuffix(".json")], digests[name] = _read_json(
                root, source
            )
    workflow_path = root / "workflow.yaml"
    if workflow_path.is_file():
        workflow_text, digests["workflow.yaml"] = _read_text(root, workflow_path)
        try:
            workflow = yaml.safe_load(workflow_text) or {}
        except yaml.YAMLError as exc:
            raise LegacyCheckpointError(
                f"invalid YAML in {workflow_path}: {exc}"
            ) from exc
        if not isinstance(workflow, dict):
            raise LegacyCheckpointError("legacy workflow root must be a mapping")
        replay_inputs["workflow"] = workflow

    paper_source = ""
    paper_relative_path = None
    for relative in (
        "full_paper.tex",
        "paper/full_paper.tex",
        "experiment_section.tex",
    ):
        source = root / relative
        if source.is_file():
            paper_source, digests[relative] = _read_text(root, source)
            paper_relative_path = relative
            break

    run_id = str(tree.get("run_id") or results.get("run_id") or root.name)
    return LegacyCheckpointViewV1(
        checkpoint_id=root.name,
        run_id=run_id,
        tree_layout=layout,
        tree=tree,
        results=results,
        paper_source=paper_source,
        paper_relative_path=paper_relative_path,
        replay_inputs=replay_inputs,
        source_digests=digests,
    )


__all__ = [
    "LEGACY_CHECKPOINT_VIEW_V1",
    "LegacyCheckpointError",
    "LegacyCheckpointViewV1",
    "load_legacy_checkpoint",
]
