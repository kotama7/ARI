"""Offline Tier-2 smoke runner + ablation-report aggregation (Task 13 §5.5).

``run_smoke`` drives a deterministic no-LLM/no-network synthetic run per
(condition, seed), computes ``rqgm_eval_metrics.json``, and aggregates
``ablation_report.{json,md}`` under ``workspace/rqgm_eval/<eval_id>/``.

The synthetic trajectory is deterministic (P2): fixed node scores, fixed
epoch ids, fixed timestamps (metadata only, never hashed). RQGM records are
produced through the REAL constructors and stores (ProposalRecord,
``make_validated_attack_record``, AdversarialCaseLog, ImmutableAuditLog,
kernel schema checks) so the smoke exercises the same detection code paths
production components hit — the doubles-only-implement-failure-behavior rule
of plan 13 §10. Scripted-component injections engage the
:mod:`ari.rqgm.evaluation.doubles` registry through the same
``rqgm.eval.scripted_components`` config surface the harness uses.

Feature flags come from the effective ``ARIConfig.model_validate(overlay)``
config, so Tier-2 and Tier-3 interpret defaults identically and never treat
an absent key as off.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from ari.rqgm.evaluation import conditions as _conditions
from ari.rqgm.evaluation import injection as _injection
from ari.rqgm.evaluation import metrics as _metrics
from ari.rqgm.evaluation.doubles import EVAL_DOUBLE_REGISTRY

log = logging.getLogger(__name__)

ABLATION_REPORT_SCHEMA_VERSION = 1
ABLATION_REPORT_JSON = "ablation_report.json"
ABLATION_REPORT_MD = "ablation_report.md"

#: The deletion-criteria smoke subset (plan 13 §9 Tier 3 smoke).
SMOKE_DEFAULT_CONDITIONS: tuple[str, ...] = ("B0", "B3")

#: Fixed synthetic trajectory (id, epoch, score) — deterministic (P2).
_SMOKE_NODES: tuple[tuple[str, str, float], ...] = (
    ("smoke_n0", "ep_000001", 0.55),
    ("smoke_n1", "ep_000001", 0.62),
    ("smoke_n2", "ep_000002", 0.70),
)

#: Fixed metadata timestamps — metric 13 is metadata only, never hashed.
_SMOKE_STARTED_AT = "2026-01-01T00:00:00Z"
_SMOKE_FINISHED_AT = "2026-01-01T00:00:05Z"

#: The §5.1 ladder deltas reported next to the per-condition medians.
_DELTA_PAIRS: tuple[tuple[str, str], ...] = (
    ("B1", "B0"),
    ("B2", "B3"),
    ("B4", "B3"),
    ("B5", "B4"),
    ("B6", "B5"),
    ("B7", "B6"),
    ("B8", "B7"),
    # B9-B8 is the only defined measurement of whether governed score
    # rewriting earns its cost: B8 pins utility_evolution off, B9 turns it on.
    ("B9", "B8"),
    # RQGM-paper-aligned headline and mechanism-isolation contrasts.
    ("P1_rqgm_replacement_only", "P0_hgm_h_fixed_critic"),
    ("P2_rqgm_no_erasure", "P1_rqgm_replacement_only"),
    ("P3_rqgm_full", "P2_rqgm_no_erasure"),
    ("P3_rqgm_full", "P0_hgm_h_fixed_critic"),
    ("P4_constitutional_rqgm", "P3_rqgm_full"),
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def _effective_config(overlay: dict):
    """The effective ``ARIConfig`` a spawned ``ari run --config <overlay>``
    resolves: pydantic defaults fill every absent key (several layer flags
    default TRUE), so Tier-2 must read flags from here — an absent-as-off
    reading would silently disagree with Tier-3 on the same overlay."""
    # Function-level import: the ari.rqgm runtime-import posture keeps
    # ari.config out of module scope (plan 01 §8.1 precedent, state.py).
    from ari.config import ARIConfig

    return ARIConfig.model_validate(overlay or {})


def _is_rqgm(overlay: dict) -> bool:
    cfg = _effective_config(overlay)
    # Both flags must agree — the Task 01 activation interlock.
    return cfg.ari.mode == "ari_rqgm" and bool(cfg.rqgm.enabled)


def _scripted_specs(specs: list) -> dict:
    """``role -> spec`` over the scripted-component injection specs."""
    out: dict = {}
    for spec in specs or ():
        if str(spec.get("mechanism")) == "scripted_component":
            out[str(spec.get("target_role") or "")] = spec
    return out


def _write_baseline_checkpoint(ckpt: Path, overlay: dict, seed: int) -> None:
    """The condition-independent artifact set (the B0 file contract)."""
    ckpt.mkdir(parents=True, exist_ok=True)
    (ckpt / "workflow.yaml").write_text(
        yaml.safe_dump(overlay, sort_keys=True), encoding="utf-8"
    )
    rqgm = _is_rqgm(overlay)
    nodes = []
    for nid, epoch, score in _SMOKE_NODES:
        node = {
            "id": nid,
            "status": "SUCCESS",
            "has_real_data": True,
            "metrics": {"_scientific_score": score},
        }
        if rqgm:
            node["epoch_id"] = epoch
        nodes.append(node)
        report_dir = ckpt / "experiments" / nid
        report_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            report_dir / "node_report.json",
            {
                "schema_version": 1,
                "node_id": nid,
                "files_changed": {
                    "added": [f"{nid}_result.csv"],
                    "modified": [],
                    "deleted": [],
                },
            },
        )
    _write_json(ckpt / "tree.json", {"nodes": nodes})
    _write_json(
        ckpt / "meta.json",
        {
            "run_id": ckpt.name,
            "seed": seed,
            "started_at": _SMOKE_STARTED_AT,
            "finished_at": _SMOKE_FINISHED_AT,
            "host": "rqgm_eval_smoke",
        },
    )


def _write_proposal_records(ckpt: Path) -> None:
    """Route one real ProposalRecord per synthetic node (Task 03 shapes)."""
    from ari.rqgm.proposals.records import ProposalRecord, ProposalSummaryView

    lines = []
    for i, (nid, epoch, _score) in enumerate(_SMOKE_NODES):
        rec = ProposalRecord(
            record_id="eval_smoke_prop_%03d" % i,
            generator="cheap",
            status="expanded",
            epoch_id=epoch,
            component_id="generator_cheap",
            source_refs={"node_id": nid},
            summary=ProposalSummaryView(
                proposal_record_id="eval_smoke_prop_%03d" % i,
                title=f"smoke proposal {i}",
                short_description="deterministic smoke fixture",
            ),
        )
        lines.append(json.dumps(rec.to_dict(), ensure_ascii=False))
    path = ckpt / "proposals" / "proposal_records.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_adversarial_stubs(ckpt: Path, scripted: dict) -> dict:
    """One deterministic attack→adjudicate round per node through the REAL
    Task 06 constructors and stores. The adversary/judge stubs default to the
    eval doubles (failure behavior); detection stays the production path:
    only ``valid``/``partially_valid`` judgments can mint a
    ValidatedAttackRecord."""
    from ari.rqgm.adversarial.pool import AdversarialCaseLog
    from ari.rqgm.adversarial.records import format_validated_id, \
        make_validated_attack_record
    from ari.rqgm.store import ImmutableAuditLog

    adversary = EVAL_DOUBLE_REGISTRY.resolve(
        "adversary/"
        + str((scripted.get("adversary") or {}).get("double")
              or "always_attack")
    )
    judge = EVAL_DOUBLE_REGISTRY.resolve(
        "judge/"
        + str((scripted.get("judge") or {}).get("double")
              or "always_validate")
    )
    case_log = AdversarialCaseLog(ckpt)
    audit = ImmutableAuditLog(ckpt)
    validated_count = 0
    seq = 0
    for nid, epoch, _score in _SMOKE_NODES:
        attacks = adversary.attacks(nid, epoch_id=epoch)
        case_log.append_all(attacks)
        for attack in attacks:
            judgment = judge.judge(attack, epoch_id=epoch)
            case_log.append_all([judgment])
            if judgment.verdict not in ("valid", "partially_valid"):
                continue
            validated = make_validated_attack_record(
                judgment, attack, record_id=format_validated_id(seq)
            )
            seq += 1
            case_log.append_all([validated])
            audit.append("validated_attack", validated.to_dict())
            validated_count += 1
    return {"validated_attacks": validated_count}


def _run_generator_stub(ckpt: Path, spec: dict) -> dict:
    """Injection 6 end-to-end: the schema-violating generator double's
    output hits the real kernel schema check; invalid proposals never reach
    the store and the violation is audited (the plan's immediate channel)."""
    from ari.rqgm.kernel import ConstitutionalKernel
    from ari.rqgm.store import ImmutableAuditLog

    generator = EVAL_DOUBLE_REGISTRY.resolve(
        "generator/" + str(spec.get("double") or "schema_violating")
    )
    kernel = ConstitutionalKernel()
    audit = ImmutableAuditLog(ckpt)
    rejected = 0
    for proposal in generator.generate():
        report = kernel.validate_record_schema(proposal)
        if report.ok:
            continue
        rejected += 1
        audit.append(
            "constitutional_violation",
            {
                "check": "validate_record_schema",
                "injection_id": str(spec.get("injection_id") or ""),
                "codes": sorted({v.code for v in report.violations}),
            },
        )
    return {"rejected_proposals": rejected}


def _run_mutator_stub(ckpt: Path, spec: dict) -> dict:
    """Injection 8 end-to-end: the degenerate mutator's candidate fails the
    real Task 07 stage-1 dry-run and is never activated (invariant 15)."""
    from ari.rqgm.prompt_evolution import static_validation_failures
    from ari.rqgm.prompt_records import candidate_from_dict
    from ari.rqgm.store import ImmutableAuditLog

    mutator = EVAL_DOUBLE_REGISTRY.resolve(
        "prompt_mutator/" + str(spec.get("double") or "degenerate")
    )
    candidate = candidate_from_dict(mutator.propose("reviewer"))
    failures = static_validation_failures(
        candidate, mutator.template_text
    )
    rejected = bool(failures)
    if rejected:
        ImmutableAuditLog(ckpt).append(
            "prompt_candidate_rejected",
            {
                "candidate_id": candidate.candidate_id,
                "stage": "schema_dry_run",
                "injection_id": str(spec.get("injection_id") or ""),
                "failure_count": len(failures),
            },
        )
    return {"mutator_candidate_rejected": rejected}


def run_condition_smoke(
    eval_root: Path,
    condition_id: str,
    *,
    matrix: dict | None = None,
    seed: int = 11,
    injections: "list[dict] | None" = None,
) -> dict:
    """One synthetic run for *condition_id* into
    ``<eval_root>/runs/<condition_id>_s<seed>/``; returns its metric report.

    Fixture injections are applied via :func:`injection.apply_injection`;
    scripted-component injections engage the matching eval double (per role)
    on the RQGM stub subsystems. Every injected run gets the
    ``rqgm_injection_provenance.json`` marker.
    """
    matrix = matrix if matrix is not None else _conditions.load_matrix()
    overlay = _conditions.evaluation_condition_overlay(matrix, condition_id)
    specs = [dict(s) for s in injections or ()]
    scripted = _scripted_specs(specs)
    if scripted:
        # The same config surface the real harness uses (plan 13 §7).
        overlay = _conditions.deep_merge(
            overlay,
            {
                "rqgm": {
                    "eval": {
                        "enabled": True,
                        "scripted_components": {
                            role: str(spec.get("double") or "")
                            for role, spec in sorted(scripted.items())
                        },
                    }
                }
            },
        )
    ckpt = Path(eval_root) / "runs" / f"{condition_id}_s{int(seed)}"
    _write_baseline_checkpoint(ckpt, overlay, seed)

    summary: dict = {}
    if _is_rqgm(overlay):
        _write_proposal_records(ckpt)
        if _effective_config(overlay).rqgm.adversarial.enabled:
            summary.update(_run_adversarial_stubs(ckpt, scripted))
        if "generator" in scripted:
            summary.update(_run_generator_stub(ckpt, scripted["generator"]))
        if "prompt_mutator" in scripted:
            summary.update(
                _run_mutator_stub(ckpt, scripted["prompt_mutator"])
            )
    for spec in specs:
        if str(spec.get("mechanism")) in {"fixture", "kca_mutation"}:
            _injection.apply_injection(spec, ckpt)
    if any(str(spec.get("mechanism")) == "kca_mutation" for spec in specs):
        from ari.rqgm.evaluation.kca_probe import run_and_persist_kca_probes

        summary.update(run_and_persist_kca_probes(ckpt, specs))
    if specs:
        _injection.write_injection_provenance(ckpt, specs)

    if not _conditions.virsci_enabled(overlay):
        # The §5.2 VirSci-off assertion: an off-condition checkpoint must
        # be VirSci-free or the VirSci contrast is invalid.
        problems = _conditions.virsci_absence_violations(ckpt)
        if problems:
            raise RuntimeError(
                f"{condition_id} is a VirSci-off condition but the "
                f"checkpoint is not VirSci-free: {problems}"
            )

    report = _metrics.compute_metric_report(
        ckpt, injections=specs or None, condition_id=condition_id, seed=seed
    )
    _metrics.write_metric_report(ckpt, report)
    if summary:
        report = dict(report)
        report["smoke_summary"] = summary
    return report


def _metric_values(report: dict) -> dict:
    values = {
        key: (entry or {}).get("value")
        for key, entry in (report.get("metrics") or {}).items()
    }
    values.update({
        key: (entry or {}).get("value")
        for key, entry in (report.get("paper") or {}).items()
    })
    values.update({
        "knowledge_capability." + key: (entry or {}).get("value")
        for key, entry in (report.get("knowledge_capability") or {}).items()
    })
    values.update({
        "assurance." + key: (entry or {}).get("value")
        for key, entry in (report.get("assurance") or {}).items()
    })
    return values


def _median(values: list) -> "float | None":
    nums = sorted(
        float(v) for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def build_ablation_report(reports: list, *, eval_id: str = "") -> dict:
    """Condition × metric matrix with per-seed values, medians, and the §6
    paired deltas (each condition vs B0 plus the ladder pairs)."""
    by_condition: dict = {}
    for report in reports or ():
        cid = str(report.get("condition_id") or "")
        entry = by_condition.setdefault(cid, {"seeds": {}, "median": {}})
        key = str(report.get("seed"))
        experiment = str(report.get("experiment_id") or "")
        if experiment:
            # Tier-3 runs the same seed across several benchmark
            # experiments (§5.2); keep each row distinct in the matrix.
            key = f"{key}:{experiment}"
        entry["seeds"][key] = _metric_values(report)
    for entry in by_condition.values():
        per_metric: dict = {}
        for values in entry["seeds"].values():
            for key, value in values.items():
                per_metric.setdefault(key, []).append(value)
        entry["median"] = {
            key: _median(vals) for key, vals in sorted(per_metric.items())
        }
    deltas: dict = {}
    pairs = list(_DELTA_PAIRS) + [
        (cid, "B0") for cid in sorted(by_condition) if cid != "B0"
    ]
    for hi, lo in pairs:
        if hi not in by_condition or lo not in by_condition:
            continue
        row: dict = {}
        for key, hv in by_condition[hi]["median"].items():
            lv = by_condition[lo]["median"].get(key)
            if isinstance(hv, (int, float)) and isinstance(lv, (int, float)):
                row[key] = hv - lv
        deltas[f"{hi}-{lo}"] = row
    return {
        "schema_version": ABLATION_REPORT_SCHEMA_VERSION,
        "eval_id": str(eval_id),
        "conditions": {k: by_condition[k] for k in sorted(by_condition)},
        "deltas": {k: deltas[k] for k in sorted(deltas)},
    }


def render_ablation_markdown(report: dict) -> str:
    """Deterministic markdown companion rendered from the JSON (§6)."""
    lines = ["# RQGM ablation report", ""]
    if report.get("eval_id"):
        lines += [f"Eval id: `{report['eval_id']}`", ""]
    conds = report.get("conditions") or {}
    metric_keys = sorted(
        {k for c in conds.values() for k in (c.get("median") or {})}
    )
    if conds:
        lines.append("| metric | " + " | ".join(sorted(conds)) + " |")
        lines.append("|---|" + "---|" * len(conds))
        for key in metric_keys:
            row = [key]
            for cid in sorted(conds):
                value = (conds[cid].get("median") or {}).get(key)
                row.append("—" if value is None else f"{value:.6g}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    deltas = report.get("deltas") or {}
    if deltas:
        lines.append("## Paired deltas (medians)")
        lines.append("")
        for pair in sorted(deltas):
            lines.append(f"- `{pair}`:")
            for key in sorted(deltas[pair]):
                lines.append(f"  - {key}: {deltas[pair][key]:+.6g}")
        lines.append("")
    return "\n".join(lines)


def write_ablation_report(eval_root: Path, report: dict) -> tuple:
    """Persist ``ablation_report.{json,md}`` into *eval_root*."""
    root = Path(eval_root)
    json_path = _write_json(root / ABLATION_REPORT_JSON, report)
    md_path = root / ABLATION_REPORT_MD
    md_path.write_text(render_ablation_markdown(report), encoding="utf-8")
    return json_path, md_path


def run_smoke(
    eval_root: Path,
    *,
    conditions=SMOKE_DEFAULT_CONDITIONS,
    seeds=(11,),
    matrix_path=None,
    injections: "list[dict] | None" = None,
    eval_id: str = "smoke",
) -> dict:
    """The offline smoke campaign: every (condition, seed) synthetic run plus
    the aggregated ``ablation_report.{json,md}`` under *eval_root*."""
    matrix = _conditions.load_matrix(matrix_path)
    reports = []
    for cid in conditions:
        for seed in seeds:
            reports.append(
                run_condition_smoke(
                    eval_root, str(cid),
                    matrix=matrix, seed=int(seed), injections=injections,
                )
            )
    report = build_ablation_report(reports, eval_id=eval_id)
    write_ablation_report(eval_root, report)
    return report
