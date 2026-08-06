"""Study-driver controls that must remain auditable and counterbalanced."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_DRIVER_PATH = _ROOT / "workspace" / "run_handoff_ablation.py"
_SBATCH_PATH = _ROOT / "workspace" / "submit_handoff_ablation_sbatch.sh"
_ARRAY_PATH = _ROOT / "workspace" / "submit_handoff_ablation_array.sh"
# THE CAMPAIGN IS NOT ARI. This file tests a driver that lives in the untracked
# workspace tree, and it executes that driver at IMPORT time -- so on a checkout
# without it, or once that tree is retired, the whole module failed to COLLECT
# and took the run down with it rather than reporting a skip. Its two siblings
# (test_analyze_handoff, test_edit_lineage) already guard the same way.
if not _DRIVER_PATH.is_file():
    pytest.skip("run_handoff_ablation.py not found (workspace/ campaign absent)",
                allow_module_level=True)
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


def test_the_observed_environment_is_recorded_separately_from_the_forced_one(
        monkeypatch):
    """`_FIXED` is what the study SETS; this is what was actually there.

    They are not the same question and must not collapse into one field. The
    forced set answers "what did we intend"; the observed record answers "what
    were the conditions" -- and only the second can catch a variable nobody
    thought to force. XOS_MMM_L_PAGING_POLICY is the case: the manifest used to
    name 24 variables explicitly and that one was not among them, having been
    found later and measured to move the same frozen source by 5.9x.
    """
    monkeypatch.setenv("XOS_MMM_L_PAGING_POLICY", "demand:demand:demand")
    env = driver._measurement_environment("stencil")
    assert env["variables"].get("XOS_MMM_L_PAGING_POLICY") == "demand:demand:demand", (
        "the observed record must pick up a variable no one enumerated; that is "
        "the whole difference between it and _FIXED")
    assert len(env.get("sha256") or "") == 64
    src = _DRIVER_PATH.read_text() if "_DRIVER_PATH" in globals() else (
        pathlib.Path(driver.__file__).read_text())
    assert '"fixed_env": dict(_FIXED)' in src
    assert '"measurement_environment": _measurement_environment(task)' in src, (
        "the manifest must carry the OBSERVED record, keyed to the task that is "
        "actually scoring")


def test_the_environment_record_survives_an_ambient_workspace_pointing_elsewhere(
        monkeypatch):
    """The manifest describes the tree it was written from, not $ARI_WORKSPACE.

    The fallback originally asked the registry, which resolves through
    ARI_WORKSPACE. With that variable pointing at another tree the capture came
    back EMPTY -- and an empty environment record is indistinguishable from a
    clean environment, so the manifest would have quietly asserted conditions
    nobody observed.
    """
    monkeypatch.setenv("ARI_WORKSPACE", "/nonexistent-other-workspace")
    env = driver._measurement_environment("erfc")
    assert "capture_error" not in env, (
        "an ambient ARI_WORKSPACE emptied the capture; the manifest must read "
        "the tree it is describing")
    assert len(env.get("sha256") or "") == 64


def test_every_registered_harness_captures_its_own_environment():
    """Borrowing is now the exception, not the norm.

    This test was originally written the other way round: erfc exposed no
    capture and the record it borrowed had to be labelled. Accuracy tasks turn
    out to need the record MORE than timing ones -- a candidate built with
    -ffast-math answers a different question about erfc and still reports a pass
    fraction -- so every harness captures its own now.
    """
    from ari.harness_registry import registered_harnesses
    for task in registered_harnesses():
        env = driver._measurement_environment(task)
        assert env["captured_via"] == f"{task}_harness.measurement_environment", (
            f"{task} borrowed {env.get('captured_via')}: its own harness should "
            f"expose measurement_environment")
        assert "captured_via_note" not in env


def test_a_borrowed_record_is_labelled_as_borrowed():
    """The fallback must never assert conditions it did not observe."""
    borrowed = driver._measurement_environment("no_such_task")
    assert borrowed["captured_via"] != "no_such_task_harness.measurement_environment"
    assert "captured_via_note" in borrowed, (
        "this is some other harness's view of the machine; recording it "
        "unlabelled would assert conditions that were never observed for the "
        "scoring task")
    assert len(borrowed.get("sha256") or "") == 64


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


def test_preflight_is_the_confirmatory_design_at_one_seed():
    """A pre-flight must exercise the SCORED configuration, not a reduced one.

    --smoke is the only other one-seed mode and it also swaps in 128^3/nt=10
    problem sizes, so it can exercise the pipeline or the scored configuration
    but never both. It is a mode rather than an ARI_SEEDS override because the
    test above forbids reading the design from the environment, and that
    prohibition is worth keeping: what ran must be readable from
    launch_contract.json alone.
    """
    launcher = _ARRAY_PATH.read_text()
    assert "--preflight) MODE=preflight ;;" in launcher
    block = launcher.split('elif [[ "$MODE" == "preflight" ]]; then', 1)
    assert len(block) == 2, "the preflight branch is gone"
    body = block[1].split("else", 1)[0]
    # one seed, but everything else identical to --full
    assert "SEEDS=1" in body
    assert "REMEASURE_REPS=15" in body
    assert "MATRIX_SMOKE=0" in body, (
        "preflight must NOT enable the reduced smoke problem sizes")


def test_resume_reruns_only_incomplete_cells_from_the_frozen_contract():
    """Recovery from a partial campaign must not become a different experiment.

    The collector refuses a partial grid and nothing below it retries a cell, so
    one terminal API error in 270 used to mean finding the cell by hand. --resume
    does that mechanically, but it has to take the design from the ORIGINAL
    launch_contract.json rather than from a mode branch, and it has to refuse
    outright when the source tree has moved since -- otherwise the resubmitted
    cells carry a different fingerprint from their siblings and the collector
    throws the whole campaign away AFTER the compute has been spent.
    """
    launcher = _ARRAY_PATH.read_text()
    assert '"--resume"' in launcher

    # design comes from the contract, not from the mode branches
    for key in ("mode)", "seeds)", "seed_base)", "max_nodes)",
                "remeasure_reps)", "model)"):
        assert key in launcher, f"resume does not read {key} back from the contract"

    # the array spec is restricted to the incomplete indices
    assert 'ARRAY_SPEC="${RESUME_INDICES}%${CONCURRENCY}"' in launcher
    assert "find_incomplete_cells.py" in launcher

    # and a moved source tree aborts, restoring the contract the fingerprint
    # computation overwrote as a side effect
    assert '"$STUDY_FINGERPRINT" != "$RESUMED_FINGERPRINT"' in launcher
    assert 'mv -f "$ROOT/launch_contract.json.resume_backup"' in launcher
    assert "exit 3" in launcher


def test_launcher_refuses_a_campaign_whose_cache_will_not_fit():
    """The seed count multiplies the oracle cache, and a pre-flight cannot show it.

    ``remeasure_seed = run_seed + 1_000_000`` means every run seed gets its own
    15 problems per shape, so the cache grows linearly in seeds: 26.7 GB for one,
    ~800 GB for thirty, against ~694 GB of quota. Running into the quota part-way
    through is the worst available failure — writes fail, oracles are recomputed
    instead of read, and only the runs late in the campaign time out, so the
    damage is unbalanced across seeds.
    """
    launcher = _ARRAY_PATH.read_text()
    assert "check_cache_capacity.py" in launcher
    assert 'ARI_SKIP_CAPACITY_CHECK' in launcher, "the check must be overridable"
    assert "exit 4" in launcher
    # and it must run BEFORE anything is submitted
    assert launcher.index("check_cache_capacity.py") < launcher.index("sbatch --parsable")


def test_collector_accepts_the_set_of_array_jobs_this_root_was_submitted_under():
    """One id per campaign stopped being true the moment resume existed.

    Recovering a dead cell resubmits it under a NEW Slurm array job into the same
    root. With a single expected id every shard is then wrong — the resumed one
    against the original, or the original 269 against the resumed one. Found by
    killing a cell and running the recovery for real: the collector went from 1
    error to 8. The launcher therefore accumulates the ids it submitted for this
    root, and starts the list fresh for anything that is not a resume, so a reused
    root cannot inherit an unrelated campaign's ids.
    """
    launcher = _ARRAY_PATH.read_text()
    assert 'echo "$ARRAY_JOB" >> "$ROOT/array_job_ids.txt"' in launcher
    assert 'echo "$ARRAY_JOB" > "$ROOT/array_job_ids.txt"' in launcher
    assert '--expected-array-job-id "$ARRAY_JOB_SET"' in launcher

    analyzer = (pathlib.Path(_ARRAY_PATH).parent / "analyze_handoff_ablation.py").read_text()
    assert "accepted = {" in analyzer
    assert "array_job_id not in accepted" in analyzer


def test_preflight_is_not_recorded_as_a_confirmatory_analysis():
    """One seed cannot support the confirmatory claim, and it prints like one.

    With n=1 every contrast comes out p=1 with a zero-width CI, so a preflight
    root left on ``analysis_role: confirmatory`` both reads like a result and is
    filed as one. The collector must therefore pass --descriptive-only for
    --preflight as well as --smoke.
    """
    launcher = _ARRAY_PATH.read_text()
    assert 'if [[ "$MODE" == "smoke" || "$MODE" == "preflight" ]]; then' in launcher
    guard = launcher.split('|| "$MODE" == "preflight" ]]; then', 1)[1]
    assert guard.lstrip().startswith("COLLECT_ARGS+=(--descriptive-only)")


def test_manifest_records_slurm_allocation(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.jsonl"
    monkeypatch.setenv("SLURM_JOB_ID", "123_4")
    monkeypatch.setenv("SLURM_ARRAY_JOB_ID", "123")
    monkeypatch.setenv("SLURM_ARRAY_TASK_ID", "4")
    # A neutral fixture value: the test asserts that whatever Slurm reports is
    # recorded verbatim, and naming this site's partition here would put site
    # detail in the repository for no test-coverage gain.
    monkeypatch.setenv("SLURM_JOB_PARTITION", "testpart")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "testnode01")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "48")
    monkeypatch.setenv("ARI_STUDY_SOURCE_FINGERPRINT", "f" * 64)

    driver._record(manifest, task="gemm", arm="evidence_only", seed=0)

    row = json.loads(manifest.read_text())
    allocation = row["allocation"]
    assert allocation["slurm_array_job_id"] == "123"
    assert allocation["slurm_array_task_id"] == "4"
    assert allocation["slurm_partition"] == "testpart"
    assert allocation["slurm_nodelist"] == "testnode01"
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


def test_a_rerun_replaces_its_own_manifest_row(tmp_path):
    """`--resume` re-runs the cells that did not finish. The manifest was opened
    in append mode, so a resumed cell left TWO rows in its shard manifest, and
    the collector requires exactly one per shard ("expected exactly one row,
    found 2") — the recovery path made the cells it recovered unusable.

    Identity is (task, arm, seed), which is what the collector keys on; other
    cells in the same file must be untouched.
    """
    manifest = tmp_path / "manifest.jsonl"
    driver._record(manifest, task="gemm", arm="code_only", seed=0, rc=86)
    driver._record(manifest, task="gemm", arm="evidence_only", seed=0, rc=0)
    driver._record(manifest, task="gemm", arm="code_only", seed=0, rc=0)  # the resume
    rows = [json.loads(x) for x in manifest.read_text().splitlines() if x.strip()]
    assert len(rows) == 2, rows
    by_arm = {r["arm"]: r for r in rows}
    assert by_arm["code_only"]["rc"] == 0, "the resumed row must win"
    assert by_arm["evidence_only"]["rc"] == 0, "a different cell must survive"


def test_a_rerun_never_drops_an_unreadable_row(tmp_path):
    """Rewriting the file must not become a way to lose evidence: a line this
    code cannot parse is preserved, so a corrupt manifest is visible to the
    collector rather than quietly cleaned up by a re-run."""
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("{not json\n")
    driver._record(manifest, task="gemm", arm="code_only", seed=0, rc=0)
    lines = [x for x in manifest.read_text().splitlines() if x.strip()]
    assert lines[0] == "{not json"
    assert len(lines) == 2


def test_the_worker_checks_for_files_added_since_launch():
    """The frozen digest walks the RECORDED path list, so it sees modification
    and deletion and is blind to ADDITION by construction — a new file under a
    pinned prefix changes what the study is made of and changes no recorded
    digest. The worker must therefore re-enumerate, and must report an
    unanswerable check as unknown rather than as zero."""
    text = _SBATCH_PATH.read_text()
    assert "from workspace.run_handoff_ablation import study_source_manifest" in text
    assert 'print("unknown")' in text, (
        "a re-enumeration that could not run must not report zero additions")
    assert "failed_before_added" in text
