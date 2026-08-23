"""RQGM Task 13 — offline smoke runner + ablation report
(docs/guides/rqgm_evaluation.md §Test tiers, Tier 2 (CI-hard, offline
smoke); §Running).

``run_smoke`` completes in seconds with stub components (no LLM, no network,
no subprocess), writes per-run ``rqgm_eval_metrics.json`` and the campaign
``ablation_report.{json,md}`` into the ``workspace/rqgm_eval/<eval_id>``-
shaped destination, keeps the B0 checkpoint free of RQGM artifacts (the
artifact-contract regression guard), detects scripted injections within
their declared latency through the real Task 06 record path, and degrades —
never crashes — when a double misbehaves.
"""

from __future__ import annotations

import json

from ari.rqgm.evaluation.injection import (
    INJECTION_PROVENANCE_FILENAME,
    load_injection_specs,
)
from ari.rqgm.evaluation.metrics import METRIC_REPORT_FILENAME
from ari.rqgm.evaluation.smoke import (
    ABLATION_REPORT_JSON,
    ABLATION_REPORT_MD,
    SMOKE_DEFAULT_CONDITIONS,
    build_ablation_report,
    render_ablation_markdown,
    run_condition_smoke,
    run_smoke,
)

_ALL_SPECS = load_injection_specs()["injections"]


def _spec(injection_id: str) -> dict:
    return next(s for s in _ALL_SPECS if s["injection_id"] == injection_id)


# ── the deletion-criteria smoke campaign ({B0, B3}, 1 seed) ──────────────────


def test_smoke_campaign_writes_reports_offline(tmp_path):
    report = run_smoke(tmp_path, eval_id="ci_smoke")
    assert SMOKE_DEFAULT_CONDITIONS == ("B0", "B3")
    assert set(report["conditions"]) == {"B0", "B3"}
    assert report["eval_id"] == "ci_smoke"
    assert (tmp_path / ABLATION_REPORT_JSON).is_file()
    assert (tmp_path / ABLATION_REPORT_MD).is_file()
    for cid in ("B0", "B3"):
        run_dir = tmp_path / "runs" / f"{cid}_s11"
        assert (run_dir / METRIC_REPORT_FILENAME).is_file()
        assert (run_dir / "workflow.yaml").is_file()
    assert "B3-B0" in report["deltas"]


def test_b0_smoke_checkpoint_has_no_rqgm_artifacts(tmp_path):
    """The B0 regression guard: with RQGM code present, a simple_bfts run
    directory carries only the baseline artifact contract — the harness's
    own metric report is the single (registered) addition."""
    run_smoke(tmp_path, conditions=("B0",), eval_id="b0_guard")
    run_dir = tmp_path / "runs" / "B0_s11"
    files = sorted(
        str(p.relative_to(run_dir))
        for p in run_dir.rglob("*")
        if p.is_file()
    )
    assert files == [
        "experiments/smoke_n0/node_report.json",
        "experiments/smoke_n1/node_report.json",
        "experiments/smoke_n2/node_report.json",
        "meta.json",
        METRIC_REPORT_FILENAME,
        "tree.json",
        "workflow.yaml",
    ]
    assert not (run_dir / "proposals").exists()
    assert not (run_dir / "rqgm_audit.jsonl").exists()
    assert not (run_dir / "rqgm_adversarial_cases.jsonl").exists()


def test_rqgm_condition_smoke_produces_proposal_records(tmp_path):
    report = run_condition_smoke(tmp_path, "B3")
    run_dir = tmp_path / "runs" / "B3_s11"
    lines = (
        run_dir / "proposals" / "proposal_records.jsonl"
    ).read_text().splitlines()
    assert len(lines) == 3
    assert report["metrics"]["proposal_to_executable_rate"]["value"] == 1.0
    assert report["metrics"]["best_valid_scientific_score"]["value"] == 0.7


# ── scripted injections through the real detection path ──────────────────────


def test_b4_scripted_injection_detected_within_latency(tmp_path):
    specs = [_spec("eval_inj_004_adversary_overreach"),
             _spec("eval_inj_005_judge_bias")]
    report = run_condition_smoke(tmp_path, "B4", injections=specs)
    run_dir = tmp_path / "runs" / "B4_s11"

    # Provenance: an injected run can never be mistaken for a real one.
    marker = json.loads(
        (run_dir / INJECTION_PROVENANCE_FILENAME).read_text()
    )
    assert marker["injection_ids"] == [
        "eval_inj_004_adversary_overreach", "eval_inj_005_judge_bias",
    ]

    # Detection records appear in the SAME epoch as the attack — within the
    # declared max_latency_epochs (1) for both specs.
    cases = [
        json.loads(line)
        for line in (
            run_dir / "rqgm_adversarial_cases.jsonl"
        ).read_text().splitlines()
    ]
    attacks = [c for c in cases if c["record_type"] == "raw_attack"]
    validated = [c for c in cases if c["record_type"] == "validated_attack"]
    assert attacks and validated
    attack_epochs = {a["record_id"]: a["epoch_id"] for a in attacks}
    for record in validated:
        assert record["epoch_id"] == attack_epochs[record["raw_attack_id"]]

    # The overreach signal: every artifact attacked, and validated-attack
    # precision collapses to 0 against the ground-truth labels (plan §5.3).
    assert len(attacks) == 3
    entry = report["metrics"]["validated_attack_precision"]
    assert entry["applicable"] is True
    assert entry["value"] == 0.0
    assert report["smoke_summary"]["validated_attacks"] == 3


def test_failing_judge_double_degrades_not_crashes(tmp_path):
    specs = [_spec("eval_inj_004_adversary_overreach"),
             dict(_spec("eval_inj_005_judge_bias"),
                  double="never_validate")]
    report = run_condition_smoke(tmp_path, "B4", injections=specs)
    # Attacks lapse unadjudicated: zero validated records, normal completion.
    assert report["smoke_summary"]["validated_attacks"] == 0
    run_dir = tmp_path / "runs" / "B4_s11"
    cases = [
        json.loads(line)
        for line in (
            run_dir / "rqgm_adversarial_cases.jsonl"
        ).read_text().splitlines()
    ]
    assert not [c for c in cases if c["record_type"] == "validated_attack"]
    assert [c for c in cases if c["record_type"] == "judgment_record"]


def test_virsci_off_condition_asserted_virsci_free(tmp_path):
    """Plan 13 §5.2: a VirSci-off run whose checkpoint carries VirSci
    artifacts fails the harness assertion instead of polluting the
    contrast."""
    import pytest

    contaminated = tmp_path / "runs" / "B3_s11" / "virsci_logs"
    contaminated.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="VirSci-free"):
        run_condition_smoke(tmp_path, "B3")


def test_generator_and_mutator_stubs_audited(tmp_path):
    specs = [_spec("eval_inj_006_bad_generator"),
             _spec("eval_inj_008_bad_prompt_mutator")]
    report = run_condition_smoke(tmp_path, "B3", injections=specs)
    assert report["smoke_summary"]["rejected_proposals"] == 1
    assert report["smoke_summary"]["mutator_candidate_rejected"] is True
    run_dir = tmp_path / "runs" / "B3_s11"
    audit = [
        json.loads(line)
        for line in (run_dir / "rqgm_audit.jsonl").read_text().splitlines()
    ]
    events = {line["event_type"] for line in audit}
    assert "constitutional_violation" in events       # injection 6, latency 0
    assert "prompt_candidate_rejected" in events      # injection 8


# ── determinism (P2) ─────────────────────────────────────────────────────────


def test_smoke_report_is_byte_deterministic(tmp_path):
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    run_smoke(a_root, conditions=("B0", "B3"), eval_id="det")
    run_smoke(b_root, conditions=("B0", "B3"), eval_id="det")
    assert (a_root / ABLATION_REPORT_JSON).read_bytes() == \
        (b_root / ABLATION_REPORT_JSON).read_bytes()
    assert (a_root / ABLATION_REPORT_MD).read_bytes() == \
        (b_root / ABLATION_REPORT_MD).read_bytes()


# ── aggregation ──────────────────────────────────────────────────────────────


def _fake_report(cid, seed, score):
    return {
        "condition_id": cid, "seed": seed,
        "metrics": {"best_valid_scientific_score": {"value": score}},
    }


def test_build_ablation_report_medians_and_deltas():
    reports = [
        _fake_report("B0", 11, 0.5), _fake_report("B0", 12, 0.6),
        _fake_report("B0", 13, 0.7),
        _fake_report("B4", 11, 0.8), _fake_report("B4", 12, 0.9),
        _fake_report("B4", 13, 1.0),
        _fake_report("B3", 11, 0.6), _fake_report("B3", 12, 0.6),
        _fake_report("B3", 13, 0.6),
    ]
    report = build_ablation_report(reports, eval_id="agg")
    med = {
        cid: report["conditions"][cid]["median"][
            "best_valid_scientific_score"
        ]
        for cid in ("B0", "B3", "B4")
    }
    assert med == {"B0": 0.6, "B3": 0.6, "B4": 0.9}
    deltas = report["deltas"]
    assert deltas["B4-B3"]["best_valid_scientific_score"] == 0.9 - 0.6
    assert deltas["B4-B0"]["best_valid_scientific_score"] == 0.9 - 0.6
    assert "B8-B7" not in deltas                     # absent rungs skipped
    md = render_ablation_markdown(report)
    assert "| metric | B0 | B3 | B4 |" in md
    assert "B4-B3" in md


def test_build_ablation_report_keeps_per_experiment_rows():
    """Tier-3 runs the same seed across several benchmark experiments
    (§5.2 same-experiment-set policy): rows must not overwrite each other
    and the median pools seeds × experiments per condition."""
    reports = [
        dict(_fake_report("B0", 11, 0.5), experiment_id="spmm_roofline"),
        dict(_fake_report("B0", 11, 0.7), experiment_id="stencil_blocking"),
    ]
    report = build_ablation_report(reports)
    seeds = report["conditions"]["B0"]["seeds"]
    assert set(seeds) == {"11:spmm_roofline", "11:stencil_blocking"}
    assert report["conditions"]["B0"]["median"][
        "best_valid_scientific_score"
    ] == 0.6


def test_build_ablation_report_tolerates_missing_values():
    reports = [
        _fake_report("B0", 11, None), _fake_report("B3", 11, 0.5),
    ]
    report = build_ablation_report(reports)
    assert report["conditions"]["B0"]["median"][
        "best_valid_scientific_score"
    ] is None
    assert report["deltas"]["B3-B0"] == {}           # no numeric pair


def test_build_ablation_report_includes_paper_metrics_and_rqgm_pairs():
    reports = []
    for cid, value in (
        ("P0_hgm_h_fixed_critic", 0.4),
        ("P3_rqgm_full", 0.6),
        ("P4_constitutional_rqgm", 0.7),
    ):
        report = _fake_report(cid, 11, 0.5)
        report["paper"] = {
            "P1_paper_acceptance_rate": {"value": value},
        }
        reports.append(report)
    aggregate = build_ablation_report(reports)
    assert aggregate["conditions"]["P4_constitutional_rqgm"]["median"][
        "P1_paper_acceptance_rate"
    ] == 0.7
    assert aggregate["deltas"][
        "P3_rqgm_full-P0_hgm_h_fixed_critic"
    ]["P1_paper_acceptance_rate"] == 0.6 - 0.4
    assert aggregate["deltas"][
        "P4_constitutional_rqgm-P3_rqgm_full"
    ]["P1_paper_acceptance_rate"] == 0.7 - 0.6
