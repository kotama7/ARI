"""Topology-neutral snapshots of completed ARI exploration runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from ari.manuscript.contracts import (
    ExplorationSnapshotV1,
    ManuscriptArtifactRefV1,
    ManuscriptNodeSnapshotV1,
)
from ari.manuscript.digest import (
    canonical_digest,
    file_digest,
    normalize_digest,
    path_has_symlink_component,
    safe_relative_path,
)


KNOWN_CHECKPOINT_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("experiment.md", "experiment-spec"),
    ("idea.json", "research-contract"),
    ("evaluation_criteria.json", "metric-contract"),
    ("metric_contract.json", "metric-contract-v1"),
    ("nodes_tree.json", "nodes-tree"),
    ("tree.json", "tree-state"),
    ("results.json", "run-results"),
    ("node_provenance_audit.json", "provenance-audit"),
    ("science_data.json", "science-data"),
    ("related_refs.json", "retrieval-records"),
    ("ear_manifest.json", "ear-manifest"),
    ("ear_published/manifest.lock", "code-bundle-lock"),
    ("figures_manifest.json", "figure-batch"),
    ("verified_context.json", "verified-context"),
    ("manuscript_disclosures.json", "manuscript-disclosures"),
)


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _string(value: Any) -> str:
    raw = getattr(value, "value", value)
    return "" if raw is None else str(raw)


def _finite_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return {
            str(key): str(item)
            for key, item in value.items()
            if item is not None
        }
    return dict(value)


def _scientific_score(metrics: dict[str, Any]) -> float | None:
    value = metrics.get("_scientific_score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    candidates = [
        float(item)
        for key, item in metrics.items()
        if not key.startswith("_")
        and isinstance(item, (int, float))
        and not isinstance(item, bool)
    ]
    return max(candidates) if candidates else None


def _artifact_id(kind: str, identity: str) -> str:
    return f"artifact-{canonical_digest([kind, identity])[7:31]}"


def _relative_artifact_path(
    checkpoint_dir: Path,
    raw_path: str,
    *,
    node: Any | None = None,
) -> str | None:
    """Resolve a node/manifest path without allowing checkpoint escape."""

    raw = raw_path.strip()
    if not raw:
        return None
    candidate = Path(raw)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        work_dir = _string(_get(node, "work_dir", "")) if node is not None else ""
        report_path = (
            _string(_get(node, "node_report_path", ""))
            if node is not None
            else ""
        )
        if work_dir:
            work = Path(work_dir)
            candidates.append((work if work.is_absolute() else checkpoint_dir / work) / candidate)
        if report_path:
            report = Path(report_path)
            report = report if report.is_absolute() else checkpoint_dir / report
            candidates.append(report.parent / candidate)
        candidates.append(checkpoint_dir / candidate)
    # Prefer an existing candidate, then preserve the first declared location
    # so a missing artifact remains addressable and freshness-checkable.
    ordered = sorted(candidates, key=lambda item: not (item.exists() or item.is_symlink()))
    for item in ordered:
        try:
            # Normalize ``..`` lexically but retain symlink components so the
            # caller can classify them as unsafe instead of hashing a target
            # reached through an alias.
            relative = Path(os.path.abspath(item)).relative_to(
                checkpoint_dir
            ).as_posix()
            return safe_relative_path(relative)
        except (OSError, ValueError):
            continue
    return None


def _node_artifact_refs(
    checkpoint_dir: Path, node: Any
) -> list[ManuscriptArtifactRefV1]:
    node_id = _string(_get(node, "id"))
    out: list[ManuscriptArtifactRefV1] = []
    for index, artifact in enumerate(_get(node, "artifacts", []) or []):
        data = (
            artifact
            if isinstance(artifact, dict)
            else {"path": artifact}
            if isinstance(artifact, str)
            else {}
        )
        raw_path = data.get("relative_path") or data.get("path") or data.get("file")
        path: str | None = None
        if isinstance(raw_path, str) and raw_path.strip():
            path = _relative_artifact_path(
                checkpoint_dir, raw_path, node=node
            )
        recorded_digest = normalize_digest(data.get("sha256") or data.get("digest"))
        recorded_size = data.get("size_bytes", data.get("size"))
        if (
            not isinstance(recorded_size, int)
            or isinstance(recorded_size, bool)
            or recorded_size < 0
        ):
            recorded_size = None
        digest = recorded_digest
        size = recorded_size
        identity = path or str(data.get("id") or index)
        status = "unhashed"
        unsafe_path: str | None = None
        if path is None and raw_path:
            status = "invalid"
            unsafe_path = "escape_or_invalid"
        elif path is not None:
            source = checkpoint_dir / path
            if path_has_symlink_component(checkpoint_dir, source):
                status = "invalid"
                unsafe_path = "symlink"
                digest = None
                size = None
            elif not source.is_file():
                status = "missing"
                digest = None
                size = None
            else:
                try:
                    actual_digest, actual_size = file_digest(source)
                    if (
                        (recorded_digest is not None and recorded_digest != actual_digest)
                        or (recorded_size is not None and recorded_size != actual_size)
                    ):
                        status = "mismatch"
                        digest = actual_digest
                        size = actual_size
                    else:
                        status = "present"
                        digest = actual_digest
                        size = actual_size
                except (OSError, ValueError):
                    status = "invalid"
                    digest = None
                    size = None
        out.append(
            ManuscriptArtifactRefV1(
                item_id=_artifact_id("node-artifact", f"{node_id}:{identity}"),
                kind="node-artifact",
                relative_path=path,
                digest=digest,
                size_bytes=size,
                source_node_id=node_id or None,
                status=status,
                metadata={
                    key: value
                    for key, value in data.items()
                    if key not in {"relative_path", "path", "file", "sha256", "digest"}
                    and isinstance(value, (str, int, float, bool, type(None)))
                }
                | ({"recorded_digest": recorded_digest} if recorded_digest else {})
                | ({"recorded_size": recorded_size} if recorded_size is not None else {})
                | ({"unsafe_path": unsafe_path} if unsafe_path else {}),
            )
        )
    return out


def _checkpoint_artifacts(checkpoint_dir: Path) -> list[ManuscriptArtifactRefV1]:
    out: list[ManuscriptArtifactRefV1] = []
    for relative_path, kind in KNOWN_CHECKPOINT_ARTIFACTS:
        path = checkpoint_dir / relative_path
        item_id = _artifact_id(kind, relative_path)
        if path_has_symlink_component(checkpoint_dir, path):
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind=kind,
                    relative_path=relative_path,
                    status="invalid",
                    metadata={"unsafe_path": "symlink"},
                )
            )
            continue
        if not path.is_file():
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind=kind,
                    relative_path=relative_path,
                    status="missing",
                )
            )
            continue
        try:
            digest, size = file_digest(path)
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind=kind,
                    relative_path=relative_path,
                    digest=digest,
                    size_bytes=size,
                    status="present",
                )
            )
        except (OSError, ValueError) as exc:
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind=kind,
                    relative_path=relative_path,
                    status="invalid",
                    metadata={"error": str(exc)[:500]},
                )
            )
    return out


def _node_report_artifacts(
    checkpoint_dir: Path,
    nodes: Iterable[Any],
) -> list[ManuscriptArtifactRefV1]:
    out: list[ManuscriptArtifactRefV1] = []
    for node in nodes:
        node_id = _string(_get(node, "id", ""))
        raw = _string(_get(node, "node_report_path", ""))
        if not node_id or not raw:
            continue
        # node_report_path is already checkpoint-relative by the Node contract;
        # do not resolve it again relative to its own parent.
        relative = _relative_artifact_path(checkpoint_dir, raw)
        item_id = _artifact_id("node-report", f"{node_id}:{relative or raw}")
        if relative is None:
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind="node-report",
                    source_node_id=node_id,
                    status="invalid",
                    metadata={"recorded_ref": raw, "unsafe_path": "escape_or_invalid"},
                )
            )
            continue
        source = checkpoint_dir / relative
        if path_has_symlink_component(checkpoint_dir, source):
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind="node-report",
                    relative_path=relative,
                    source_node_id=node_id,
                    status="invalid",
                    metadata={"unsafe_path": "symlink"},
                )
            )
        elif not source.is_file():
            out.append(
                ManuscriptArtifactRefV1(
                    item_id=item_id,
                    kind="node-report",
                    relative_path=relative,
                    source_node_id=node_id,
                    status="missing",
                )
            )
        else:
            try:
                digest, size = file_digest(source)
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="node-report",
                        relative_path=relative,
                        digest=digest,
                        size_bytes=size,
                        source_node_id=node_id,
                        status="present",
                    )
                )
            except (OSError, ValueError) as exc:
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="node-report",
                        relative_path=relative,
                        source_node_id=node_id,
                        status="invalid",
                        metadata={"error": str(exc)[:500]},
                    )
                )
    return out


def _manifest_referenced_artifacts(
    checkpoint_dir: Path,
    sources: Iterable[ManuscriptArtifactRefV1],
) -> list[ManuscriptArtifactRefV1]:
    """Inventory file references nested in known JSON source contracts."""

    known_paths = {
        item.relative_path for item in sources if item.relative_path is not None
    }
    discovered: dict[tuple[str, str], ManuscriptArtifactRefV1] = {}

    def visit(value: Any, *, source_kind: str) -> None:
        if isinstance(value, dict):
            raw = value.get("relative_path") or value.get("path") or value.get("file")
            if isinstance(raw, str) and raw.strip():
                relative = _relative_artifact_path(checkpoint_dir, raw)
                identity = relative or raw.strip()
                key = (source_kind, identity)
                if relative not in known_paths and key not in discovered:
                    recorded_digest = normalize_digest(
                        value.get("digest") or value.get("sha256")
                    )
                    recorded_size = value.get("size_bytes", value.get("size"))
                    if not isinstance(recorded_size, int) or isinstance(recorded_size, bool):
                        recorded_size = None
                    status = "invalid" if relative is None else "missing"
                    unsafe_path = "escape_or_invalid" if relative is None else None
                    # A missing file cannot carry a content identity.  Keep any
                    # identity asserted by the enclosing manifest as metadata so
                    # the omission remains diagnosable without making the
                    # artifact contract internally inconsistent.
                    digest = None
                    size = None
                    if relative is not None:
                        path = checkpoint_dir / relative
                        if path_has_symlink_component(checkpoint_dir, path):
                            status = "invalid"
                            unsafe_path = "symlink"
                            digest = None
                            size = None
                        elif path.is_file():
                            try:
                                actual = file_digest(path)
                                status = (
                                    "mismatch"
                                    if (
                                        recorded_digest is not None
                                        and recorded_digest != actual[0]
                                    )
                                    or (
                                        recorded_size is not None
                                        and recorded_size != actual[1]
                                    )
                                    else "present"
                                )
                                digest, size = actual
                            except (OSError, ValueError):
                                status = "invalid"
                                digest = None
                                size = None
                    discovered[key] = ManuscriptArtifactRefV1(
                        item_id=_artifact_id(
                            "manifest-artifact", f"{source_kind}:{identity}"
                        ),
                        kind="manifest-artifact",
                        relative_path=relative,
                        digest=digest,
                        size_bytes=size,
                        status=status,
                        metadata={
                            "source_kind": source_kind,
                            **(
                                {"recorded_digest": recorded_digest}
                                if recorded_digest
                                else {}
                            ),
                            **({"unsafe_path": unsafe_path} if unsafe_path else {}),
                        },
                    )
            for child in value.values():
                visit(child, source_kind=source_kind)
        elif isinstance(value, list):
            for child in value:
                visit(child, source_kind=source_kind)

    reference_bearing_source_kinds = {
        "ear-manifest",
        "figure-batch",
        "provenance-audit",
        "science-data",
        "verified-context",
    }
    for source in sources:
        if (
            source.status != "present"
            or source.relative_path is None
            or not source.relative_path.endswith(".json")
            or source.kind not in reference_bearing_source_kinds
        ):
            continue
        try:
            document = json.loads(
                (checkpoint_dir / source.relative_path).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        visit(document, source_kind=source.kind)
    return [discovered[key] for key in sorted(discovered)]


def _attestation_artifacts(
    checkpoint_dir: Path,
    nodes: Iterable[Any],
) -> list[ManuscriptArtifactRefV1]:
    out: list[ManuscriptArtifactRefV1] = []
    for node in nodes:
        node_id = _string(_get(node, "id"))
        for raw in _get(node, "attestation_refs", []) or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                relative = safe_relative_path(raw.strip())
            except ValueError:
                relative = None
            identity = relative or raw.strip()
            item_id = _artifact_id("harness-attestation", identity)
            if relative is None:
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="harness-attestation",
                        source_node_id=node_id or None,
                        status="invalid",
                        metadata={
                            "recorded_ref": raw.strip(),
                            "unsafe_path": "escape_or_invalid",
                        },
                    )
                )
                continue
            path = checkpoint_dir / relative
            if path_has_symlink_component(checkpoint_dir, path):
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="harness-attestation",
                        relative_path=relative,
                        source_node_id=node_id or None,
                        status="invalid",
                        metadata={"unsafe_path": "symlink"},
                    )
                )
                continue
            if not path.is_file():
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="harness-attestation",
                        relative_path=relative,
                        source_node_id=node_id or None,
                        status="missing",
                    )
                )
                continue
            try:
                digest, size = file_digest(path)
                from ari.assurance.models import HarnessAttestationV1

                document = json.loads(path.read_text(encoding="utf-8"))
                attestation = HarnessAttestationV1.model_validate(document)
                target_digest = normalize_digest(
                    _get(node, "verified_target_digest", "")
                )
                tiers = tuple(
                    sorted({item.tier for item in attestation.property_results})
                )
                belongs_to_node = attestation.node_id == node_id
                target_matches = (
                    target_digest is not None
                    and attestation.target_digest == target_digest
                )
                certify_pass = (
                    belongs_to_node
                    and attestation.verdict == "pass"
                    and target_matches
                    and "certify" in tiers
                    and all(
                        item.verdict == "pass"
                        for item in attestation.property_results
                        if item.tier == "certify"
                    )
                )
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="harness-attestation",
                        relative_path=relative,
                        digest=digest,
                        size_bytes=size,
                        source_node_id=node_id or None,
                        status=(
                            "invalid"
                            if not belongs_to_node
                            else "present"
                            if target_matches
                            else "stale"
                        ),
                        metadata={
                            "attestation_digest": attestation.attestation_digest,
                            "target_digest": attestation.target_digest,
                            "verdict": attestation.verdict,
                            "tiers": tiers,
                            "certify_pass": certify_pass,
                            "belongs_to_node": belongs_to_node,
                            "target_matches": target_matches,
                            "verification_contract_digest": (
                                attestation.verification_contract_digest
                            ),
                            "baseline_harness_lock_digest": (
                                attestation.baseline_harness_lock_digest
                            ),
                        },
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError):
                out.append(
                    ManuscriptArtifactRefV1(
                        item_id=item_id,
                        kind="harness-attestation",
                        relative_path=relative,
                        source_node_id=node_id or None,
                        status="invalid",
                    )
                )
    return out


def _research_contract(checkpoint_dir: Path) -> tuple[str | None, str]:
    idea_path = checkpoint_dir / "idea.json"
    if not idea_path.is_file():
        return None, ""
    try:
        data = json.loads(idea_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    contract = data.get("research_contract")
    if isinstance(contract, dict):
        digest = normalize_digest(contract.get("contract_digest"))
        question = str(
            contract.get("research_question")
            or contract.get("objective")
            or contract.get("goal")
            or ""
        )
        if digest:
            return digest, question
    digest = normalize_digest(data.get("research_contract_digest"))
    ideas = data.get("ideas")
    first = ideas[0] if isinstance(ideas, list) and ideas and isinstance(ideas[0], dict) else {}
    question = str(
        data.get("research_question")
        or data.get("goal")
        or first.get("description")
        or first.get("title")
        or ""
    )
    return digest, question


def _run_id(checkpoint_dir: Path) -> str:
    for filename in ("tree.json", "nodes_tree.json"):
        path = checkpoint_dir / filename
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("run_id"):
                    return str(data["run_id"])
            except Exception:
                pass
    return checkpoint_dir.name or "unknown-run"


def build_exploration_snapshot(
    checkpoint_dir: str | Path,
    all_nodes: Iterable[Any],
    *,
    experiment_data: dict[str, Any] | None = None,
    exploration_mode: str = "simple_bfts",
) -> ExplorationSnapshotV1:
    checkpoint = Path(checkpoint_dir).resolve()
    raw_nodes = list(all_nodes or [])
    artifacts = _checkpoint_artifacts(checkpoint)
    for node in raw_nodes:
        artifacts.extend(_node_artifact_refs(checkpoint, node))
    artifacts.extend(_node_report_artifacts(checkpoint, raw_nodes))
    artifacts.extend(_attestation_artifacts(checkpoint, raw_nodes))
    artifacts.extend(_manifest_referenced_artifacts(checkpoint, artifacts))
    artifacts = sorted(artifacts, key=lambda item: item.item_id)
    by_node: dict[str, list[str]] = {}
    for item in artifacts:
        if item.source_node_id:
            by_node.setdefault(item.source_node_id, []).append(item.item_id)

    nodes: list[ManuscriptNodeSnapshotV1] = []
    for raw in raw_nodes:
        node_id = _string(_get(raw, "id"))
        if not node_id:
            continue
        metrics = _finite_mapping(_get(raw, "metrics", {}))
        target_digest = normalize_digest(_get(raw, "verified_target_digest", ""))
        certify_items = tuple(
            sorted(
                item.item_id
                for item in artifacts
                if item.source_node_id == node_id
                and item.kind == "harness-attestation"
                and item.status == "present"
                and item.metadata.get("certify_pass") is True
            )
        )
        valid = metrics.get("_valid_for_frontier", True) is not False and not bool(
            metrics.get("_stale", False)
        )
        nodes.append(
            ManuscriptNodeSnapshotV1(
                node_id=node_id,
                parent_id=_string(_get(raw, "parent_id")) or None,
                ancestor_ids=tuple(
                    str(item) for item in (_get(raw, "ancestor_ids", []) or []) if item
                ),
                depth=max(0, int(_get(raw, "depth", 0) or 0)),
                status=_string(_get(raw, "status", "unknown")),
                label=_string(_get(raw, "label", "")),
                name=_string(_get(raw, "name", "")),
                original_direction=(
                    _string(_get(raw, "original_direction")) or None
                ),
                has_real_data=bool(_get(raw, "has_real_data", False)),
                metrics=metrics,
                scientific_score=_scientific_score(metrics),
                valid_for_frontier=valid,
                assurance_status=_string(_get(raw, "assurance_status", "")),
                assurance_tier=_string(_get(raw, "assurance_tier", "")),
                frontier_class=_string(_get(raw, "frontier_class", "")),
                attestation_refs=tuple(
                    sorted(
                        item.relative_path
                        for item in artifacts
                        if item.source_node_id == node_id
                        and item.kind == "harness-attestation"
                        and item.relative_path is not None
                    )
                ),
                certify_attestation_item_ids=certify_items,
                verified_target_digest=target_digest,
                property_verdicts={
                    str(key): str(value)
                    for key, value in _finite_mapping(
                        _get(raw, "property_verdicts", {})
                    ).items()
                },
                artifact_item_ids=tuple(sorted(by_node.get(node_id, []))),
                repair_request_id=(
                    _string(_get(raw, "repair_request_id", "")) or None
                ),
                repair_requirement_ids=tuple(
                    sorted(
                        str(item)
                        for item in (_get(raw, "repair_requirement_ids", []) or [])
                        if item
                    )
                ),
                repair_context_digest=normalize_digest(
                    _get(raw, "repair_context_digest", "")
                ),
                repair_allowed_changes=tuple(
                    sorted(
                        str(item)
                        for item in (_get(raw, "repair_allowed_changes", []) or [])
                        if item
                    )
                ),
                error_summary=_string(_get(raw, "error_log", ""))[:4_000],
            )
        )
    nodes.sort(key=lambda item: (item.depth, item.node_id))
    valid_nodes = [item for item in nodes if item.valid_for_frontier]
    real_nodes = [item for item in valid_nodes if item.has_real_data]
    candidates = real_nodes or valid_nodes
    candidates.sort(
        key=lambda item: (
            item.scientific_score is not None,
            item.scientific_score if item.scientific_score is not None else float("-inf"),
            item.node_id,
        ),
        reverse=True,
    )
    winner_id = candidates[0].node_id if candidates else None
    contract_digest, question = _research_contract(checkpoint)
    if not question:
        question = str((experiment_data or {}).get("goal") or "")
    source_digests = {
        item.item_id: item.digest
        for item in artifacts
        if item.digest is not None and item.source_node_id is None
    }
    return ExplorationSnapshotV1.create(
        run_id=_run_id(checkpoint),
        checkpoint_id=checkpoint.name or "checkpoint",
        exploration_mode=(
            "ari_rqgm" if exploration_mode == "ari_rqgm" else "simple_bfts"
        ),
        selection_policy_digest=canonical_digest(
            {
                "policy": "manuscript-scientific-winner-v1",
                "validity": "valid_for_frontier",
                "eligibility": "real_data_then_all",
                "order": ["scientific_score_desc", "node_id_desc"],
            }
        ),
        research_contract_digest=contract_digest,
        research_question=question.strip(),
        nodes=tuple(nodes),
        artifacts=tuple(artifacts),
        scientific_winner_id=winner_id,
        source_digests=source_digests,
    )


__all__ = ["KNOWN_CHECKPOINT_ARTIFACTS", "build_exploration_snapshot"]
