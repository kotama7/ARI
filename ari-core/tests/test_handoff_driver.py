"""Study-driver controls that must remain auditable and counterbalanced."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_DRIVER_PATH = _ROOT / "workspace" / "run_handoff_ablation.py"
_SBATCH_PATH = _ROOT / "workspace" / "submit_handoff_ablation_sbatch.sh"
_ARRAY_PATH = _ROOT / "workspace" / "submit_handoff_ablation_array.sh"
_SPEC = importlib.util.spec_from_file_location("handoff_driver", _DRIVER_PATH)
driver = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(driver)


def test_measurement_environment_serializes_reference_blas_and_pins_openmp():
    expected = {
        "OPENBLAS_NUM_THREADS": "1",
        "GOTO_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "BLIS_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "OMP_PROC_BIND": "spread",
        "OMP_PLACES": "cores",
        "OMP_DYNAMIC": "FALSE",
        "ARI_HARNESS_RUN_TIMEOUT_S": "120",
    }
    assert driver._MEASUREMENT_ENV == expected
    assert {key: driver._FIXED[key] for key in expected} == expected
    assert driver._FIXED["ARI_MAX_REACT"] == "25"
    assert driver._FIXED["ARI_MAX_DEPTH"] == "10"
    sbatch = _SBATCH_PATH.read_text()
    for key, value in expected.items():
        assert f"export {key}={value}" in sbatch
    assert 'export ARI_MAX_REACT="${ARI_MAX_REACT:-25}"' in sbatch
    assert "export ARI_HARNESS_RUN_TIMEOUT_S=120" in sbatch


def test_study_fingerprint_covers_controls_and_registered_harnesses():
    manifest = driver.study_source_manifest()
    assert "workspace/run_handoff_ablation.py" in manifest
    assert "workspace/analyze_handoff_ablation.py" in manifest
    assert "ari-core/ari/agent/loop.py" in manifest
    for task in ("gemm", "spmm", "stencil"):
        assert f"workspace/harnesses/{task}/harness.toml" in manifest
        assert f"workspace/harnesses/{task}/{task}_harness.py" in manifest
    fingerprint = driver.study_source_fingerprint()
    assert len(fingerprint) == 64
    assert fingerprint == driver.study_source_fingerprint()


def test_invalid_case_stops_remaining_harness_cases(monkeypatch):
    monkeypatch.setenv("ARI_WORKSPACE", str(_ROOT / "workspace"))
    monkeypatch.setenv("ARI_HARNESS_RUN_TIMEOUT_S", "7.5")

    def candidate_fails(kind, *_args):
        if kind == "candidate":
            raise RuntimeError("candidate hung")
        raise AssertionError("baseline must not run after candidate-first failure")

    from ari.harness_registry import load

    cases = (
        ("gemm", {
            "shapes": ((2, 2, 2), (3, 3, 3)),
        }),
        ("spmm", {
            "families": ("uniform", "banded"),
            "n": 8,
            "k": 2,
        }),
        ("stencil", {
            "shapes": ((4, 4, 4, 1), (5, 4, 4, 1)),
        }),
    )
    for task, kwargs in cases:
        harness = load(task)
        timeout_fn = harness._measure_node.__globals__["_run_timeout_seconds"]
        assert timeout_fn() == 7.5
        result = harness._measure_node(
            "unused",
            run_kernel=candidate_fails,
            reps=1,
            seed=0,
            **kwargs,
        )
        assert result["evaluation_status"] == "candidate_invalid"
        assert len(result["families"]) == 1


def test_arm_order_is_exactly_cyclically_counterbalanced():
    arms = ["code_only", "evidence_only", "evidence_plus_reflection"]
    orders = [driver._counterbalanced_arms(arms, seed) for seed in range(3)]
    assert orders == [
        ["code_only", "evidence_only", "evidence_plus_reflection"],
        ["evidence_only", "evidence_plus_reflection", "code_only"],
        ["evidence_plus_reflection", "code_only", "evidence_only"],
    ]
    for position in range(3):
        assert {order[position] for order in orders} == set(arms)


def test_array_submission_is_one_registered_matrix_cell_per_worker():
    worker = _SBATCH_PATH.read_text()
    launcher = _ARRAY_PATH.read_text()

    assert '--shard-arm "$ARM"' in worker
    assert "--task \"$TASK\"" in worker
    assert "--seeds 1" in worker
    assert "Refusing the obsolete serial 3-task x 3-arm submission" in worker
    assert "srun" not in worker
    assert '--array="$ARRAY_SPEC"' in launcher
    assert '--dependency="afterany:$ARRAY_JOB"' in launcher
    assert "TOTAL=$((SEEDS * 9))" in launcher
    assert "ARI_STUDY_SOURCE_FINGERPRINT=$STUDY_FINGERPRINT" in launcher
    assert '--expected-study-fingerprint "$STUDY_FINGERPRINT"' in launcher
    assert '--expected-max-nodes "$MAX_NODES"' in launcher
    assert '--expected-remeasure-reps "$REMEASURE_REPS"' in launcher
    assert '--expected-model "$MODEL"' in launcher
    assert "source_integrity.json" in worker
    assert '"failed_before"' in worker
    assert '"failed_after"' in worker


def test_registered_array_design_cannot_be_overridden_by_ambient_env():
    launcher = _ARRAY_PATH.read_text()
    for ambient in (
        "ARI_SEEDS",
        "ARI_SEED_BASE",
        "ARI_MAX_NODES",
        "ARI_REMEASURE_REPS",
        "ARI_LARGE_MODEL",
    ):
        assert f"${{{ambient}:-" not in launcher
    for assignment in (
        "SEEDS=30",
        "SEED_BASE=0",
        "MAX_NODES=10",
        "REMEASURE_REPS=15",
        'MODEL="cerebras/gpt-oss-120b"',
    ):
        assert assignment in launcher


def test_manifest_records_slurm_allocation(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.jsonl"
    monkeypatch.setenv("SLURM_JOB_ID", "123_4")
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "123")
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "4")
    monkeypatch.setenv("SLURM_JOB_PARTITION", "fx700")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "fx29")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "48")
    monkeypatch.setenv("ARI_STUDY_SOURCE_FINGERPRINT", "f" * 64)

    driver._record(manifest, task="gemm", arm="evidence_only", seed=0)

    row = json.loads(manifest.read_text())
    allocation = row["allocation"]
    assert allocation["slurm_array_job_id"] == "123"
    assert allocation["slurm_array_task_id"] == "4"
    assert allocation["slurm_partition"] == "fx700"
    assert allocation["slurm_nodelist"] == "fx29"
    assert allocation["slurm_cpus_per_task"] == "48"
    assert row["study_source_fingerprint"] == "f" * 64


def test_unscored_run_final_measurement_is_infrastructure(tmp_path):
    run = tmp_path / "run"
    node = run / "node_root"
    node.mkdir(parents=True)
    (node / "node_report.json").write_text(json.dumps({
        "node_id": "node_root",
        "status": "failed",
        "metrics": {"_scientific_score": None},
        "evaluation_status": "",
    }))

    result = driver._write_final_measurement(
        str(run), task="gemm", seed=3, reps=5)

    payload = json.loads((run / "final_measurement.json").read_text())
    assert result["status"] == "infrastructure_error"
    assert payload["evaluation_status"] == "infrastructure_error"
    assert payload["scientific_score"] is None


def test_underfilled_search_is_infrastructure(tmp_path):
    run = tmp_path / "run"
    node = run / "node_root"
    node.mkdir(parents=True)
    (node / "node_report.json").write_text(json.dumps({
        "node_id": "node_root",
        "status": "success",
        "metrics": {
            "_scientific_score": 1.0,
            "valid_geomean_speedup": 1.0,
        },
        "evaluation_status": "valid",
        "measurement_valid": True,
    }))

    result = driver._write_final_measurement(
        str(run), task="gemm", seed=3, reps=5, expected_nodes=2)

    payload = json.loads((run / "final_measurement.json").read_text())
    assert result["status"] == "infrastructure_error"
    assert payload["expected_search_nodes"] == 2
    assert payload["observed_search_nodes"] == 1
    assert "1/2 readable node reports" in payload["reason"]


def test_best_valid_node_excludes_sterile_noop(tmp_path):
    run = tmp_path / "run"
    genuine = run / "node_genuine"
    sterile = run / "node_sterile"
    genuine.mkdir(parents=True)
    sterile.mkdir()
    (genuine / "node_report.json").write_text(json.dumps({
        "node_id": "node_genuine",
        "measurement_valid": True,
        "metrics": {"valid_geomean_speedup": 4.0},
    }))
    (sterile / "node_report.json").write_text(json.dumps({
        "node_id": "node_sterile",
        "measurement_valid": True,
        "metrics": {
            "valid_geomean_speedup": 40.0,
            "_sterile": True,
        },
    }))

    node_dir, report, score = driver._best_valid_node(str(run))

    assert node_dir == genuine
    assert report["node_id"] == "node_genuine"
    assert score == 4.0


def test_study_bundle_contains_ignored_harness_and_exact_controls(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("ARI_WORKSPACE", str(_ROOT / "workspace"))
    args = argparse.Namespace(
        mode="mvp",
        arms=["code_only", "evidence_only", "evidence_plus_reflection"],
        seed_base=0,
        seeds=1,
        max_nodes=10,
        remeasure_reps=5,
        model="pilot",
        large_model="cerebras/gpt-oss-120b",
        scorer="deterministic",
    )
    digest = driver._write_study_bundle(
        tmp_path, task="gemm", args=args)
    bundle = tmp_path / "study_bundle"
    manifest = json.loads((bundle / "manifest.json").read_text())
    config = json.loads((bundle / "study_configuration.json").read_text())

    names = set(manifest["files"])
    assert len(digest) == 64
    assert "harness/gemm/harness.toml" in names
    assert "harness/gemm/gemm_harness.py" in names
    assert "source/workspace/run_handoff_ablation.py" in names
    assert "source/ari-core/ari/cli/bfts_loop.py" in names
    assert "source/ari-core/ari/orchestrator/bfts.py" in names
    assert (
        "source/ari-core/ari/evaluator/deterministic_evaluator.py" in names
    )
    assert config["harness"]["task"] == "gemm"
    assert config["max_react"] == "25"
    for key, value in driver._MEASUREMENT_ENV.items():
        assert config["fixed_env"][key] == value
