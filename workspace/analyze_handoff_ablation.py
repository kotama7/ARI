#!/usr/bin/env python3
"""Analyze an evidence/reflection handoff sweep.

The primary outcome is the independently remeasured search winner stored in
``final_measurement.json``. The two pre-specified contrasts are tested within
seed-matched run blocks on the all-run native outcome, where scientific invalids
are zero. Validity and conditional log-speedup are reported as separate paired
components.

Pure analysis (no LLM/API). Writes ``analysis.json`` next to the manifest.

Usage:
    python workspace/analyze_handoff_ablation.py <out_dir|manifest.jsonl>
    python workspace/analyze_handoff_ablation.py <matrix_root> \
        --aggregate-shards --seeds 30 --expected-array-job-id <job_id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ari-core"))

from ari.evaluator.handoff_stats import (  # noqa: E402
    geomean,
    holm_adjust,
    paired_bootstrap_difference_ci,
    sign_flip_ci,
    paired_permutation_test,
    summarize_arm,
)

PRIMARY_CONTRASTS = (
    ("evidence_only", "code_only"),
    ("evidence_plus_reflection", "evidence_only"),
)
REGISTERED_ARMS = (
    "code_only",
    "evidence_only",
    "evidence_plus_reflection",
)
REGISTERED_HANDOFF_CHANNELS = {
    "code_only": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "0",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "extractive",
    },
    "evidence_only": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "1",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "evidence",
    },
    "evidence_plus_reflection": {
        "ARI_HANDOFF_COPY_WORKDIR": "1",
        "ARI_HANDOFF_AGENT_BLOCK": "1",
        "ARI_HANDOFF_LOG_MODE": "none",
        "ARI_HANDOFF_SUMMARY_FORM": "evidence_reflection",
    },
}


class ShardAggregationError(RuntimeError):
    """The submitted matrix is incomplete, duplicated, or contaminated."""


def _json_clean(value):
    """Convert analysis output to strict JSON-compatible values."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(v) for v in value]
    return value


def run_scored_any(run_dir: str | None) -> bool:
    """True iff the fixed evaluator produced a scientific outcome for the run.

    Infrastructure failures are excluded; candidate/measurement-invalid outcomes
    are retained as scientific zeroes. A typed infrastructure error in any search
    node takes precedence over a superficially valid final-measurement artifact.
    """
    if not run_dir or not os.path.isdir(run_dir):
        return False
    reports: list[dict] = []
    for rpt in glob(os.path.join(run_dir, "node_*", "node_report.json")):
        try:
            with open(rpt) as fh:
                reports.append(json.load(fh))
        except Exception:
            continue
    if any(r.get("evaluation_status") == "infrastructure_error" for r in reports):
        return False

    final_path = Path(run_dir) / "final_measurement.json"
    if final_path.is_file():
        try:
            final = json.loads(final_path.read_text())
            return final.get("evaluation_status") in {
                "valid", "candidate_invalid", "measurement_invalid",
            }
        except Exception:
            return False
    import math as _m
    saw_scored = False
    for report in reports:
        if report.get("evaluation_status") in {
            "valid", "candidate_invalid", "measurement_invalid",
        }:
            saw_scored = True
        m = report.get("metrics") or {}
        for k in ("_scientific_score", "valid_geomean_speedup"):
            v = m.get(k)
            if isinstance(v, (int, float)) and _m.isfinite(v):
                saw_scored = True
    return saw_scored


def report_measurement_valid(report: dict) -> bool | None:
    """Read objective validity from current reports, then legacy reports."""
    current = report.get("measurement_valid")
    if isinstance(current, bool):
        return current
    status = report.get("evaluation_status")
    if status in {
        "valid",
        "candidate_invalid",
        "measurement_invalid",
        "infrastructure_error",
    }:
        return status == "valid"
    has_real_data = report.get("has_real_data")
    if isinstance(has_real_data, bool):
        return has_real_data
    legacy = (report.get("self_assessment") or {}).get("succeeded")
    return legacy if isinstance(legacy, bool) else None


def run_outcome(run_dir: str | None) -> tuple[float, int, int]:
    """Reduce a run to (primary_outcome, n_valid_search_nodes, n_search_nodes).

    Current runs use the independently remeasured winner in
    ``final_measurement.json``. Legacy runs fall back to best valid @ N.
    """
    if not run_dir or not os.path.isdir(run_dir):
        return (0.0, 0, 0)
    best, n_valid, n_nodes = 0.0, 0, 0
    for rpt in glob(os.path.join(run_dir, "node_*", "node_report.json")):
        n_nodes += 1
        try:
            with open(rpt) as fh:
                d = json.load(fh)
        except Exception:
            continue
        m = d.get("metrics") or {}
        g = m.get("valid_geomean_speedup")
        if not isinstance(g, (int, float)):
            continue
        # VALIDITY comes from the evaluator, not from the value being positive.
        # Current reports store deterministic has_real_data as measurement_valid;
        # report_measurement_valid() also reads the legacy mixed location. On the
        # SCORE axis 0.0 is a
        # legitimate measured outcome (the candidate ran and scored nothing), and
        # treating it as "invalid" dropped those runs from the arm means — biasing
        # every arm upward, and differentially, since the arms fail at different
        # rates. Fall back to g > 0 only when the field is absent (older reports).
        verdict = report_measurement_valid(d)
        is_valid = verdict if isinstance(verdict, bool) else (g > 0)
        if is_valid:
            n_valid += 1
            best = max(best, float(g))
    final_path = Path(run_dir) / "final_measurement.json"
    if final_path.is_file():
        try:
            final = json.loads(final_path.read_text())
            score = final.get("scientific_score")
            if (final.get("measurement_valid") is True
                    and isinstance(score, (int, float))
                    and math.isfinite(float(score))):
                best = float(score)
            else:
                best = 0.0
        except Exception:
            best = 0.0
    return (best, n_valid, n_nodes)


def run_outcome_source(run_dir: str | None) -> str:
    if run_dir and (Path(run_dir) / "final_measurement.json").is_file():
        return "independent_final_remeasurement"
    return "legacy_best_valid_at_n"


def run_primary_valid(run_dir: str | None, *, legacy_n_valid: int = 0) -> bool:
    if run_dir:
        path = Path(run_dir) / "final_measurement.json"
        if path.is_file():
            try:
                return json.loads(path.read_text()).get("measurement_valid") is True
            except Exception:
                return False
    return legacy_n_valid > 0


def lineage_stats(run_dir: str | None) -> dict:
    """Node-level, handoff-SENSITIVE stats from the run's tree.json (lineage).

    The 'best valid @ N' outcome is a max over noisy attempts — insensitive to
    handoff. Handoff acts on the DISTRIBUTION: whether a child, inheriting a
    valid parent, improves it (vs breaks it), and the overall success rate /
    mean node quality. Returns counts to aggregate across runs:
      n_nodes, n_valid, valid_speedups, child_total (children of a VALID parent),
      child_improve (child valid & >1.01x parent), child_break (child invalid).
    Sterile no-op children retain their objective validity but are excluded from
    the parent/child transition rates because they made no candidate change.
    """
    out = {"n_nodes": 0, "n_valid": 0, "valid_speedups": [],
           "child_total": 0, "child_improve": 0, "child_break": 0}
    if not run_dir:
        return out
    # tree.json lives in the checkpoint dir paired with the experiments run dir
    ck = run_dir.replace("/experiments/", "/checkpoints/")
    tree = None
    for cand in (os.path.join(ck, "tree.json"), os.path.join(run_dir, "tree.json")):
        if os.path.isfile(cand):
            try:
                with open(cand) as fh:
                    tree = json.load(fh)
            except Exception:
                tree = None
            break
    if not tree:
        return out
    nodes = tree.get("nodes", [])
    def vg(nd):
        g = (nd.get("metrics") or {}).get("valid_geomean_speedup")
        return float(g) if isinstance(g, (int, float)) else 0.0
    def node_valid(nd):
        # Same validity rule as run_outcome: trust the evaluator's verdict; a
        # legitimately-measured score of 0.0 (score axis) is valid, not a failure.
        verdict = report_measurement_valid(nd)
        return verdict if isinstance(verdict, bool) else (vg(nd) > 0)
    gm = {nd.get("id"): (vg(nd) if node_valid(nd) else None) for nd in nodes}
    for nd in nodes:
        out["n_nodes"] += 1
        if node_valid(nd):
            out["n_valid"] += 1
            out["valid_speedups"].append(vg(nd))
        pg = gm.get(nd.get("parent_id"))
        if pg is not None:  # parent was valid: did the child build on it or break it?
            if (nd.get("metrics") or {}).get("_sterile") is True:
                continue
            out["child_total"] += 1
            # A child "improves" if it is itself valid and beats the parent; it
            # "breaks" if it went invalid. Use node_valid() (evaluator verdict),
            # not the old raw g>0 — a legitimately-measured score-axis 0.0 is a
            # valid child, not a break.
            if node_valid(nd) and vg(nd) > pg * 1.01:
                out["child_improve"] += 1
            elif not node_valid(nd):
                out["child_break"] += 1
    return out


def load_manifest(path: Path) -> list[dict]:
    mf = path / "manifest.jsonl" if path.is_dir() else path
    if not mf.is_file():
        sys.exit(f"manifest not found: {mf}")
    rows = [json.loads(line) for line in mf.read_text().splitlines() if line.strip()]
    return rows


def matrix_cells(
    tasks: list[str],
    arms: list[str],
    seed_base: int,
    seeds: int,
) -> list[dict]:
    """Return the registered Slurm-array mapping in array-task order."""
    cells: list[dict] = []
    width = len(tasks) * len(arms)
    for seed_offset in range(seeds):
        seed = seed_base + seed_offset
        arm_offset = seed % len(arms)
        order = arms[arm_offset:] + arms[:arm_offset]
        for task_index, task in enumerate(tasks):
            for arm_position, arm in enumerate(order):
                cells.append({
                    "array_task_id": seed_offset * width
                    + task_index * len(arms)
                    + arm_position,
                    "task": task,
                    "arm": arm,
                    "seed": seed,
                    "arm_order": order,
                    "arm_order_index": arm_position,
                })
    return cells


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(_json_clean(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )
    tmp.replace(path)


def aggregate_shards(
    root: Path,
    *,
    tasks: list[str],
    arms: list[str],
    seed_base: int,
    seeds: int,
    expected_array_job_id: str | None = None,
    expected_study_fingerprint: str | None = None,
    expected_max_nodes: int | None = None,
    expected_remeasure_reps: int | None = None,
    expected_model: str | None = None,
    descriptive_only: bool = False,
) -> dict:
    """Validate and merge one-manifest-per-allocation matrix shards.

    No task analysis is written unless every expected task x arm x seed cell is
    present exactly once and carries its final measurement, provenance bundle,
    and Slurm allocation identity.
    """
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cells = matrix_cells(tasks, arms, seed_base, seeds)
    expected = {
        (cell["task"], cell["arm"], cell["seed"]): cell for cell in cells
    }
    paths = sorted((root / "shards").glob("*/*/seed_*/manifest.jsonl"))
    errors: list[str] = []
    rows_by_key: dict[tuple[str, str, int], dict] = {}
    path_by_key: dict[tuple[str, str, int], str] = {}
    observed_fingerprints: set[str] = set()
    infrastructure_cells: list[dict] = []

    for path in paths:
        try:
            lines = [
                json.loads(line)
                for line in path.read_text().splitlines()
                if line.strip()
            ]
        except Exception as exc:
            errors.append(f"{path}: unreadable manifest: {exc}")
            continue
        if len(lines) != 1:
            errors.append(f"{path}: expected exactly one row, found {len(lines)}")
            continue
        row = lines[0]
        try:
            key = (str(row["task"]), str(row["arm"]), int(row["seed"]))
        except Exception as exc:
            errors.append(f"{path}: invalid task/arm/seed identity: {exc}")
            continue
        if key not in expected:
            errors.append(f"{path}: unexpected matrix cell {key}")
            continue
        if key in rows_by_key:
            errors.append(
                f"duplicate matrix cell {key}: {path_by_key[key]} and {path}"
            )
            continue

        expected_path = (
            root / "shards" / key[0] / key[1] / f"seed_{key[2]}"
            / "manifest.jsonl"
        )
        if path.resolve() != expected_path.resolve():
            errors.append(
                f"{path}: path does not match row identity; expected {expected_path}"
            )

        cell = expected[key]
        if row.get("arm_order") != cell["arm_order"]:
            errors.append(
                f"{path}: arm_order {row.get('arm_order')} != "
                f"{cell['arm_order']}"
            )
        if row.get("arm_order_index") != cell["arm_order_index"]:
            errors.append(
                f"{path}: arm_order_index {row.get('arm_order_index')} != "
                f"{cell['arm_order_index']}"
            )
        if row.get("scorer") != "deterministic":
            errors.append(
                f"{path}: scorer {row.get('scorer')!r} != 'deterministic'"
            )
        if row.get("paired_modes") not in (None, []):
            errors.append(f"{path}: confirmatory shard unexpectedly used paired mode")
        if row.get("resolved_handoff") != REGISTERED_HANDOFF_CHANNELS[key[1]]:
            errors.append(
                f"{path}: resolved_handoff does not match registered arm {key[1]}"
            )
        if (
            expected_max_nodes is not None
            and row.get("max_nodes") != expected_max_nodes
        ):
            errors.append(
                f"{path}: max_nodes {row.get('max_nodes')!r} != "
                f"{expected_max_nodes}"
            )
        if (
            expected_remeasure_reps is not None
            and row.get("remeasure_reps") != expected_remeasure_reps
        ):
            errors.append(
                f"{path}: remeasure_reps {row.get('remeasure_reps')!r} != "
                f"{expected_remeasure_reps}"
            )
        if expected_model is not None and row.get("model") != expected_model:
            errors.append(
                f"{path}: model {row.get('model')!r} != {expected_model!r}"
            )
        source_fingerprint = str(
            row.get("study_source_fingerprint") or ""
        ).strip()
        if expected_study_fingerprint:
            if source_fingerprint != expected_study_fingerprint:
                errors.append(
                    f"{path}: study source fingerprint "
                    f"{source_fingerprint!r} != {expected_study_fingerprint!r}"
                )
            integrity_path = path.parent / "source_integrity.json"
            try:
                integrity = json.loads(integrity_path.read_text())
            except Exception as exc:
                errors.append(
                    f"{path}: missing/unreadable source_integrity.json: {exc}"
                )
            else:
                if (
                    integrity.get("status") != "verified"
                    or integrity.get("expected") != expected_study_fingerprint
                    or integrity.get("before") != expected_study_fingerprint
                    or integrity.get("after") != expected_study_fingerprint
                ):
                    errors.append(
                        f"{path}: source integrity was not verified before and "
                        "after the worker"
                    )
        if source_fingerprint:
            observed_fingerprints.add(source_fingerprint)

        allocation = row.get("allocation") or {}
        if not allocation.get("hostname"):
            errors.append(f"{path}: missing allocation.hostname")
        array_task_id = str(allocation.get("slurm_array_task_id") or "")
        if array_task_id != str(cell["array_task_id"]):
            errors.append(
                f"{path}: Slurm array task {array_task_id!r} != "
                f"{cell['array_task_id']}"
            )
        array_job_id = str(allocation.get("slurm_array_job_id") or "")
        # A COMMA-SEPARATED SET, not a single id. The check exists so that shards
        # from an unrelated submission cannot be swept into this root, and one id
        # expressed that as long as a campaign was exactly one submission. It is
        # not: recovering a cell that died on a terminal API error resubmits just
        # that cell, under a new array job id, into the same root. With a single
        # expected id every shard is then wrong -- the resumed one against the
        # original, or the original 269 against the resumed one. The launcher
        # accumulates the ids it actually submitted for this root and passes them
        # all, so the guarantee is unchanged: every shard must come from a
        # submission this launcher made for this campaign.
        accepted = {
            v.strip() for v in str(expected_array_job_id or "").split(",") if v.strip()
        }
        if accepted and array_job_id not in accepted:
            errors.append(
                f"{path}: Slurm array job {array_job_id!r} not in "
                f"{sorted(accepted)!r}"
            )

        run_dir_raw = row.get("run_dir")
        run_dir = Path(run_dir_raw) if run_dir_raw else None
        readable_node_reports = 0
        final_status = str(
            (row.get("final_measurement") or {}).get("status") or ""
        )
        if run_dir is None or not run_dir.is_dir():
            errors.append(f"{path}: missing run_dir {run_dir_raw!r}")
        elif not (run_dir / "final_measurement.json").is_file():
            errors.append(f"{path}: missing independent final_measurement.json")
        else:
            node_report_paths = sorted(
                run_dir.glob("node_*/node_report.json")
            )
            for report_path in node_report_paths:
                try:
                    json.loads(report_path.read_text())
                    readable_node_reports += 1
                except Exception as exc:
                    errors.append(
                        f"{path}: unreadable node report {report_path}: {exc}"
                    )
            try:
                final_payload = json.loads(
                    (run_dir / "final_measurement.json").read_text()
                )
            except Exception as exc:
                errors.append(f"{path}: unreadable final_measurement.json: {exc}")
            else:
                disk_status = str(
                    final_payload.get("evaluation_status") or ""
                )
                if final_status and disk_status and final_status != disk_status:
                    errors.append(
                        f"{path}: manifest final status {final_status!r} != "
                        f"artifact status {disk_status!r}"
                    )
                final_status = disk_status or final_status
                if (
                    expected_remeasure_reps is not None
                    and final_payload.get("requested_repetitions")
                    != expected_remeasure_reps
                ):
                    errors.append(
                        f"{path}: final requested_repetitions "
                        f"{final_payload.get('requested_repetitions')!r} != "
                        f"{expected_remeasure_reps}"
                    )

        row_rc = row.get("rc")
        if final_status == "infrastructure_error":
            if row_rc in (0, None):
                errors.append(
                    f"{path}: infrastructure_error must carry a non-zero worker rc"
                )
            infrastructure_cells.append({
                "task": key[0],
                "arm": key[1],
                "seed": key[2],
                "rc": row_rc,
                "reason": (row.get("final_measurement") or {}).get("reason"),
            })
        elif row_rc != 0:
            errors.append(
                f"{path}: worker/run rc={row_rc!r} without a recorded "
                "infrastructure_error"
            )
        elif (
            expected_max_nodes is not None
            and readable_node_reports != expected_max_nodes
        ):
            errors.append(
                f"{path}: completed scientific run has "
                f"{readable_node_reports}/{expected_max_nodes} readable node reports"
            )

        bundle_manifest = path.parent / "study_bundle" / "manifest.json"
        recorded_hash = row.get("study_bundle_manifest_sha256")
        if not bundle_manifest.is_file():
            errors.append(f"{path}: missing study bundle manifest")
        elif _sha256_file(bundle_manifest) != recorded_hash:
            errors.append(f"{path}: study bundle manifest hash mismatch")

        rows_by_key[key] = row
        path_by_key[key] = str(path)

    missing = sorted(set(expected) - set(rows_by_key))
    if missing:
        errors.append(
            "missing matrix cells: "
            + ", ".join(f"{task}/{arm}/seed_{seed}" for task, arm, seed in missing)
        )

    run_dirs = [
        str(row.get("run_dir"))
        for row in rows_by_key.values()
        if row.get("run_dir")
    ]
    duplicate_run_dirs = sorted(
        run_dir for run_dir, count in Counter(run_dirs).items() if count > 1
    )
    if duplicate_run_dirs:
        errors.append(
            "run_dir reused by multiple shards: " + ", ".join(duplicate_run_dirs)
        )
    if len(observed_fingerprints) > 1:
        errors.append(
            "matrix used multiple study source fingerprints: "
            + ", ".join(sorted(observed_fingerprints))
        )

    node_counts: dict[str, dict[str, int]] = {}
    for arm in arms:
        counts = Counter(
            (row.get("allocation") or {}).get("hostname")
            for key, row in rows_by_key.items()
            if key[1] == arm and (row.get("allocation") or {}).get("hostname")
        )
        node_counts[arm] = dict(sorted(counts.items()))

    audit = {
        "schema_version": 1,
        "status": "complete" if not errors else "failed",
        "expected_cells": len(expected),
        "discovered_manifests": len(paths),
        "validated_cells": len(rows_by_key),
        "tasks": tasks,
        "arms": arms,
        "seed_base": seed_base,
        "seeds": seeds,
        # The literal keeps the "smoke_" prefix for compatibility with roots
        # already on disk and with the tests that pin it, but it now covers
        # --preflight as well: it means "not confirmatory", not "smoke".
        "analysis_role": (
            "smoke_descriptive_only" if descriptive_only else "confirmatory"
        ),
        "expected_array_job_id": expected_array_job_id,
        "expected_study_source_fingerprint": expected_study_fingerprint,
        "expected_max_nodes": expected_max_nodes,
        "expected_remeasure_reps": expected_remeasure_reps,
        "expected_model": expected_model,
        "observed_study_source_fingerprints": sorted(observed_fingerprints),
        "n_infrastructure_cells": len(infrastructure_cells),
        "infrastructure_cells": infrastructure_cells,
        "node_counts_by_arm": node_counts,
        "errors": errors,
        "shards": [
            {
                **cell,
                "manifest": path_by_key.get(
                    (cell["task"], cell["arm"], cell["seed"])
                ),
                "hostname": (
                    rows_by_key.get(
                        (cell["task"], cell["arm"], cell["seed"]), {}
                    ).get("allocation") or {}
                ).get("hostname"),
            }
            for cell in cells
        ],
    }
    _write_json_atomic(root / "shard_audit.json", audit)
    if errors:
        raise ShardAggregationError(
            f"matrix shard audit failed with {len(errors)} error(s); "
            f"see {root / 'shard_audit.json'}"
        )

    arm_rank = {arm: index for index, arm in enumerate(arms)}
    for task in tasks:
        task_rows = [
            row for (row_task, _, _), row in rows_by_key.items()
            if row_task == task
        ]
        task_rows.sort(key=lambda row: (int(row["seed"]), arm_rank[row["arm"]]))
        task_dir = root / task
        task_dir.mkdir(parents=True, exist_ok=True)
        manifest = task_dir / "manifest.jsonl"
        tmp = manifest.with_name(manifest.name + ".tmp")
        tmp.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in task_rows)
        )
        tmp.replace(manifest)
    return audit


def combine_task_analyses(root: Path) -> int:
    """Apply one Holm correction across the six task-by-primary tests."""
    analyses: list[dict] = []
    for path in sorted(root.glob("*/analysis.json")):
        try:
            analyses.append(json.loads(path.read_text()))
        except Exception as exc:
            raise SystemExit(f"cannot read task analysis {path}: {exc}")
    if not analyses:
        raise SystemExit(f"no child analysis.json files found under {root}")

    records: list[dict] = []
    pvalues: list[float] = []
    for analysis in analyses:
        task = analysis.get("task")
        for key, contrast in (analysis.get("primary_contrasts") or {}).items():
            native = contrast.get("native_all_runs") or {}
            p = native.get("p_value")
            if isinstance(p, (int, float)) and math.isfinite(float(p)):
                records.append({
                    "task": task,
                    "contrast": key,
                    "raw_p": float(p),
                })
                pvalues.append(float(p))
    adjusted = holm_adjust(pvalues)
    for record, p_adj in zip(records, adjusted):
        record["holm_p_across_tasks_and_primary_contrasts"] = p_adj
    out = {
        "schema_version": 1,
        "analysis_role": (
            "smoke_descriptive_only"
            if analyses and all(
                item.get("analysis_role") == "smoke_descriptive_only"
                for item in analyses
            )
            else "confirmatory"
        ),
        "multiplicity_family": (
            "all task x two pre-specified primary contrasts; Holm-Bonferroni"
        ),
        "n_tests": len(records),
        "tests": records,
    }
    path = root / "cross_task_analysis.json"
    path.write_text(json.dumps(_json_clean(out), indent=2, allow_nan=False) + "\n")
    print(f"wrote {path} ({len(records)} primary tests)")
    return 0


def _paired_node_records(run_dir: str | None) -> list[dict]:
    """Per-child records for paired handoff runs.

    A paired run stamps sibling children with ``handoff_mode``. Each record keeps
    the child score, validity, and parent score so the same parent workspace is
    the comparison block.
    """
    if not run_dir or not os.path.isdir(run_dir):
        return []
    reports: dict[str, dict] = {}
    for rpt in glob(os.path.join(run_dir, "node_*", "node_report.json")):
        try:
            d = json.load(open(rpt))
        except Exception:
            continue
        nid = d.get("node_id") or Path(rpt).parent.name
        reports[nid] = d

    def _score(rep: dict | None) -> float:
        if not rep:
            return 0.0
        m = rep.get("metrics") or {}
        g = m.get("valid_geomean_speedup")
        return float(g) if isinstance(g, (int, float)) and math.isfinite(g) else 0.0

    def _valid(rep: dict | None) -> bool:
        if not rep:
            return False
        verdict = report_measurement_valid(rep)
        if isinstance(verdict, bool):
            return verdict
        return _score(rep) > 0

    out: list[dict] = []
    for nid, rep in reports.items():
        mode = (rep.get("handoff_mode") or "").strip()
        pid = rep.get("parent_id")
        if not mode or not pid:
            continue
        parent = reports.get(pid)
        pg = _score(parent)
        cg = _score(rep)
        cv = _valid(rep)
        out.append({
            "node_id": nid,
            "parent_id": pid,
            "handoff_mode": mode,
            "child_score": cg,
            "parent_score": pg,
            "child_valid": cv,
            "improved": bool(cv and cg > pg * 1.01),
            "broke": bool(not cv),
        })
    return out


def analyze_paired(rows: list[dict], out_dir: Path, task: str, is_score: bool) -> int:
    """Analyze paired handoff manifests where one run contains all arms."""
    by_arm: dict[str, list[dict]] = {}
    by_parent: dict[tuple[str, str], set[str]] = {}
    modes_registered: set[str] = set()
    for r in rows:
        for m in (r.get("paired_modes") or []):
            modes_registered.add(str(m))
        for rec in _paired_node_records(r.get("run_dir")):
            by_arm.setdefault(rec["handoff_mode"], []).append(rec)
            by_parent.setdefault((r.get("run_dir") or "", rec["parent_id"]), set()).add(rec["handoff_mode"])

    summary: dict[str, dict] = {}
    axis_label = "score[0,1]" if is_score else "geomean speedup"
    print(f"\n=== Paired handoff evidence/reflection: {out_dir.name}  (task={task}, axis={axis_label}) ===")
    print(f"{'arm':<26} {'children':>8} {'valid':>7} {'center':>10} {'improve':>9} {'break':>8}")
    for arm in sorted(by_arm):
        recs = by_arm[arm]
        vals = [r["child_score"] for r in recs if r["child_valid"]]
        center = (float(sum(vals) / len(vals)) if is_score else geomean(vals)) if vals else float("nan")
        n = len(recs)
        nv = sum(1 for r in recs if r["child_valid"])
        ni = sum(1 for r in recs if r["improved"])
        nb = sum(1 for r in recs if r["broke"])
        summary[arm] = {
            "n_children": n,
            "n_valid_children": nv,
            "valid_rate": nv / n if n else None,
            "center": center,
            "estimator": "mean" if is_score else "geomean",
            "improve_rate": ni / n if n else None,
            "break_rate": nb / n if n else None,
            "child_scores": [r["child_score"] for r in recs],
        }
        print(f"{arm:<26} {n:>8} {nv:>7} {center:>10.3g} {ni/n if n else 0:>8.1%} {nb/n if n else 0:>7.1%}")

    complete_blocks = sum(1 for modes in by_parent.values()
                          if modes_registered and modes_registered.issubset(modes))
    out = {
        "out_dir": str(out_dir),
        "task": task,
        "paired": True,
        "registered_modes": sorted(modes_registered),
        "n_parent_blocks": len(by_parent),
        "n_complete_parent_blocks": complete_blocks,
        "axis": axis_label,
        "arms": summary,
    }
    (out_dir / "analysis.json").write_text(json.dumps(_json_clean(out), indent=2, allow_nan=False))
    print(f"\npaired parent blocks: {complete_blocks}/{len(by_parent)} complete")
    print(f"Wrote {out_dir / 'analysis.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="manifest, task output directory, or matrix root")
    ap.add_argument(
        "--aggregate-shards",
        action="store_true",
        help="validate task x arm x seed array shards and merge per-task manifests "
             "before analysis",
    )
    ap.add_argument("--tasks", default="gemm,spmm,stencil")
    ap.add_argument("--arms", default=",".join(REGISTERED_ARMS))
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=None)
    ap.add_argument("--expected-array-job-id", default=None)
    ap.add_argument("--expected-study-fingerprint", default=None)
    ap.add_argument("--expected-max-nodes", type=int, default=None)
    ap.add_argument("--expected-remeasure-reps", type=int, default=None)
    ap.add_argument("--expected-model", default=None)
    ap.add_argument(
        "--descriptive-only",
        action="store_true",
        help="write smoke-run summaries but suppress confidence intervals and "
             "hypothesis tests",
    )
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if args.aggregate_shards:
        if args.seeds is None or args.seeds < 1:
            ap.error("--aggregate-shards requires --seeds >= 1")
        tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
        arms = [item.strip() for item in args.arms.split(",") if item.strip()]
        if not tasks or not arms:
            ap.error("--tasks and --arms must be non-empty")
        try:
            audit = aggregate_shards(
                target,
                tasks=tasks,
                arms=arms,
                seed_base=args.seed_base,
                seeds=args.seeds,
                expected_array_job_id=args.expected_array_job_id,
                expected_study_fingerprint=args.expected_study_fingerprint,
                expected_max_nodes=args.expected_max_nodes,
                expected_remeasure_reps=args.expected_remeasure_reps,
                expected_model=args.expected_model,
                descriptive_only=args.descriptive_only,
            )
        except ShardAggregationError as exc:
            print(f"[aggregate] FATAL: {exc}", file=sys.stderr)
            return 2
        print(
            f"[aggregate] validated {audit['validated_cells']}/"
            f"{audit['expected_cells']} independent shards"
        )

    if target.is_dir() and not (target / "manifest.jsonl").is_file():
        manifests = sorted(target.glob("*/manifest.jsonl"))
        if manifests:
            import subprocess
            for manifest in manifests:
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    str(manifest.parent),
                ]
                if args.descriptive_only:
                    command.append("--descriptive-only")
                subprocess.run(command, check=True)
            return combine_task_analyses(target)
    rows = load_manifest(target)
    out_dir = target if target.is_dir() else target.parent

    # Task-awareness: refuse a manifest that mixes native outcome axes. Each task
    # is analyzed separately; cross-task aggregation combines only adjusted
    # hypothesis-test records, never raw scores.
    tasks = sorted({(r.get("task") or "spmm") for r in rows})
    if len(tasks) > 1:
        sys.exit(f"manifest mixes tasks {tasks}: scores are non-commensurable "
                 f"across performance/numerical/combinatorial axes — analyze each "
                 f"task's sweep separately (the driver writes one --task per manifest).")
    task = tasks[0]
    from ari.harness_registry import axis as _task_axis
    is_score = _task_axis(task) == "score"
    axis_label = "score[0,1]" if is_score else "geomean speedup"

    if any(r.get("paired_modes") for r in rows):
        before = len(rows)
        rows = [
            r for r in rows
            if r.get("rc") in (0, None) and r.get("run_dir") and run_scored_any(r.get("run_dir"))
        ]
        if len(rows) != before:
            print(f"[analyze] paired mode: excluded {before - len(rows)} infrastructure/unscored run(s).")
        return analyze_paired(rows, out_dir, task, is_score)

    # arm -> list of run records {seed, outcome, n_valid, n_nodes}
    by_arm: dict[str, list[dict]] = {}
    lin_by_arm: dict[str, dict] = {}
    # DEDUPE (arm, seed). A successful measurement always wins over an
    # infrastructure-failed retry; among rows with the same status, last wins.
    # Dedupe key includes model/scorer/max_nodes so runs that share (arm, seed)
    # but differ in configuration are NOT collapsed into one (that would drop a
    # legitimately distinct run).
    def _is_infra(r) -> bool:
        if r.get("rc") not in (0, None) or not r.get("run_dir"):
            return True
        return not run_scored_any(r.get("run_dir"))

    _seen: dict[tuple, int] = {}
    _deduped: list[dict] = []
    for r in rows:
        key = (r.get("arm"), r.get("seed"), r.get("model"),
               r.get("scorer"), r.get("max_nodes"))
        if key in _seen:
            idx = _seen[key]
            current = _deduped[idx]
            if _is_infra(current) or not _is_infra(r):
                _deduped[idx] = r
        else:
            _seen[key] = len(_deduped)
            _deduped.append(r)
    if len(_deduped) != len(rows):
        print(f"[analyze] deduped {len(rows) - len(_deduped)} repeated (arm, seed) "
              f"manifest row(s); {len(_deduped)} unique runs remain.")
    rows = _deduped

    # INFRASTRUCTURE failures are not scientific outcomes. A run whose driver exited
    # non-zero (job died, node lost, harness crashed) produced no measurement, but it
    # used to be reduced to outcome 0.0 and ranked as "the agent failed" — importing
    # cluster flakiness into the treatment effect, and differentially if one arm runs
    # longer. They are excluded and counted separately.
    _infra = [r for r in rows if _is_infra(r)]
    _infra_records = [
        {
            "task": r.get("task"),
            "arm": r.get("arm"),
            "seed": r.get("seed"),
            "rc": r.get("rc"),
            "status": (r.get("final_measurement") or {}).get("status"),
            "reason": (r.get("final_measurement") or {}).get("reason"),
        }
        for r in _infra
    ]
    _infra_by_arm = dict(sorted(Counter(
        str(r.get("arm") or "?") for r in _infra
    ).items()))
    if _infra:
        print(f"[analyze] EXCLUDED {len(_infra)} run(s) (infrastructure failure: rc!=0, "
              f"missing run_dir, or NO node ever scored [LLM/provider outage]; not a "
              f"measured outcome): {_infra_by_arm}")
        if len(_infra) >= 0.2 * max(1, len(rows)):
            print(f"  *** WARNING: {len(_infra)}/{len(rows)} runs are infrastructure "
                  f"failures (>=20%). This sweep is likely CORRUPTED (provider outage / "
                  f"resource limit) — investigate before trusting any contrast. ***")
        rows = [r for r in rows if not _is_infra(r)]

    for r in rows:
        best, nv, nn = run_outcome(r.get("run_dir"))
        by_arm.setdefault(r["arm"], []).append(
            {
                "seed": r.get("seed"),
                "outcome": best,
                "outcome_valid": run_primary_valid(
                    r.get("run_dir"), legacy_n_valid=nv),
                "outcome_source": run_outcome_source(r.get("run_dir")),
                "n_valid": nv,
                "n_nodes": nn,
            }
        )
        ls = lineage_stats(r.get("run_dir"))
        agg = lin_by_arm.setdefault(r["arm"], {"n_nodes": 0, "n_valid": 0,
            "valid_speedups": [], "child_total": 0, "child_improve": 0, "child_break": 0,
            "runs_seen": 0, "runs_with_lineage": 0})
        for k in ("n_nodes", "n_valid", "child_total", "child_improve", "child_break"):
            agg[k] += ls[k]
        agg["valid_speedups"].extend(ls["valid_speedups"])
        # A run whose tree.json is missing/unreadable contributes ZERO nodes. Without
        # this counter the node-level table silently pooled a different number of runs
        # per arm and printed the percentages side by side as if comparable.
        agg["runs_seen"] += 1
        agg["runs_with_lineage"] += 1 if ls["n_nodes"] else 0

    summary: dict[str, dict] = {}
    print(f"\n=== Handoff ablation: {out_dir.name}  (task={task}, axis={axis_label}) ===")
    print(
        f"{'arm':<26} {'runs':>5} {'valid':>6} {'all-run mean':>14} "
        f"{'valid-only center':>18}"
    )
    for arm in sorted(by_arm):
        runs = by_arm[arm]
        outcomes = [x["outcome"] for x in runs]
        valid = [x["outcome"] for x in runs if x["outcome_valid"]]
        all_runs = summarize_arm(outcomes, is_score=True)
        valid_only = (
            summarize_arm(valid, is_score=is_score)
            if valid
            else {
                "n_runs": 0,
                "geomean": float("nan"),
                "center": float("nan"),
                "estimator": "mean" if is_score else "geomean",
                "ci_lo": float("nan"),
                "ci_hi": float("nan"),
            }
        )
        s = {
            "n_total": len(runs),
            "n_valid_runs": len(valid),
            "valid_rate": len(valid) / len(runs) if runs else None,
            "all_run_mean": all_runs["center"],
            "all_run_ci_lo": (
                None if args.descriptive_only else all_runs["ci_lo"]),
            "all_run_ci_hi": (
                None if args.descriptive_only else all_runs["ci_hi"]),
            "valid_only_center": valid_only["center"],
            "valid_only_estimator": valid_only["estimator"],
            "valid_only_ci_lo": (
                None if args.descriptive_only else valid_only["ci_lo"]),
            "valid_only_ci_hi": (
                None if args.descriptive_only else valid_only["ci_hi"]),
            # Compatibility key for existing consumers: explicitly valid-only.
            "geomean": valid_only["center"],
            "seeds": [x["seed"] for x in runs],
            "outcomes": outcomes,
            "outcome_valid": [x["outcome_valid"] for x in runs],
            "outcome_sources": [x["outcome_source"] for x in runs],
        }
        summary[arm] = s
        print(
            f"{arm:<26} {len(runs):>5} {len(valid):>6} "
            f"{s['all_run_mean']:>14.3g} {s['valid_only_center']:>18.3g}"
        )

    # Exploratory handoff-sensitive distribution stats (node level, from lineage).
    # These do not replace the independently remeasured run-level primary outcome.
    print(f"\n{'arm':<22} {'succ%':>6} {'mean_sp':>8} {'child improve/break/tot':>24}"
          f"  {'runs w/ lineage':>16}")
    for arm in sorted(lin_by_arm):
        a = lin_by_arm[arm]
        vs = a["valid_speedups"]
        # Axis-consistent central tendency (same rule as summarize_arm): the
        # bounded [0,1] score axis uses the arithmetic mean, ratios the geomean.
        msp = (float(sum(vs)/len(vs)) if is_score else geomean(vs)) if vs else float("nan")
        succ = 100.0 * a["n_valid"] / a["n_nodes"] if a["n_nodes"] else float("nan")
        ct = a["child_total"]
        s = summary.setdefault(arm, {})
        s["node_success_rate"] = succ / 100.0 if a["n_nodes"] else None
        s["node_mean_geomean"] = msp
        s["n_nodes"] = a["n_nodes"]
        s["child_total"] = ct
        s["child_improve_rate"] = (a["child_improve"] / ct) if ct else None
        s["child_break_rate"] = (a["child_break"] / ct) if ct else None
        s["runs_with_lineage"] = a["runs_with_lineage"]
        s["runs_seen"] = a["runs_seen"]
        _partial = "" if a["runs_with_lineage"] == a["runs_seen"] else "  <-- PARTIAL"
        print(f"{arm:<22} {succ:>5.0f}% {msp:>8.1f}"
              f"  {a['child_improve']:>3}/{a['child_break']:<3}/{ct:<3}"
              f"  (imp {100*a['child_improve']/ct if ct else 0:.0f}% / brk {100*a['child_break']/ct if ct else 0:.0f}%)"
              f"  {a['runs_with_lineage']:>7}/{a['runs_seen']:<7}{_partial}")
    if any(x["runs_with_lineage"] != x["runs_seen"] for x in lin_by_arm.values()):
        print("  NOTE: arms marked PARTIAL pooled nodes from fewer runs than they have; "
              "these node-level percentages are NOT comparable across arms as printed.")

    primary_contrasts: dict[str, dict] = {}

    def _records_by_seed(records: list[dict]) -> tuple[dict[int, dict], list[int]]:
        mapped: dict[int, dict] = {}
        duplicates: list[int] = []
        for record in records:
            seed = int(record["seed"])
            if seed in mapped:
                duplicates.append(seed)
            mapped[seed] = record
        return mapped, sorted(set(duplicates))

    for treatment, control in PRIMARY_CONTRASTS:
        key = f"{treatment}_minus_{control}"
        if treatment not in summary or control not in summary:
            primary_contrasts[key] = {
                "protocol_deviation": "required arm missing",
                "missing_arms": [
                    arm for arm in (treatment, control) if arm not in summary
                ],
            }
            print(f"\nPRIMARY {key}: required arm missing")
            continue

        t_by_seed, t_duplicates = _records_by_seed(by_arm[treatment])
        c_by_seed, c_duplicates = _records_by_seed(by_arm[control])
        if t_duplicates or c_duplicates:
            primary_contrasts[key] = {
                "treatment": treatment,
                "control": control,
                "protocol_deviation": "duplicate run within arm and seed",
                "treatment_duplicate_seeds": t_duplicates,
                "control_duplicate_seeds": c_duplicates,
            }
            continue

        paired_seeds = sorted(set(t_by_seed) & set(c_by_seed))
        unmatched_treatment = sorted(set(t_by_seed) - set(c_by_seed))
        unmatched_control = sorted(set(c_by_seed) - set(t_by_seed))
        if args.descriptive_only:
            primary_contrasts[key] = {
                "treatment": treatment,
                "control": control,
                "analysis_role": "smoke_descriptive_only",
                "not_estimated": (
                    "Smoke runs validate execution and collection only; "
                    "no confidence interval or hypothesis test is computed."
                ),
                "paired_seeds": paired_seeds,
            }
            continue
        if not paired_seeds:
            primary_contrasts[key] = {
                "treatment": treatment,
                "control": control,
                "protocol_deviation": "no complete seed-matched run pairs",
                "unmatched_treatment_seeds": unmatched_treatment,
                "unmatched_control_seeds": unmatched_control,
            }
            continue

        t_records = [t_by_seed[seed] for seed in paired_seeds]
        c_records = [c_by_seed[seed] for seed in paired_seeds]
        t_values = [float(record["outcome"]) for record in t_records]
        c_values = [float(record["outcome"]) for record in c_records]
        native = paired_permutation_test(t_values, c_values)
        point, ci_lo, ci_hi = paired_bootstrap_difference_ci(
            t_values, c_values)
        # The percentile bootstrap interval and the sign-flip p-value are two
        # different procedures and can disagree at the boundary, which reads as
        # an inconsistent result. Also report the interval obtained by INVERTING
        # the sign-flip test, which agrees with the reported p-value by
        # construction. The bootstrap interval and the p-value are unchanged.
        _, sf_lo, sf_hi = sign_flip_ci(t_values, c_values)
        native.update({
            "effect": "mean(treatment-control) within seed",
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "sign_flip_ci_lo": sf_lo,
            "sign_flip_ci_hi": sf_hi,
            "sign_flip_ci_n_perm": 500_000,
            "invalid_run_value": 0.0,
            "paired_seeds": paired_seeds,
            "unmatched_treatment_seeds": unmatched_treatment,
            "unmatched_control_seeds": unmatched_control,
        })

        t_valid_flags = [bool(record["outcome_valid"]) for record in t_records]
        c_valid_flags = [bool(record["outcome_valid"]) for record in c_records]
        tv, tn = sum(t_valid_flags), len(t_valid_flags)
        cv, cn = sum(c_valid_flags), len(c_valid_flags)
        treatment_only_valid = sum(
            t_valid and not c_valid
            for t_valid, c_valid in zip(t_valid_flags, c_valid_flags)
        )
        control_only_valid = sum(
            c_valid and not t_valid
            for t_valid, c_valid in zip(t_valid_flags, c_valid_flags)
        )
        discordant = treatment_only_valid + control_only_valid
        if discordant:
            from scipy import stats as _scipy_stats
            validity_p = float(_scipy_stats.binomtest(
                treatment_only_valid,
                n=discordant,
                p=0.5,
                alternative="two-sided",
            ).pvalue)
        else:
            validity_p = 1.0
        risk_point, risk_lo, risk_hi = paired_bootstrap_difference_ci(
            [float(value) for value in t_valid_flags],
            [float(value) for value in c_valid_flags],
        )
        validity = {
            "treatment_valid": tv,
            "treatment_total": tn,
            "control_valid": cv,
            "control_total": cn,
            "risk_difference": risk_point,
            "risk_difference_ci_lo": risk_lo,
            "risk_difference_ci_hi": risk_hi,
            "treatment_only_valid": treatment_only_valid,
            "control_only_valid": control_only_valid,
            "p_value_two_sided_mcnemar_exact": validity_p,
            "n_pairs": len(paired_seeds),
        }

        both_valid = [
            index for index, (t_valid, c_valid)
            in enumerate(zip(t_valid_flags, c_valid_flags))
            if t_valid and c_valid
        ]
        t_survivors = [t_values[index] for index in both_valid]
        c_survivors = [c_values[index] for index in both_valid]
        if not is_score:
            t_cond = [math.log(v) for v in t_survivors if v > 0]
            c_cond = [math.log(v) for v in c_survivors if v > 0]
            conditional_domain = "log_speedup"
        else:
            t_cond, c_cond = t_survivors, c_survivors
            conditional_domain = "native_score"
        conditional = paired_permutation_test(t_cond, c_cond)
        c_point, c_lo, c_hi = paired_bootstrap_difference_ci(t_cond, c_cond)
        conditional.update({
            "domain": conditional_domain,
            "ci_lo": c_lo,
            "ci_hi": c_hi,
            "conditional_on_both_seed_matched_final_remeasurements_valid": True,
            "paired_seeds": [paired_seeds[index] for index in both_valid],
        })
        if not is_score and math.isfinite(c_point):
            conditional["geomean_ratio_treatment_over_control"] = math.exp(c_point)

        primary_contrasts[key] = {
            "treatment": treatment,
            "control": control,
            "native_all_runs": native,
            "validity": validity,
            "conditional_magnitude": conditional,
        }
        print(
            f"\nPRIMARY two-sided {key}: native mean diff={point:+.4g}, "
            f"95% CI [{ci_lo:+.4g}, {ci_hi:+.4g}], p={native['p_value']:.4g}"
        )
        print(
            f"  validity {tv}/{tn} vs {cv}/{cn}, "
            f"risk diff={validity['risk_difference']:+.3f}, "
            f"exact McNemar p={validity_p:.4g}"
        )

    result = {
        "out_dir": str(out_dir),
        "n_runs": len(rows),
        "task": task,
        "axis": axis_label,
        "is_score_axis": is_score,
        "analysis_role": (
            "smoke_descriptive_only"
            if args.descriptive_only else "confirmatory"
        ),
        "infrastructure_exclusions": {
            "n_total": len(_infra_records),
            "by_arm": _infra_by_arm,
            "records": _infra_records,
        },
        "primary_outcome": (
            "independently remeasured selected candidate; invalid=0"
        ),
        "arms": summary,
        "primary_contrasts": primary_contrasts,
        # Compatibility alias; no JT/TOST tests are run in this protocol.
        "contrasts": primary_contrasts,
    }
    (out_dir / "analysis.json").write_text(
        json.dumps(_json_clean(result), indent=2, allow_nan=False)
    )
    print(f"\nwrote {out_dir / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
