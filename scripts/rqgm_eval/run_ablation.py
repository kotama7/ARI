#!/usr/bin/env python3
"""RQGM ablation-run orchestrator (docs/plans/ari_rqgm/13 §5.5/§7).

Expands B0-B8 exploration presets, the legacy B paper ladder, or the
RQGM-paper-aligned P0-P4 presets from ``ablation_matrix.yaml`` into per-run
``workflow.yaml`` overlays and drives each condition × seed as a FRESH
``ari run`` checkpoint under ``workspace/rqgm_eval/<eval_id>/`` (no resume,
no ``skip_if_exists`` reuse across conditions), then computes each run's
``rqgm_eval_metrics.json`` and the campaign ``ablation_report.{json,md}``.

Deliberately a standalone argparse script — NOT an ``ari`` Typer command, no
``ari.public.*`` import — so the CLI/contract surfaces stay unchanged
(plan 13 non-goal). The unit-testable logic lives in
``ari.rqgm.evaluation.*`` (CI-hard); this file only wires processes.

Modes
-----
--dry-run     expand the selected conditions into ``configs/<cond>.yaml``
              overlays and stop (no runs, no LLM).
--smoke       offline Tier-2 smoke: synthetic stub-component runs through
              ``ari.rqgm.evaluation.smoke`` (seconds, no LLM) — the
              deletion-criteria smoke campaign ({B0, B3}, 1 seed) by default.
(default)     Tier-3: spawn ``ari run <experiment.md> --config <overlay>``
              per condition × seed × experiment with ``ARI_CHECKPOINT_DIR``
              pinned to the fresh checkpoint. The experiment set defaults to
              every ``experiments/*.md`` benchmark next to this script (the
              §5.2 "same experiment set" policy); ``eval_defaults.bfts`` is
              merged under every overlay (node-budget parity) and
              ``eval_defaults.models`` is resolved once at campaign start
              into the ``ARI_MODEL_*`` phase env vars stamped on every run
              (per-campaign model pinning). Real LLM cost — never run in CI.
              Only fixture-mechanism ``--inject`` specs are accepted:
              scripted_component specs are smoke-tier (plan 13 §5.3
              mechanism S — nothing in a real ``ari run`` consumes
              ``rqgm.eval.scripted_components``) and are refused rather
              than recorded as active faults that were never injected.
              For ``--rqgm-paper-conditions``, the final manuscript is then
              evaluated by a separate fixed rubric panel and written to
              ``panel_review_report.json`` before paper metrics are computed.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The shared benchmark experiment set (plan 13 §5.2 / §5.5).
EXPERIMENTS_DIR = Path(__file__).resolve().parent / "experiments"

# Editable installs make `import ari` work from anywhere; fall back to the
# in-repo package for bare source checkouts.
try:
    import ari  # noqa: F401
except ImportError:  # pragma: no cover - environment-dependent
    sys.path.insert(0, str(REPO_ROOT / "ari-core"))

import yaml  # noqa: E402

from ari.rqgm.evaluation import conditions as _conditions  # noqa: E402
from ari.rqgm.evaluation import injection as _injection  # noqa: E402
from ari.rqgm.evaluation import metrics as _metrics  # noqa: E402
from ari.rqgm.evaluation import smoke as _smoke  # noqa: E402


def expand_paper_condition(preset_id: str, matrix_path=None) -> dict:
    """Argparse-side expansion of a paper-archive B-ladder preset
    (``B0_paper_linear`` / ``B_archive_no_coevo`` / ``B_full``) to its concrete
    ``paper.mode`` + ``rqgm.paper.*`` overlay (paper-archive Task 07 §5.6/§7).

    Deviation from plan 07 §7 (said explicitly): the PURE expansion logic lives
    in ``ari.rqgm.evaluation.conditions.expand_paper_condition`` (CI-hard,
    unit-tested), exactly as the exploration ``expand_condition`` does — this
    thin argparse wrapper only loads the matrix and delegates, so no untested
    expansion logic hides in a non-package script.
    """
    matrix = _conditions.load_matrix(matrix_path)
    return _conditions.paper_condition_overlay(matrix, preset_id)


def expand_rqgm_paper_condition(preset_id: str, matrix_path=None) -> dict:
    """Expand an RQGM-original-paper-aligned P0-P4 evaluation arm."""

    matrix = _conditions.load_matrix(matrix_path)
    return _conditions.rqgm_paper_condition_overlay(matrix, preset_id)


def _parse_inject(arg: str) -> tuple:
    """``path[:id1,id2]`` → (specs path, selected ids or None)."""
    if not arg:
        return None, None
    path, _, ids = arg.partition(":")
    selected = [s for s in ids.split(",") if s] or None
    return Path(path), selected


def _select_specs(specs_path, selected_ids):
    if specs_path is None:
        return []
    data = _injection.load_injection_specs(specs_path)
    specs = (
        list(data["injections"])
        + list(data["controls"])
        + list(data.get("kca_injections") or ())
        + list(data.get("kca_controls") or ())
    )
    problems = []
    for spec in specs:
        problems += [
            f"{spec.get('injection_id')}: {p}"
            for p in _injection.spec_violations(spec)
        ]
    if problems:
        raise SystemExit("invalid injection specs:\n  " + "\n  ".join(problems))
    if selected_ids is not None:
        known = {str(s.get("injection_id")) for s in specs}
        missing = sorted(set(selected_ids) - known)
        if missing:
            raise SystemExit(f"unknown injection ids: {missing}")
        specs = [
            s for s in specs if str(s.get("injection_id")) in selected_ids
        ]
    return specs


def _scripted_overlay(specs) -> dict:
    scripted = {
        str(s.get("target_role")): str(s.get("double") or "")
        for s in specs
        if str(s.get("mechanism")) == "scripted_component"
    }
    if not scripted:
        return {}
    return {"rqgm": {"eval": {"enabled": True,
                              "scripted_components": scripted}}}


def _experiment_paths(raw) -> list:
    """Resolve ``--experiment`` (repeatable) to the benchmark set; defaults
    to every ``experiments/*.md`` next to this script (§5.2: every condition
    runs the SAME experiment set)."""
    paths = [Path(p) for p in raw or ()]
    if not paths:
        paths = sorted(EXPERIMENTS_DIR.glob("*.md"))
    if not paths:
        raise SystemExit(
            f"no benchmark experiments under {EXPERIMENTS_DIR} — "
            "pass --experiment <file.md>"
        )
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise SystemExit(f"experiment file(s) not found: {missing}")
    # The spawned `ari run` gets cwd=REPO_ROOT — relative paths must not
    # silently rebase.
    return [p.resolve() for p in paths]


def _run_one(eval_root: Path, condition_id: str, seed: int,
             experiment: Path, overlay: dict, specs, *,
             ari_bin: str, models_env: dict, paper: bool = False,
             panel: "dict | None" = None) -> dict:
    """One fresh Tier-3 checkpoint: write overlay, apply injections,
    spawn ``ari run``, compute the metric report."""
    ckpt = eval_root / "runs" / f"{condition_id}_s{seed}_{experiment.stem}"
    ckpt.mkdir(parents=True, exist_ok=False)  # fresh-checkpoint policy
    config_path = ckpt / "workflow.yaml"
    config_path.write_text(
        yaml.safe_dump(overlay, sort_keys=True), encoding="utf-8"
    )
    fixture_specs = [
        s for s in specs if str(s.get("mechanism")) == "fixture"
    ]
    for spec in fixture_specs:
        _injection.apply_injection(spec, ckpt)
    if specs:
        _injection.write_injection_provenance(ckpt, specs)
    env = dict(os.environ)
    env["ARI_CHECKPOINT_DIR"] = str(ckpt)
    # Campaign-start model snapshot: identical for every run (§5.2 pinning).
    env.update(models_env)
    subprocess.run(
        [ari_bin, "run", str(experiment), "--config", str(config_path)],
        check=True, env=env, cwd=str(REPO_ROOT),
    )
    if paper and panel:
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("run_paper_panel.py")),
                str(ckpt),
                "--spec-json",
                json.dumps(panel, sort_keys=True),
            ],
            check=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
    if not _conditions.virsci_enabled(overlay):
        # Plan 13 §5.2: the VirSci-off condition must be VirSci-free
        # (no prompts in prompt_trace.jsonl, no transcript artifacts).
        problems = _conditions.virsci_absence_violations(ckpt)
        if problems:
            raise RuntimeError(
                f"{condition_id} (VirSci off) checkpoint is not "
                f"VirSci-free: {problems}"
            )
    report = _metrics.compute_metric_report(
        ckpt, injections=specs or None,
        condition_id=condition_id, seed=seed,
        paper=paper, panel=panel,
    )
    # Keep (seed, experiment) rows distinct in the campaign aggregation.
    report["experiment_id"] = experiment.stem
    _metrics.write_metric_report(ckpt, report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--matrix", type=Path,
        default=Path(__file__).with_name("ablation_matrix.yaml"),
    )
    parser.add_argument(
        "--conditions", default="B0,B3",
        help="comma-separated condition ids (default: the smoke pair)",
    )
    parser.add_argument(
        "--assurance-conditions", default="",
        help="comma-separated Task-20 H-axis ids; forms a B×H×K panel",
    )
    parser.add_argument(
        "--knowledge-capability-conditions", default="",
        help="comma-separated Task-20 K-axis ids; forms a B×H×K panel",
    )
    parser.add_argument(
        "--paper-conditions", default="",
        help="comma-separated paper-archive B-ladder ids "
             "(B0_paper_linear,B_archive_no_coevo,B_full); expanded to "
             "paper.mode + rqgm.paper.* overlays (dry-run supported)",
    )
    parser.add_argument(
        "--rqgm-paper-conditions", default="",
        help="comma-separated RQGM-paper-aligned evaluation ids "
             "(P0_hgm_h_fixed_critic,P1_rqgm_replacement_only,"
             "P2_rqgm_no_erasure,P3_rqgm_full,"
             "P4_constitutional_rqgm)",
    )
    parser.add_argument("--eval-id", default="eval_local")
    parser.add_argument(
        "--seeds", default="",
        help="comma-separated seeds (default: eval_defaults.seeds)",
    )
    parser.add_argument(
        "--inject", default="",
        help="failure_injections.yaml[:id1,id2] to activate "
             "(scripted_component ids are accepted only with --smoke)",
    )
    parser.add_argument(
        "--experiment", action="append", type=Path, default=None,
        help="benchmark experiment .md for Tier-3 runs (repeatable; "
             "default: every experiments/*.md next to this script)",
    )
    parser.add_argument(
        "--workspace", type=Path, default=REPO_ROOT / "workspace" / "rqgm_eval",
    )
    parser.add_argument("--ari-bin", default="ari")
    parser.add_argument("--dry-run", action="store_true",
                        help="expand configs only; no runs")
    parser.add_argument("--smoke", action="store_true",
                        help="offline synthetic smoke (no LLM, seconds)")
    args = parser.parse_args(argv)

    matrix = _conditions.load_matrix(args.matrix)
    paper_condition_ids = [c for c in args.paper_conditions.split(",") if c]
    rqgm_paper_condition_ids = [
        c for c in args.rqgm_paper_conditions.split(",") if c
    ]
    if paper_condition_ids and rqgm_paper_condition_ids:
        raise SystemExit(
            "--paper-conditions and --rqgm-paper-conditions are separate "
            "campaigns; select one"
        )
    if paper_condition_ids:
        # Paper-archive B-ladder (Task 07 §5.6): expand paper.mode +
        # rqgm.paper.* overlays. Dry-run prints them; a full Tier-3 paper
        # campaign spawns `ari run` + `ari paper` per condition (paper-phase
        # plumbing, never in CI).
        paper_overlays = {
            cid: _conditions.paper_condition_overlay(matrix, cid)
            for cid in paper_condition_ids
        }
        if args.dry_run:
            print(json.dumps(paper_overlays, indent=2, sort_keys=True))
            return 0
        raise SystemExit(
            "paper-archive Tier-3 campaigns are run per-condition via "
            "`ari run` + `ari paper` with these overlays; use --dry-run to "
            "emit them, or the pinned presets in ablation_matrix.yaml"
        )
    if rqgm_paper_condition_ids:
        if args.smoke:
            raise SystemExit(
                "RQGM-paper P0-P4 conditions require the real paper pipeline; "
                "--smoke is not supported"
            )
        if args.inject:
            raise SystemExit(
                "--inject currently targets the exploration failure set; "
                "run the P0-P4 comparison without it"
            )
        parity = _conditions.eval_defaults_overlay(matrix)
        overlays = {
            cid: _conditions.deep_merge(
                parity,
                _conditions.rqgm_paper_condition_overlay(matrix, cid),
            )
            for cid in rqgm_paper_condition_ids
        }
        if args.dry_run:
            print(json.dumps(overlays, indent=2, sort_keys=True))
            return 0
        seeds = [int(s) for s in args.seeds.split(",") if s] or [
            int(s)
            for s in (matrix.get("eval_defaults") or {}).get("seeds", [11])
        ]
        eval_root = (args.workspace / args.eval_id).resolve()
        eval_root.mkdir(parents=True, exist_ok=True)
        for cid, overlay in overlays.items():
            out = eval_root / "configs" / f"{cid}.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                yaml.safe_dump(overlay, sort_keys=True), encoding="utf-8"
            )
        experiments = _experiment_paths(args.experiment)
        models_env = _conditions.resolve_models(matrix, os.environ)
        panel = dict((matrix.get("paper_eval_defaults") or {}).get("panel")
                     or {})
        reports = []
        for cid in rqgm_paper_condition_ids:
            for seed in seeds:
                for experiment in experiments:
                    reports.append(
                        _run_one(
                            eval_root, cid, seed, experiment, overlays[cid], (),
                            ari_bin=args.ari_bin, models_env=models_env,
                            paper=True, panel=panel,
                        )
                    )
        report = _smoke.build_ablation_report(
            reports, eval_id=args.eval_id
        )
        _smoke.write_ablation_report(eval_root, report)
        print(
            "RQGM-paper ablation report: "
            f"{eval_root / _smoke.ABLATION_REPORT_JSON}"
        )
        return 0
    b_condition_ids = [c for c in args.conditions.split(",") if c]
    h_condition_ids = [
        c for c in args.assurance_conditions.split(",") if c
    ]
    k_condition_ids = [
        c for c in args.knowledge_capability_conditions.split(",") if c
    ]
    if bool(h_condition_ids) != bool(k_condition_ids):
        raise SystemExit(
            "Task-20 factorial campaigns require both "
            "--assurance-conditions and --knowledge-capability-conditions"
        )
    if h_condition_ids:
        condition_ids = [
            _conditions.factorial_condition_id(b, h, k)
            for b, h, k in itertools.product(
                b_condition_ids, h_condition_ids, k_condition_ids
            )
        ]
    else:
        condition_ids = b_condition_ids
    specs = _select_specs(*_parse_inject(args.inject))
    scripted_ids = _injection.smoke_only_spec_ids(specs)
    if scripted_ids and not args.smoke:
        # Plan 13 §5.3: mechanism S is smoke-tier. A real `ari run` never
        # consults rqgm.eval.scripted_components, so accepting these here
        # would stamp provenance/metrics with a fault that was never
        # injected (inflating false_accept_rate).
        raise SystemExit(
            "scripted_component injections are smoke-tier only; refused "
            "outside --smoke: " + ", ".join(scripted_ids)
            + "\nRe-run with --smoke, or select fixture ids only, e.g. "
            "--inject failure_injections.yaml:eval_inj_001_metric_gaming"
        )
    seeds = [int(s) for s in args.seeds.split(",") if s] or [
        int(s)
        for s in (matrix.get("eval_defaults") or {}).get("seeds", [11])
    ]
    # Resolve before any subprocess runs with cwd=REPO_ROOT.
    eval_root = (args.workspace / args.eval_id).resolve()
    eval_root.mkdir(parents=True, exist_ok=True)

    # §5.2 node-budget parity: eval_defaults.bfts merged UNDER every
    # condition so max_total_nodes / max_depth are identical across rungs.
    parity = _conditions.eval_defaults_overlay(matrix)
    overlays = {}
    for cid in condition_ids:
        overlay = _conditions.deep_merge(
            parity, _conditions.evaluation_condition_overlay(matrix, cid)
        )
        overlay = _conditions.deep_merge(overlay, _scripted_overlay(specs))
        overlays[cid] = overlay
        out = eval_root / "configs" / f"{cid}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(overlay, sort_keys=True),
                       encoding="utf-8")
    if args.dry_run:
        print(json.dumps({cid: overlays[cid] for cid in condition_ids},
                         indent=2, sort_keys=True))
        return 0

    if args.smoke:
        report = _smoke.run_smoke(
            eval_root, conditions=condition_ids, seeds=seeds,
            matrix_path=args.matrix, injections=specs or None,
            eval_id=args.eval_id,
        )
        print(f"smoke report: {eval_root / _smoke.ABLATION_REPORT_JSON}")
        print(json.dumps(report.get("deltas", {}), indent=2, sort_keys=True))
        return 0

    experiments = _experiment_paths(args.experiment)
    # One campaign-start snapshot pins ARI_MODEL_* for every spawned run.
    models_env = _conditions.resolve_models(matrix, os.environ)
    reports = []
    for cid in condition_ids:
        for seed in seeds:
            for experiment in experiments:
                reports.append(
                    _run_one(eval_root, cid, seed, experiment,
                             overlays[cid], specs,
                             ari_bin=args.ari_bin, models_env=models_env)
                )
    report = _smoke.build_ablation_report(reports, eval_id=args.eval_id)
    _smoke.write_ablation_report(eval_root, report)
    print(f"ablation report: {eval_root / _smoke.ABLATION_REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
