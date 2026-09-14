"""Tests for the handoff-sweep analyzer's outcome extraction.

The analyzer is a study-specific CLI (not a package). It lives under
``workspace/`` (gitignored, self-contained with the harnesses), with a legacy
``scripts/`` fallback; import it by path and skip if neither location exists.
We exercise the independent final remeasurement and the legacy best-valid
fallback that map a run directory to its analysis outcome.
"""
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = next((p for p in (_ROOT / "workspace" / "analyze_handoff_ablation.py",
                            _ROOT / "scripts" / "analyze_handoff_ablation.py") if p.is_file()), None)
if _SCRIPT is None:
    pytest.skip("analyze_handoff_ablation.py not found (workspace/ or scripts/)", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("analyze_handoff_ablation", _SCRIPT)
ana = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ana)


def _node(run_dir: Path, name: str, *, valid_geomean):
    nd = run_dir / f"node_{name}"
    nd.mkdir(parents=True, exist_ok=True)
    metrics = {} if valid_geomean is None else {"valid_geomean_speedup": valid_geomean}
    (nd / "node_report.json").write_text(json.dumps({"node_id": name, "metrics": metrics}))


def test_run_outcome_picks_best_valid(tmp_path):
    run = tmp_path / "run1"
    _node(run, "root", valid_geomean=0.0)     # invalid (evaluator zeroes it)
    _node(run, "a", valid_geomean=3.5)        # valid
    _node(run, "b", valid_geomean=9.0)        # valid, best
    _node(run, "c", valid_geomean=None)       # failed (no metric)
    best, n_valid, n_nodes = ana.run_outcome(str(run))
    assert best == 9.0
    assert n_valid == 2
    assert n_nodes == 4


def test_run_outcome_no_valid_node_is_zero(tmp_path):
    run = tmp_path / "run2"
    _node(run, "root", valid_geomean=0.0)
    _node(run, "a", valid_geomean=None)
    best, n_valid, n_nodes = ana.run_outcome(str(run))
    assert best == 0.0 and n_valid == 0 and n_nodes == 2


def test_run_outcome_missing_dir(tmp_path):
    assert ana.run_outcome(None) == (0.0, 0, 0)
    assert ana.run_outcome(str(tmp_path / "nope")) == (0.0, 0, 0)


def test_run_outcome_prefers_independent_final_remeasurement(tmp_path):
    run = tmp_path / "run_final"
    _node(run, "search_winner", valid_geomean=9.0)
    (run / "final_measurement.json").write_text(json.dumps({
        "evaluation_status": "valid",
        "measurement_valid": True,
        "scientific_score": 4.25,
    }))
    best, n_valid, n_nodes = ana.run_outcome(str(run))
    assert (best, n_valid, n_nodes) == (4.25, 1, 1)
    assert ana.run_outcome_source(str(run)) == "independent_final_remeasurement"


def test_analyzer_runs_two_registered_two_sided_primary_contrasts(tmp_path):
    """The task analysis matches the paper's two pairwise confirmatory tests."""
    import json as _json
    import subprocess
    import sys
    arms = {
        "code_only": [3.0, 3.3],
        "evidence_only": [5.0, 5.2],
        "evidence_plus_reflection": [5.0, 5.1],
    }
    rows = []
    for arm, vals in arms.items():
        for seed, v in enumerate(vals):
            rd = tmp_path / f"{arm}_{seed}"
            _node(rd, "a", valid_geomean=v)
            rows.append({"arm": arm, "seed": seed, "run_dir": str(rd), "rc": 0})
    (tmp_path / "manifest.jsonl").write_text(
        "\n".join(_json.dumps(r) for r in rows) + "\n")
    subprocess.run([sys.executable, str(_SCRIPT), str(tmp_path)],
                   check=True, capture_output=True)
    out = _json.loads((tmp_path / "analysis.json").read_text())
    c = out["primary_contrasts"]
    assert set(c) == {
        "evidence_only_minus_code_only",
        "evidence_plus_reflection_minus_evidence_only",
    }
    assert all(
        item["native_all_runs"]["alternative"] == "two-sided"
        for item in c.values()
    )
    assert all(
        item["native_all_runs"]["method"] == "paired sign-flip permutation"
        and item["native_all_runs"]["n_pairs"] == 2
        for item in c.values()
    )
    assert all(
        "p_value_two_sided_mcnemar_exact" in item["validity"]
        for item in c.values()
    )
    assert "primary_trend_jt" not in out["contrasts"]


def test_descriptive_only_suppresses_smoke_inference(tmp_path):
    import subprocess
    import sys

    rows = []
    for arm, value in (
        ("code_only", 3.0),
        ("evidence_only", 5.0),
        ("evidence_plus_reflection", 4.0),
    ):
        run_dir = tmp_path / arm
        _node(run_dir, "a", valid_geomean=value)
        rows.append({
            "arm": arm,
            "seed": 0,
            "run_dir": str(run_dir),
            "rc": 0,
        })
    (tmp_path / "manifest.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n")
    subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(tmp_path),
            "--descriptive-only",
        ],
        check=True,
        capture_output=True,
    )
    out = json.loads((tmp_path / "analysis.json").read_text())
    assert out["analysis_role"] == "smoke_descriptive_only"
    assert all(
        contrast["analysis_role"] == "smoke_descriptive_only"
        and "not_estimated" in contrast
        and "native_all_runs" not in contrast
        for contrast in out["primary_contrasts"].values()
    )
    assert all(
        arm["all_run_ci_lo"] is None and arm["all_run_ci_hi"] is None
        for arm in out["arms"].values()
    )


def test_analysis_reports_typed_infrastructure_exclusions(tmp_path):
    import subprocess
    import sys

    rows = []
    for arm in ana.REGISTERED_ARMS:
        run_dir = tmp_path / arm
        _node(run_dir, "valid", valid_geomean=2.0)
        rows.append({
            "task": "gemm",
            "arm": arm,
            "seed": 0,
            "run_dir": str(run_dir),
            "rc": 0,
        })
    failed_run = tmp_path / "evidence_failed"
    failed_node = failed_run / "node_root"
    failed_node.mkdir(parents=True)
    (failed_node / "node_report.json").write_text(json.dumps({
        "node_id": "node_root",
        "evaluation_status": "infrastructure_error",
        "measurement_valid": False,
        "metrics": {"_scientific_score": 0.0},
    }))
    (failed_run / "final_measurement.json").write_text(json.dumps({
        "evaluation_status": "infrastructure_error",
        "measurement_valid": False,
        "scientific_score": None,
    }))
    rows.append({
        "task": "gemm",
        "arm": "evidence_only",
        "seed": 1,
        "run_dir": str(failed_run),
        "rc": 4,
        "final_measurement": {
            "status": "infrastructure_error",
            "reason": "provider outage",
        },
    })
    (tmp_path / "manifest.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n")

    subprocess.run(
        [sys.executable, str(_SCRIPT), str(tmp_path), "--descriptive-only"],
        check=True,
        capture_output=True,
    )
    out = json.loads((tmp_path / "analysis.json").read_text())
    exclusions = out["infrastructure_exclusions"]
    assert exclusions["n_total"] == 1
    assert exclusions["by_arm"] == {"evidence_only": 1}
    assert exclusions["records"][0]["seed"] == 1


def test_matrix_cells_rotate_arm_array_positions_across_seeds():
    tasks = ["gemm", "spmm", "stencil"]
    arms = ["code_only", "evidence_only", "evidence_plus_reflection"]
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=3)

    assert len(cells) == 27
    assert [cell["array_task_id"] for cell in cells] == list(range(27))
    gemm_orders = [
        [
            cell["arm"]
            for cell in cells
            if cell["task"] == "gemm" and cell["seed"] == seed
        ]
        for seed in range(3)
    ]
    assert gemm_orders == [
        ["code_only", "evidence_only", "evidence_plus_reflection"],
        ["evidence_only", "evidence_plus_reflection", "code_only"],
        ["evidence_plus_reflection", "code_only", "evidence_only"],
    ]


def _write_matrix_shard(
    root: Path,
    cell: dict,
    *,
    array_job_id="8123",
    fingerprint="a" * 64,
    final_status="valid",
    rc=0,
    node_count=1,
):
    task, arm, seed = cell["task"], cell["arm"], cell["seed"]
    shard = root / "shards" / task / arm / f"seed_{seed}"
    shard.mkdir(parents=True)
    run_dir = root / "runs" / f"{task}_{arm}_{seed}"
    run_dir.mkdir(parents=True)
    for index in range(node_count):
        node = run_dir / f"node_{index}"
        node.mkdir()
        (node / "node_report.json").write_text(json.dumps({
            "node_id": f"node_{index}",
            "evaluation_status": "valid",
            "measurement_valid": True,
            "metrics": {
                "_scientific_score": 2.0,
                "valid_geomean_speedup": 2.0,
            },
        }))
    (run_dir / "final_measurement.json").write_text(json.dumps({
        "evaluation_status": final_status,
        "measurement_valid": final_status == "valid",
        "scientific_score": (
            None if final_status == "infrastructure_error" else 2.0
        ),
        "requested_repetitions": 5,
        "expected_search_nodes": 1,
        "observed_search_nodes": node_count,
    }))
    bundle = shard / "study_bundle"
    bundle.mkdir()
    bundle_manifest = bundle / "manifest.json"
    bundle_manifest.write_text("{}\n")
    bundle_hash = hashlib.sha256(bundle_manifest.read_bytes()).hexdigest()
    row = {
        "task": task,
        "arm": arm,
        "seed": seed,
        "rc": rc,
        "run_dir": str(run_dir),
        "model": "registered-model",
        "scorer": "deterministic",
        "max_nodes": 1,
        "remeasure_reps": 5,
        "paired_modes": None,
        "resolved_handoff": ana.REGISTERED_HANDOFF_CHANNELS[arm],
        "arm_order": cell["arm_order"],
        "arm_order_index": cell["arm_order_index"],
        "study_bundle_manifest_sha256": bundle_hash,
        "study_source_fingerprint": fingerprint,
        "final_measurement": {
            "status": final_status,
            "score": None if final_status == "infrastructure_error" else 2.0,
            "reason": (
                "provider outage"
                if final_status == "infrastructure_error"
                else "ok"
            ),
        },
        "allocation": {
            "hostname": f"fx{cell['array_task_id']:02d}",
            "slurm_array_job_id": array_job_id,
            "slurm_array_task_id": str(cell["array_task_id"]),
        },
    }
    (shard / "manifest.jsonl").write_text(json.dumps(row) + "\n")
    (shard / "source_integrity.json").write_text(json.dumps({
        "schema_version": 1,
        "expected": fingerprint,
        "before": fingerprint,
        "after": fingerprint,
        "status": "verified",
    }))


def test_aggregate_shards_requires_and_merges_complete_grid(tmp_path):
    tasks = ["gemm"]
    arms = list(ana.REGISTERED_ARMS)
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=1)
    for cell in cells:
        _write_matrix_shard(tmp_path, cell)

    audit = ana.aggregate_shards(
        tmp_path,
        tasks=tasks,
        arms=arms,
        seed_base=0,
        seeds=1,
        expected_array_job_id="8123",
        expected_study_fingerprint="a" * 64,
        expected_max_nodes=1,
        expected_remeasure_reps=5,
        expected_model="registered-model",
    )

    assert audit["status"] == "complete"
    assert audit["expected_cells"] == 3
    rows = [
        json.loads(line)
        for line in (tmp_path / "gemm" / "manifest.jsonl").read_text().splitlines()
    ]
    assert {(row["arm"], row["seed"]) for row in rows} == {
        (arm, 0) for arm in arms
    }


def test_aggregate_shards_fails_loudly_on_missing_cell(tmp_path):
    tasks = ["gemm"]
    arms = list(ana.REGISTERED_ARMS)
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=1)
    for cell in cells[:-1]:
        _write_matrix_shard(tmp_path, cell)

    with pytest.raises(ana.ShardAggregationError):
        ana.aggregate_shards(
            tmp_path,
            tasks=tasks,
            arms=arms,
            seed_base=0,
            seeds=1,
            expected_array_job_id="8123",
            expected_study_fingerprint="a" * 64,
            expected_max_nodes=1,
            expected_remeasure_reps=5,
            expected_model="registered-model",
        )

    audit = json.loads((tmp_path / "shard_audit.json").read_text())
    assert audit["status"] == "failed"
    assert any("missing matrix cells" in error for error in audit["errors"])
    assert not (tmp_path / "gemm" / "manifest.jsonl").exists()


def test_aggregate_keeps_typed_infrastructure_cell_for_analysis(tmp_path):
    tasks = ["gemm"]
    arms = list(ana.REGISTERED_ARMS)
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=1)
    for cell in cells:
        if cell["arm"] == "evidence_only":
            _write_matrix_shard(
                tmp_path,
                cell,
                final_status="infrastructure_error",
                rc=4,
            )
        else:
            _write_matrix_shard(tmp_path, cell)

    audit = ana.aggregate_shards(
        tmp_path,
        tasks=tasks,
        arms=arms,
        seed_base=0,
        seeds=1,
        expected_array_job_id="8123",
        expected_study_fingerprint="a" * 64,
        expected_max_nodes=1,
        expected_remeasure_reps=5,
        expected_model="registered-model",
    )

    assert audit["status"] == "complete"
    assert audit["n_infrastructure_cells"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "gemm" / "manifest.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 3
    assert any(row["rc"] == 4 for row in rows)


def test_aggregate_rejects_source_fingerprint_mismatch(tmp_path):
    tasks = ["gemm"]
    arms = list(ana.REGISTERED_ARMS)
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=1)
    for index, cell in enumerate(cells):
        _write_matrix_shard(
            tmp_path,
            cell,
            fingerprint=("b" * 64 if index == 0 else "a" * 64),
        )

    with pytest.raises(ana.ShardAggregationError):
        ana.aggregate_shards(
            tmp_path,
            tasks=tasks,
            arms=arms,
            seed_base=0,
            seeds=1,
            expected_array_job_id="8123",
            expected_study_fingerprint="a" * 64,
            expected_max_nodes=1,
            expected_remeasure_reps=5,
            expected_model="registered-model",
        )

    audit = json.loads((tmp_path / "shard_audit.json").read_text())
    assert any("study source fingerprint" in error for error in audit["errors"])


def test_aggregate_rejects_underfilled_scientific_run(tmp_path):
    tasks = ["gemm"]
    arms = list(ana.REGISTERED_ARMS)
    cells = ana.matrix_cells(tasks, arms, seed_base=0, seeds=1)
    for cell in cells:
        _write_matrix_shard(
            tmp_path,
            cell,
            node_count=(0 if cell["arm"] == "evidence_only" else 1),
        )

    with pytest.raises(ana.ShardAggregationError):
        ana.aggregate_shards(
            tmp_path,
            tasks=tasks,
            arms=arms,
            seed_base=0,
            seeds=1,
            expected_array_job_id="8123",
            expected_study_fingerprint="a" * 64,
            expected_max_nodes=1,
            expected_remeasure_reps=5,
            expected_model="registered-model",
        )

    audit = json.loads((tmp_path / "shard_audit.json").read_text())
    assert any(
        "0/1 readable node reports" in error for error in audit["errors"]
    )


def test_lineage_stats_parent_child_improve_break(tmp_path):
    """REGRESSION: lineage_stats reads tree.json and compares each child to its
    parent. A refactor of the validity rule left a stale `g` reference in the
    parent/child branch, so the whole function raised NameError on ANY run with a
    readable tree.json — but no unit test exercised that path, so it shipped and
    only surfaced on real smoke data. This drives the tree.json branch directly."""
    run = tmp_path / "experiments" / "run_x"
    ck = tmp_path / "checkpoints" / "run_x"
    ck.mkdir(parents=True)
    tree = {"nodes": [
        {"id": "root", "parent_id": None,
         "metrics": {"valid_geomean_speedup": 2.0}, "self_assessment": {"succeeded": True}},
        {"id": "c_up", "parent_id": "root",           # child improved on parent
         "metrics": {"valid_geomean_speedup": 3.0}, "self_assessment": {"succeeded": True}},
        {"id": "c_break", "parent_id": "root",         # child went invalid
         "metrics": {"valid_geomean_speedup": 0.0}, "self_assessment": {"succeeded": False}},
    ]}
    (ck / "tree.json").write_text(json.dumps(tree))
    run.mkdir(parents=True)

    out = ana.lineage_stats(str(run))          # must NOT raise
    assert out["n_nodes"] == 3
    assert out["n_valid"] == 2                  # root + c_up (c_break is invalid)
    assert out["child_total"] == 2             # both children have a valid parent
    assert out["child_improve"] == 1           # c_up beat the parent
    assert out["child_break"] == 1             # c_break went invalid


def test_lineage_stats_score_axis_zero_child_is_not_a_break(tmp_path):
    """A score-axis child that legitimately scored 0.0 (succeeded=True) is a VALID
    child, not a break — the validity fix must reach the parent/child comparison."""
    run = tmp_path / "experiments" / "run_s"
    ck = tmp_path / "checkpoints" / "run_s"
    ck.mkdir(parents=True)
    tree = {"nodes": [
        {"id": "root", "parent_id": None,
         "metrics": {"valid_geomean_speedup": 0.6}, "self_assessment": {"succeeded": True}},
        {"id": "c0", "parent_id": "root",              # measured 0.0 but valid
         "metrics": {"valid_geomean_speedup": 0.0}, "self_assessment": {"succeeded": True}},
    ]}
    (ck / "tree.json").write_text(json.dumps(tree))
    run.mkdir(parents=True)
    out = ana.lineage_stats(str(run))
    assert out["n_valid"] == 2                  # the 0.0 child is valid
    assert out["child_break"] == 0             # and is NOT counted as a break


def test_lineage_stats_excludes_sterile_from_parent_child_rates(tmp_path):
    run = tmp_path / "experiments" / "run_sterile"
    ck = tmp_path / "checkpoints" / "run_sterile"
    ck.mkdir(parents=True)
    tree = {"nodes": [
        {
            "id": "root",
            "parent_id": None,
            "metrics": {"valid_geomean_speedup": 2.0},
            "evaluation_status": "valid",
            "has_real_data": True,
        },
        {
            "id": "noop",
            "parent_id": "root",
            "metrics": {
                "valid_geomean_speedup": 20.0,
                "_sterile": True,
            },
            "evaluation_status": "valid",
            "has_real_data": True,
        },
    ]}
    (ck / "tree.json").write_text(json.dumps(tree))
    run.mkdir(parents=True)

    out = ana.lineage_stats(str(run))

    assert out["n_nodes"] == 2
    assert out["n_valid"] == 2
    assert out["child_total"] == 0
    assert out["child_improve"] == 0
    assert out["child_break"] == 0


def test_unscored_run_is_infra_not_measurement_invalid(tmp_path):
    """REGRESSION (real outage, 2026-07-27): a Cerebras payment error let jobs exit
    rc=0 while EVERY node failed at the root with a null score. run_outcome scored
    those runs 0 and they entered the analysis, manufacturing a spurious harm signal
    (validity 86/82/68%) that was purely the outage's timing across arms. Such a run
    (evaluator never scored ANY node) must be detected as an infrastructure failure,
    not a measured 0."""
    # (a) API-outage run: single root, status=failed, _scientific_score null
    api = tmp_path / "run_api"
    nd = api / "node_root"; nd.mkdir(parents=True)
    (nd / "node_report.json").write_text(json.dumps({
        "node_id": "root", "status": "failed",
        "metrics": {"_scientific_score": None},
        "self_assessment": {"succeeded": False}, "evaluator_reason": ""}))
    assert ana.run_scored_any(str(api)) is False   # no node was ever scored

    # (b) genuine measurement-invalid run: evaluator DID run, scored 0
    meas = tmp_path / "run_meas"
    nd2 = meas / "node_root"; nd2.mkdir(parents=True)
    (nd2 / "node_report.json").write_text(json.dumps({
        "node_id": "root", "status": "success",
        "metrics": {"_scientific_score": 0.0, "valid_geomean_speedup": 0.0},
        "self_assessment": {"succeeded": False},
        "evaluator_reason": "compile failed: candidate.c:1: error"}))
    assert ana.run_scored_any(str(meas)) is True    # the evaluator scored it (0) — a real measurement

    # (c) valid run
    ok = tmp_path / "run_ok"
    nd3 = ok / "node_root"; nd3.mkdir(parents=True)
    (nd3 / "node_report.json").write_text(json.dumps({
        "node_id": "root", "status": "success",
        "metrics": {"_scientific_score": 0.4, "valid_geomean_speedup": 20.0},
        "self_assessment": {"succeeded": True}}))
    assert ana.run_scored_any(str(ok)) is True

    # (d) evaluator exception: a finite internal ranking fallback is explicitly
    # typed infrastructure and must never turn into a scientific zero.
    infra = tmp_path / "run_infra"
    nd4 = infra / "node_root"; nd4.mkdir(parents=True)
    (nd4 / "node_report.json").write_text(json.dumps({
        "node_id": "root",
        "metrics": {"_scientific_score": 0.0, "valid_geomean_speedup": 0.0},
        "evaluation_status": "infrastructure_error",
        "measurement_valid": False,
    }))
    assert ana.run_scored_any(str(infra)) is False

    # (e) A typed search-time infrastructure error cannot be masked by a stale or
    # contradictory final-measurement artifact.
    (infra / "final_measurement.json").write_text(json.dumps({
        "evaluation_status": "valid",
        "measurement_valid": True,
        "scientific_score": 3.0,
    }))
    assert ana.run_scored_any(str(infra)) is False


def test_paired_analysis_groups_children_by_handoff_mode(tmp_path):
    run = tmp_path / "run_paired"
    root = run / "node_root"
    root.mkdir(parents=True)
    (root / "node_report.json").write_text(json.dumps({
        "node_id": "node_root",
        "parent_id": None,
        "metrics": {"_scientific_score": 0.2, "valid_geomean_speedup": 10.0},
        "self_assessment": {"succeeded": True},
    }))
    for mode, score, ok in (
        ("code_only", 9.0, True),
        ("evidence_only", 12.0, True),
        ("evidence_plus_reflection", 0.0, False),
    ):
        nd = run / f"node_{mode}"
        nd.mkdir()
        (nd / "node_report.json").write_text(json.dumps({
            "node_id": f"node_{mode}",
            "parent_id": "node_root",
            "handoff_mode": mode,
            "metrics": {"_scientific_score": score / 20.0, "valid_geomean_speedup": score},
            "self_assessment": {"succeeded": ok},
        }))

    rows = [{"run_dir": str(run), "paired_modes": [
        "code_only", "evidence_only", "evidence_plus_reflection",
    ]}]
    assert ana.analyze_paired(rows, tmp_path, "gemm", False) == 0
    out = json.loads((tmp_path / "analysis.json").read_text())
    assert out["paired"] is True
    assert out["n_complete_parent_blocks"] == 1
    assert out["arms"]["evidence_only"]["improve_rate"] == 1.0
    assert out["arms"]["evidence_plus_reflection"]["break_rate"] == 1.0
    assert out["arms"]["evidence_plus_reflection"]["center"] is None
