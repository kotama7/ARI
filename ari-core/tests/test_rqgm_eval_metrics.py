"""RQGM Task 13 — the thirteen evaluation metrics (docs/plans/ari_rqgm/13 §5.4/§9).

Each metric helper against hand-built fixtures with known answers;
absence tolerance (missing RQGM records ⇒ ``applicable: false``, never an
exception); determinism (two computations byte-identical); sterile/stale
exclusion in metric 1; the ``rqgm_eval_metrics.json`` envelope; META_FILES
registration; and the offline no-LLM/no-network import guard.

No test calls a real LLM; every input is a deterministic fixture (P2).
"""

from __future__ import annotations

import json
from pathlib import Path

from ari.paths import PathManager
from ari.rqgm.evaluation.metrics import (
    METRIC_KEYS,
    METRIC_REPORT_FILENAME,
    best_valid_scientific_score,
    compute_metric_report,
    cost_metrics,
    detection_rates,
    downstream_success_rate,
    frontier_contamination,
    proposal_to_executable_rate,
    recovery_after_erasure,
    wall_clock_metadata,
    write_metric_report,
)


def _node(nid, score=None, *, status="SUCCESS", sterile=False,
          has_real_data=True, epoch=None, valid=None):
    metrics = {}
    if score is not None:
        metrics["_scientific_score"] = score
    if sterile:
        metrics["_sterile"] = True
    if valid is not None:
        metrics["_valid_for_frontier"] = valid
    node = {"id": nid, "status": status, "has_real_data": has_real_data,
            "metrics": metrics}
    if epoch is not None:
        node["epoch_id"] = epoch
    return node


# ── metric 1: best valid scientific score ────────────────────────────────────


def test_metric1_max_over_valid_nodes():
    tree = {"nodes": [_node("a", 0.4), _node("b", 0.9), _node("c", 0.7)]}
    out = best_valid_scientific_score(tree, None)
    assert out["applicable"] is True
    assert out["value"] == 0.9
    assert out["evidence_refs"] == ["b"]


def test_metric1_sterile_clamp_is_authoritative():
    tree = {"nodes": [_node("a", 0.4), _node("bad", 0.99, sterile=True)]}
    assert best_valid_scientific_score(tree, None)["value"] == 0.4


def test_metric1_failed_nodes_excluded():
    tree = {"nodes": [_node("a", 0.4),
                      _node("f", 0.95, status="FAILED")]}
    assert best_valid_scientific_score(tree, None)["value"] == 0.4


def test_metric1_stale_and_invalid_excluded_under_task10_index():
    tree = {"nodes": [_node("a", 0.4), _node("s", 0.95), _node("i", 0.9)]}
    stale_index = {"stale": {"s": "ers_000001"},
                   "invalid_nodes": {"i": "ers_000001"}}
    out = best_valid_scientific_score(tree, stale_index)
    assert out["value"] == 0.4


def test_metric1_not_applicable_without_scores():
    out = best_valid_scientific_score({"nodes": [_node("a")]}, None)
    assert out["applicable"] is False
    assert out["value"] is None


# ── metric 2: proposal_to_executable_rate ────────────────────────────────────


def _routed(rid, nid):
    return {"record_id": rid, "source_refs": {"node_id": nid}}


def test_metric2_counts_nonsterile_diffful_nodes():
    records = [_routed("p1", "n1"), _routed("p2", "n2"),
               _routed("p3", "n3"), {"record_id": "unrouted"}]
    node_reports = {
        "n1": {"files_changed": True, "sterile": False},
        "n2": {"files_changed": False, "sterile": False},  # empty diff
        "n3": {"files_changed": True, "sterile": True},    # sterile
    }
    out = proposal_to_executable_rate(records, node_reports)
    assert (out["numerator"], out["denominator"]) == (1, 3)
    assert out["value"] == 1 / 3
    assert out["evidence_refs"] == ["p1"]


def test_metric2_not_applicable_without_routed_records():
    out = proposal_to_executable_rate([{"record_id": "x"}], {})
    assert out["applicable"] is False


# ── metric 3: downstream_success_rate ────────────────────────────────────────


def test_metric3_success_and_gate_verdict():
    tree = {"nodes": [_node("n1"), _node("n2", has_real_data=False),
                      _node("n3", status="FAILED")]}
    records = [_routed("p1", "n1"), _routed("p2", "n2"), _routed("p3", "n3")]
    gate = {"status": "passed", "should_block": False}
    out = downstream_success_rate(records, tree, gate)
    assert (out["numerator"], out["denominator"]) == (1, 3)
    assert out["detail"]["hard_gate_final_passed"] is True


def test_metric3_not_applicable_without_derived_nodes():
    out = downstream_success_rate([], {"nodes": []}, None)
    assert out["applicable"] is False


# ── metrics 4-8: detection rates ─────────────────────────────────────────────

_INJECTIONS = [
    {"injection_id": "eval_inj_a", "ground_truth_label": "bad",
     "target_refs": ["bad_ref_a"]},
    {"injection_id": "eval_inj_b", "ground_truth_label": "bad",
     "target_refs": ["bad_ref_b"]},
]
_CONTROLS = [
    {"injection_id": "eval_ctl_a", "ground_truth_label": "good",
     "target_refs": ["good_ref"]},
]


def test_detection_rates_known_answers():
    detections = [
        # true positive against injection a
        {"channel": "adversary.overclaim", "record_type": "validated_attack",
         "record_id": "vat_000000", "target_ref": "bad_ref_a"},
        # false positive: validated attack against a control artifact
        {"channel": "adversary.overclaim", "record_type": "validated_attack",
         "record_id": "vat_000001", "target_ref": "good_ref"},
        # upheld impeachment against an uninjected component (false)
        {"channel": "governance.impeachment",
         "record_type": "impeachment_outcome", "record_id": "imp_000001",
         "target_ref": "innocent_component", "verdict": "upheld"},
        # retirement of the injected-bad prompt (true)
        {"channel": "transition.retirement",
         "record_type": "retirement_event", "record_id": "ret_000001",
         "target_ref": "bad_ref_b"},
    ]
    out = detection_rates(detections, _INJECTIONS, _CONTROLS)
    # injection b was caught by retirement; a by validated attack → FA = 0
    assert out["false_accept_rate"]["value"] == 0.0
    # the control got a validated attack → FR = 1/1
    assert out["false_reject_rate"]["value"] == 1.0
    # 1 of 2 validated attacks targeted labeled-bad
    assert out["validated_attack_precision"]["value"] == 0.5
    # 1 upheld impeachment, target not labeled-bad
    assert out["false_impeachment_rate"]["value"] == 1.0
    # 1 retirement, target labeled-bad
    assert out["prompt_retirement_precision"]["value"] == 1.0


def test_detection_rates_false_accept_counts_undetected():
    out = detection_rates([], _INJECTIONS, _CONTROLS)
    assert out["false_accept_rate"]["value"] == 1.0
    assert out["false_reject_rate"]["value"] == 0.0
    assert out["validated_attack_precision"]["applicable"] is False


def test_detection_rates_not_applicable_without_ground_truth():
    out = detection_rates([], [], [])
    for key in ("false_accept_rate", "false_reject_rate",
                "validated_attack_precision", "false_impeachment_rate",
                "prompt_retirement_precision"):
        assert out[key]["applicable"] is False


# ── metric 9: frontier contamination ─────────────────────────────────────────


def test_metric9_counts_retired_hashes():
    frontier = [
        {"record_id": "r1", "prompt_hash": "a" * 12},
        {"record_id": "r2", "prompt_hash": "b" * 12},
        {"record_id": "r3", "prompt_hash": None},
    ]
    out = frontier_contamination(frontier, {"a" * 12})
    assert (out["numerator"], out["denominator"]) == (1, 3)
    assert out["evidence_refs"] == ["r1"]


def test_metric9_absence_tolerance():
    assert frontier_contamination([], {"a" * 12})["applicable"] is False
    assert frontier_contamination(
        [{"record_id": "r"}], None
    )["applicable"] is False


# ── metric 10: recovery after selective erasure ──────────────────────────────


def test_metric10_counts_nodes_to_recovery():
    series = [
        {"ordinal": 0, "epoch_id": "ep_000001", "score": 0.6},
        {"ordinal": 1, "epoch_id": "ep_000001", "score": 0.7},
        {"ordinal": 2, "epoch_id": "ep_000002", "score": 0.5},
        {"ordinal": 3, "epoch_id": "ep_000002", "score": 0.65},
        {"ordinal": 4, "epoch_id": "ep_000003", "score": 0.75},
    ]
    events = [{"record_id": "ers_000001", "epoch_id": "ep_000002"}]
    out = recovery_after_erasure(series, events)
    assert out["value"] == 3            # third post-erasure node reaches 0.7
    assert out["detail"]["pre_erasure_best"] == 0.7
    assert out["detail"]["recovered"] is True


def test_metric10_unrecovered_is_none_with_detail():
    series = [
        {"ordinal": 0, "epoch_id": "ep_000001", "score": 0.9},
        {"ordinal": 1, "epoch_id": "ep_000002", "score": 0.2},
    ]
    events = [{"record_id": "ers_000001", "epoch_id": "ep_000002"}]
    out = recovery_after_erasure(series, events)
    assert out["value"] is None
    assert out["detail"]["recovered"] is False


def test_metric10_not_applicable_without_events_or_series():
    assert recovery_after_erasure([], [])["applicable"] is False
    assert recovery_after_erasure(
        [], [{"record_id": "e", "epoch_id": "ep_000002"}]
    )["applicable"] is False


# ── metrics 11-12: cost ──────────────────────────────────────────────────────

_TRACE = [
    {"phase": "governance", "total_tokens": 100,
     "estimated_cost_usd": 0.30},
    {"phase": "governance", "total_tokens": 50,
     "estimated_cost_usd": 0.10},
    {"phase": "bfts", "total_tokens": 400, "estimated_cost_usd": 1.00},
]


def test_cost_metrics_totals_and_per_detection():
    out = cost_metrics(_TRACE, 2)
    assert out["token_cost"]["value"] == 550
    assert out["token_cost"]["detail"]["by_phase"] == {
        "bfts": 400, "governance": 150,
    }
    entry = out["cost_per_detected_failure"]
    assert entry["value"] == (0.30 + 0.10) / 2
    assert entry["detail"]["governance_usd"] == 0.4


def test_cost_metrics_non_injection_run():
    out = cost_metrics(_TRACE, None)
    assert out["token_cost"]["applicable"] is True
    assert out["cost_per_detected_failure"]["applicable"] is False


def test_cost_metrics_absence_tolerance():
    out = cost_metrics([], 1)
    assert out["token_cost"]["applicable"] is False
    assert out["cost_per_detected_failure"]["applicable"] is False


# ── metric 13: wall clock (metadata only) ────────────────────────────────────


def test_wall_clock_from_meta_timestamps():
    out = wall_clock_metadata({
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:42Z",
        "host": "smoke-host",
    })
    assert out["value"] == 42.0
    assert out["detail"] == {"host": "smoke-host", "hashed": False}


def test_wall_clock_not_applicable_without_timestamps():
    assert wall_clock_metadata({})["applicable"] is False
    assert wall_clock_metadata(None)["applicable"] is False


# ── compute_metric_report: envelope, absence tolerance, determinism ──────────


def test_report_on_empty_checkpoint_never_raises(tmp_path):
    report = compute_metric_report(tmp_path, condition_id="B0", seed=11)
    assert tuple(report["metrics"]) == METRIC_KEYS      # all 13, in order
    assert report["condition_id"] == "B0"
    assert report["seed"] == 11
    assert report["injection_ids"] == []
    for key in METRIC_KEYS:
        assert report["metrics"][key]["applicable"] is False, key


def _populate_ckpt(ckpt: Path) -> None:
    ckpt.mkdir(parents=True, exist_ok=True)
    (ckpt / "tree.json").write_text(json.dumps({"nodes": [
        _node("n1", 0.8, epoch="ep_000001"),
    ]}))
    (ckpt / "meta.json").write_text(json.dumps({
        "run_id": "r1", "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:01:00Z", "host": "h",
    }))
    (ckpt / "proposals").mkdir(exist_ok=True)
    (ckpt / "proposals" / "proposal_records.jsonl").write_text(
        json.dumps({"record_id": "p1", "record_type": "proposal_record",
                    "prompt_hash": "a" * 12,
                    "source_refs": {"node_id": "n1"}}) + "\n"
    )
    report_dir = ckpt / "experiments" / "n1"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "node_report.json").write_text(json.dumps({
        "files_changed": {"added": ["x.csv"], "modified": [], "deleted": []},
    }))
    (ckpt / "cost_trace.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _TRACE) + "\n"
    )


def test_report_is_deterministic_and_byte_identical(tmp_path):
    _populate_ckpt(tmp_path)
    first = compute_metric_report(tmp_path, condition_id="B3", seed=11)
    second = compute_metric_report(tmp_path, condition_id="B3", seed=11)
    assert json.dumps(first, sort_keys=True) == json.dumps(
        second, sort_keys=True
    )
    assert first["metrics"]["best_valid_scientific_score"]["value"] == 0.8
    assert first["metrics"]["proposal_to_executable_rate"]["value"] == 1.0
    assert first["metrics"]["token_cost"]["value"] == 550
    assert first["run_id"] == "r1"


def test_stale_rollup_and_registry_feed_contamination(tmp_path):
    _populate_ckpt(tmp_path)
    (tmp_path / "rqgm_registry.json").write_text(json.dumps({
        "prompts": [{"prompt_id": "v1", "status": "retired",
                     "prompt_hash": "a" * 12}],
    }))
    report = compute_metric_report(tmp_path)
    entry = report["metrics"]["frontier_contamination_rate"]
    assert entry["value"] == 1.0        # the sole frontier record is tainted
    assert entry["evidence_refs"] == ["p1"]


def test_write_metric_report_registered_and_stable(tmp_path):
    _populate_ckpt(tmp_path)
    report = compute_metric_report(tmp_path, condition_id="B3", seed=11)
    path = write_metric_report(tmp_path, report)
    assert path.name == METRIC_REPORT_FILENAME
    assert METRIC_REPORT_FILENAME in PathManager.META_FILES
    reread = json.loads(path.read_text())
    assert reread == json.loads(json.dumps(report))


# ── offline guard (P2: metric computation never talks to an LLM) ─────────────


def test_metrics_module_is_offline_no_llm_or_network_imports():
    import ari.rqgm.evaluation.metrics as mod

    text = open(mod.__file__, encoding="utf-8").read()
    for forbidden in ("import litellm", "import requests", "import urllib",
                      "import socket", "import http", "import random"):
        assert forbidden not in text, forbidden
