"""
ari-skill-transform: LLM-powered experiment tree analysis.

Reads nodes_tree.json (BFTS output) and uses an LLM to deeply understand:
- Hardware environment discovered during experiments
- Implementation methodology of the best configurations
- Performance measurements and their scientific meaning
- Comparison baselines if any were measured
- Key findings suitable for paper writing

Replaces the former regex-only transform with full LLM comprehension.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import litellm as litellm
from mcp.server.fastmcp import FastMCP

from annotations import (
    annotate_science_data,
    build_interpretation_prompt,
    robust_extract_json,
)
from ari.public.execution import (
    MeasurementDocumentError,
    measurement_document_format,
    parse_measurement_document,
)
from science_data import assemble_science_data, build_deterministic_sections

mcp = FastMCP("transform-skill")


def _default_llm_model() -> str:
    """Pick a fallback model that matches the active backend.

    Why this exists: ``nodes_to_science_data`` and similar transforms are
    invoked from workflow.yaml without an explicit ``llm_model`` argument. The
    historical default ``gpt-4o-mini`` is an OpenAI-only model name, but when
    ``ARI_BACKEND=cli-shim`` the ``ari.cost_tracker`` litellm injector
    auto-fills ``api_base`` with ``ARI_LLM_API_BASE`` for *every* call. The
    cli-shim then rejects ``gpt-4o-mini`` with
    ``unknown model 'gpt-4o-mini'; expected one of claude-cli, ...`` and the
    whole analysis returns an error string that ends up in
    ``experiment_context.error`` of science_data.json. Falling back to
    ``claude-cli`` when the backend is cli-shim lines the model up with what
    the shim actually serves.
    """
    backend = (os.environ.get("ARI_BACKEND") or "").strip().lower()
    if backend in ("cli-shim", "cli_shim"):
        return "claude-cli"
    return "gpt-4o-mini"


def _resolve_llm_model(explicit: str = "") -> str:
    """Resolve the transform model with the repository-wide precedence."""

    return (
        explicit.strip()
        or (os.environ.get("ARI_MODEL_TRANSFORM") or "").strip()
        or (os.environ.get("ARI_LLM_MODEL") or "").strip()
        or (os.environ.get("LLM_MODEL") or "").strip()
        or _default_llm_model()
    )


def _resolve_llm_base_url(explicit: str = "") -> str:
    """Resolve an optional provider endpoint without inventing a default."""

    if explicit.strip():
        return explicit.strip()
    ari_value = os.environ.get("ARI_LLM_API_BASE")
    if ari_value is not None:
        return ari_value.strip()
    return (os.environ.get("LLM_API_BASE") or "").strip()


try:
    from ari.public import cost_tracker as _ari_cost_tracker  # type: ignore

    _ari_cost_tracker.bootstrap_skill("transform")
except Exception:
    pass


def _load_nodes(nodes_json_path: str) -> list[dict]:
    data = json.loads(Path(nodes_json_path).read_text())
    return data if isinstance(data, list) else data.get("nodes", [])


_robust_extract_json = robust_extract_json


def _load_node_reports_for_tree(
    nodes_json_path: str, nodes: list[dict]
) -> dict[str, dict]:
    """Best-effort discovery of `node_report.json` files for *nodes*.

    Walks two candidate work_dir layouts so both PathManager-shaped
    workspaces (`{ws}/checkpoints/{run_id}/`,
    `{ws}/experiments/{run_id}/{node_id}/`) and flatter test fixtures work.
    """
    from pathlib import Path as _P

    p = _P(nodes_json_path).expanduser().resolve()
    if p.is_file():
        ckpt = p.parent
    else:
        ckpt = p if p.is_dir() else _P(".").resolve()

    workspace = ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent
    run_id = ckpt.name

    reports: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        for cand in (
            workspace / "experiments" / run_id / nid / "node_report.json",
            workspace / "experiments" / nid / "node_report.json",
            ckpt / "experiments" / nid / "node_report.json",
        ):
            if cand.is_file():
                try:
                    report = json.loads(cand.read_text())
                except Exception:
                    continue
                # A report at the expected path is not evidence when its bound
                # identity disagrees.  Treat it as missing; never compensate by
                # scanning trace/source files in the live producer.
                if not isinstance(report, dict) or str(
                    report.get("node_id") or ""
                ) != str(nid):
                    continue
                reports[nid] = report
                break
    return reports


def _resolve_best_node_for_synthesis(nodes: list[dict]) -> str:
    """Same best-node rule as generate_ear (argmax score, validation tie-break).

    Nodes erased by RQGM selective erasure (``_valid_for_frontier: false`` in
    metrics) are excluded — their retained scores must not pick the node whose
    data becomes science_data.json. Inert on non-RQGM trees (key never written).
    """
    real = [
        n for n in nodes
        if n.get("has_real_data") and n.get("metrics")
        and (n.get("metrics") or {}).get("_valid_for_frontier", True) is not False
    ]
    if not real:
        return ""
    real.sort(
        key=lambda n: (
            float((n.get("metrics") or {}).get("_scientific_score") or 0.0),
            1 if str(n.get("label") or "").lower() == "validation" else 0,
            int(n.get("depth") or 0),
        ),
        reverse=True,
    )
    return real[0].get("id", "")


def _load_run_metric_contract(nodes_json_path: str) -> "dict | None":
    """Load the run-level metric_contract make_metric_spec persisted next to
    tree.json (idea-derived: concept invariants, correctness, required_measured,
    falsifiable claims). ``None`` when absent (legacy run) or unreadable, so the
    gate's declared-contract checks are a clean no-op.
    """
    from pathlib import Path as _P_mc

    from ari.public.claim_gate import (
        migrate_legacy_metric_gate_contract,
        parse_metric_gate_contract,
    )

    _mc_path = (
        _P_mc(nodes_json_path).expanduser().resolve().parent / "metric_contract.json"
    )
    if not _mc_path.is_file():
        return None
    try:
        _mc_obj = json.loads(_mc_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(_mc_obj, dict) or not _mc_obj:
        return None
    if _mc_obj.get("schema_version") == "ari.metric-gate-contract/v1":
        return parse_metric_gate_contract(_mc_obj).model_dump(mode="json")
    try:
        migrated = migrate_legacy_metric_gate_contract(_mc_obj)
    except Exception:
        return None
    return migrated.model_dump(mode="json")


@mcp.tool()
async def nodes_to_science_data(
    nodes_json_path: str,
    llm_model: str = "",
    llm_base_url: str = "",
    primary_metric: str = "",
    higher_is_better: str = "true",
) -> dict:
    """
    LLM-powered conversion of BFTS experiment tree to publication-ready scientific data.

    Unlike a regex approach, the LLM reads the actual experiment outputs (stdout,
    logs, scripts) and extracts rich scientific context: hardware specs, methodology,
    implementation details, comparison baselines, and key findings.

    Args:
        nodes_json_path:   Path to nodes_tree.json produced by BFTS
        llm_model:         LLM model name (litellm format). Falls back through
                           ARI_MODEL_TRANSFORM, ARI_LLM_MODEL, and LLM_MODEL.
        llm_base_url:      Optional base URL for OpenAI-compatible API.
        primary_metric:    Name of the metric used for "best" reduction. When empty,
                           summary_stats omits a single-scalar best (the previous
                           naive max-over-all-values produced absurd results when the
                           metrics dict mixed measurements with input parameters like
                           nnz / M / K). Resolved upstream from evaluation_criteria.json.
        higher_is_better:  "true" or "false" — direction for primary_metric reduction.
                           Accepted as a string because workflow.yaml templating renders
                           bool values as their str() form.

    Returns:
        A digest-bound ``ari.science-data/v1`` document. Executed facts live in
        ``raw``, formula-derived values and claims in ``derived``, and model
        prose in the non-claimable ``interpretation`` section.
    """
    _hib = str(higher_is_better).strip().lower() not in ("false", "0", "no", "")
    try:
        nodes = _load_nodes(nodes_json_path)
    except Exception as e:
        return {"error": str(e), "configurations": []}

    # ── Best-effort: load node_report.json for every node ──
    reports = _load_node_reports_for_tree(nodes_json_path, nodes)

    # Filter to successful nodes with real measurements
    good_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    if not good_nodes:
        return {
            "error": "No successful nodes with real data found",
            "configurations": [],
        }

    # ── results.json (typed coding-skill emit_results contract) ──
    # Each node's work_dir may contain a typed payload that splits inputs
    # (params) from outputs (measurements/predictions/scores). When present,
    # we propagate it onto configurations[*] so paper-writing and figure
    # generation can tell apart "what we ran on" from "what we measured" —
    # otherwise the metrics dict mixes both and per_key_summary's reduction
    # treats input sizes (nnz, M, K) as candidate maxima.
    _ckpt_dir = Path(nodes_json_path).expanduser().resolve().parent
    _workspace = (
        _ckpt_dir.parent.parent
        if _ckpt_dir.parent.name == "checkpoints"
        else _ckpt_dir.parent
    )
    _run_id = _ckpt_dir.name

    def _node_results_json(nid: str) -> dict:
        """Return one validated canonical measurement projection."""
        if not nid:
            return {}
        cand = _workspace / "experiments" / _run_id / nid / "results.json"
        if not cand.is_file():
            cand = _workspace / "experiments" / nid / "results.json"
            if not cand.is_file():
                return {}
        try:
            data = json.loads(cand.read_text())
            measurement_set = parse_measurement_document(data)
        except (MeasurementDocumentError, OSError, ValueError):
            return {}
        return {
            "params": measurement_set.parameters,
            "measurements": {
                record.metric_id: record.value
                for record in measurement_set.measurements
            },
            "measurement_records": [
                record.model_dump(mode="json")
                for record in measurement_set.measurements
            ],
            "predictions": measurement_set.predictions,
            "scores": measurement_set.scores,
            "artifact_digests": measurement_set.artifact_digests,
            "_provenance": {
                record.metric_id: record.provenance
                for record in measurement_set.measurements
                if record.provenance is not None
            },
            "typed_schema_version": measurement_set.schema_version,
            "source_schema": measurement_document_format(data),
        }

    def _node_provenance_union(nid: str) -> dict:
        """Union the _provenance maps across EVERY results*.json variant in the node
        dir. emit_results documents non-default file names ("results_seed42.json"), so
        the idea-owned requirement-flag evidence (a measured-ceiling / correctness tag)
        must surface to the gate regardless of which variant carried it. The canonical
        results.json wins on conflict (it sorts first). Best-effort."""
        out: dict = {}
        if not nid:
            return out
        for base in (
            _workspace / "experiments" / _run_id / nid,
            _workspace / "experiments" / nid,
        ):
            if not base.is_dir():
                continue
            for p in sorted(base.glob("results*.json")):
                try:
                    d = json.loads(p.read_text())
                    measurement_set = parse_measurement_document(d)
                except (MeasurementDocumentError, OSError, ValueError):
                    continue
                for record in measurement_set.measurements:
                    if record.provenance is not None:
                        out.setdefault(record.metric_id, record.provenance)
        return out

    # Map node_id → typed payload (only stores entries that exist on disk).
    typed_results: dict[str, dict] = {}
    for n in good_nodes:
        nid = n.get("id") or n.get("node_id") or ""
        rj = _node_results_json(nid)
        if rj:
            typed_results[nid] = rj

    # Build ranked configurations (no domain-specific sorting — pass all to LLM)
    # Include eval_summary and label so downstream stages (paper writing,
    # reproducibility check) can associate each metric with the experiment
    # that produced it (kernel type, configuration, setup).
    #
    # Only a validated results.json measurement contract is authoritative.
    # Historical evaluator-produced `_params_dict` / `_measurements_dict`
    # values were model output and are deliberately not adopted as facts.
    ranked: list[dict] = []
    for i, n in enumerate(good_nodes):
        nid = n.get("id") or n.get("node_id") or ""
        cfg: dict = {
            "rank": i + 1,
            "parameters": {},
            "metrics": n.get("metrics", {}),
            "label": n.get("label", ""),
            "eval_summary": (n.get("eval_summary") or "")[:400],
        }
        rj = typed_results.get(nid) or {}
        if rj:
            if isinstance(rj.get("params"), dict):
                cfg["parameters"] = dict(rj["params"])
            if isinstance(rj.get("measurements"), dict):
                cfg["measurements"] = dict(rj["measurements"])
            if isinstance(rj.get("predictions"), dict):
                cfg["predictions"] = dict(rj["predictions"])
            if isinstance(rj.get("scores"), dict):
                cfg["scores"] = dict(rj["scores"])
            cfg["measurement_records"] = list(rj["measurement_records"])
            cfg["measurement_artifact_digests"] = list(rj["artifact_digests"])
            # Metric-correctness contract: carry the agent-emitted measurement
            # provenance ({metric_name: "microbench"|"benchmark"|"correctness"|...}) so
            # the hard gate can confirm a contract's required ceilings were MEASURED and
            # a correctness check was run, not assumed. Union across results*.json
            # variants so a non-default emit_results filename still surfaces evidence.
            # Domain-neutral: just a pass-through field.
            _prov_union = _node_provenance_union(nid)
            if _prov_union:
                cfg["_provenance"] = _prov_union
            cfg["_typed_schema_version"] = rj["typed_schema_version"]
            cfg["_typed_compatibility"] = rj["source_schema"]
            cfg["_typed_source"] = "results.json"
        ranked.append(cfg)

    # ── per_key_summary: exclude declared input parameters ──
    # Once a node declares a validated results.json split, its param keys are inputs
    # by construction and must NOT participate in best/min/max reductions
    # (they used to dominate via raw size — nnz=3.84M was bigger than any
    # GFlops/s measurement). Build a global "input_keys" set across nodes
    # and skip them in per_key_summary. Also exclude the reserved "_…"
    # bookkeeping keys that the evaluator stores on metrics.
    input_keys: set[str] = set()
    for rj in typed_results.values():
        if isinstance(rj.get("params"), dict):
            input_keys.update(str(k) for k in rj["params"].keys())

    def _is_reserved(k: str) -> bool:
        # Underscore-prefixed keys are internal bookkeeping (axis scores,
        # composite, comparison flag, typed-split mirrors). They're not
        # measurements and must never appear in per_key_summary.
        return isinstance(k, str) and k.startswith("_")

    all_keys: list[str] = []
    for n in good_nodes:
        for k in n.get("metrics", {}):
            if k in all_keys or k in input_keys or _is_reserved(k):
                continue
            all_keys.append(k)
    per_key_summary: dict = {}
    for k in all_keys:
        vals = [
            n["metrics"][k]
            for n in good_nodes
            if k in n.get("metrics", {}) and isinstance(n["metrics"][k], (int, float))
        ]
        if vals:
            per_key_summary[k] = {
                "best_value": max(vals),
                "min": min(vals),
                "max": max(vals),
                "n": len(vals),
            }

    # ── LLM analysis: read top nodes' artifacts and extract scientific context ──
    model = _resolve_llm_model(llm_model)
    api_base = _resolve_llm_base_url(llm_base_url)

    # ── Report-driven path: when reports exist, narrow the LLM input via
    #    filter_nodes(for_synthesis) and pull source bytes via the same
    #    selection that generate_ear publishes (FR-SS-5 contract).
    report_driven = False
    selected_source_blob = ""
    selected_node_blocks: list[str] = []
    best_id_for_synth = _resolve_best_node_for_synthesis(nodes)
    if reports and best_id_for_synth:
        try:
            from ari.public import node_selection as _ns

            kept = _ns.filter_nodes(
                nodes,
                reports,
                "for_synthesis",
                always_include_node_ids={best_id_for_synth},
            )
            # Build compact per-report blocks.
            for n in kept:
                rep = reports.get(n.get("id")) or {}
                label = str(n.get("label") or "?").upper()
                depth = n.get("depth", 0)
                metrics = json.dumps(n.get("metrics") or {}, ensure_ascii=False)
                fc = rep.get("files_changed") or {}
                added = [e.get("path") for e in (fc.get("added") or [])][:8]
                modified = [e.get("path") for e in (fc.get("modified") or [])][:8]
                deleted = [e.get("path") for e in (fc.get("deleted") or [])][:8]
                sa = rep.get("self_assessment") or {}
                lines = [
                    f"[{label} depth={depth}]",
                    f"  metrics: {metrics}",
                ]
                if added:
                    lines.append(f"  files_added: {added}")
                if modified:
                    lines.append(f"  files_modified: {modified}")
                if deleted:
                    lines.append(f"  files_deleted: {deleted}")
                if sa.get("headline"):
                    lines.append(f"  headline: {sa['headline'][:240]}")
                if sa.get("concerns"):
                    lines.append(f"  concerns: {sa['concerns'][:5]}")
                if rep.get("build_command"):
                    lines.append(f"  build: {rep['build_command'][:160]}")
                if rep.get("run_command"):
                    lines.append(f"  run: {rep['run_command'][:160]}")
                # Compute-resource provenance (where this measurement came from).
                # node_report exposes these as top-level fields when ari.agent.run_env
                # captured them; absent for legacy runs.
                _exec = rep.get("executor", "")
                _host = rep.get("hostname", "")
                _jid = rep.get("slurm_job_id", "")
                _part = rep.get("slurm_partition", "")
                _cpu = rep.get("cpu_info") or {}
                if _exec or _host:
                    parts = [
                        f"executor={_exec or 'unknown'}",
                        f"host={_host or 'unknown'}",
                    ]
                    if _part:
                        parts.append(f"partition={_part}")
                    if _jid:
                        parts.append(f"slurm_job={_jid}")
                    if _cpu.get("model"):
                        parts.append(
                            f"cpu={_cpu.get('model')[:60]} ({_cpu.get('threads', '?')}t)"
                        )
                    lines.append("  ran_on: " + ", ".join(parts))
                selected_node_blocks.append("\n".join(lines))

            # Pull verbatim source bytes — same selection used by generate_ear.
            from pathlib import Path as _P

            sel = _ns.select_source_files_for_publication(
                nodes,
                reports,
                best_id_for_synth,
            )
            ckpt_dir = _P(nodes_json_path).expanduser().resolve().parent
            workspace = (
                ckpt_dir.parent.parent
                if ckpt_dir.parent.name == "checkpoints"
                else ckpt_dir.parent
            )
            run_id_for_src = ckpt_dir.name

            def _wd(nid: str):
                cand = workspace / "experiments" / run_id_for_src / nid
                if cand.is_dir():
                    return cand
                return workspace / "experiments" / nid

            loaded = _ns.load_selected_sources(
                sel,
                work_dir_for=_wd,
                size_budget=16384,
            )
            for rel_path, payload in sorted(loaded.items()):
                try:
                    text = payload["bytes"].decode("utf-8", errors="replace")
                except Exception:
                    continue
                selected_source_blob += (
                    f"\n# === {rel_path} (from {payload['from_node_id']}) ===\n"
                    + text
                    + "\n"
                )

            if selected_node_blocks:
                report_driven = True
        except Exception:
            report_driven = False

    if report_driven:
        report_blob = "\n\n".join(selected_node_blocks)
        analysis_prompt = build_interpretation_prompt(
            report_blob,
            selected_source_blob,
        )
    else:
        # Missing reports are an explicit unavailable annotation.  New runs do
        # not inspect trace_log or arbitrary source paths as a substitute.
        analysis_prompt = None

    # ── summary_stats: direction-aware reduction over the primary metric ──
    # Previously this was max() over every per_key_summary entry, which
    # picked the largest *number* regardless of what it represented (often
    # an input parameter like nnz=3,840,000). When a primary_metric is
    # known, reduce only over that key with the correct direction; when it
    # is not, omit the scalar best entirely rather than fabricate one.
    summary_stats: dict = {"count": len(ranked)}
    # typed_split_coverage: how many ranked configs have an authoritative
    # params/measurements split, broken down by source. Lets us monitor
    # adoption of the emit_results contract over time without grepping
    # individual configurations.
    _ts_counts: dict[str, int] = {"results.json": 0, "none": 0}
    for c in ranked:
        src = c.get("_typed_source") or "none"
        _ts_counts[src] = _ts_counts.get(src, 0) + 1
    summary_stats["typed_split_coverage"] = _ts_counts
    pm = (primary_metric or "").strip()
    if pm:
        summary_stats["primary_metric"] = pm
        summary_stats["direction"] = "higher_is_better" if _hib else "lower_is_better"
        pm_vals = [
            n["metrics"][pm]
            for n in good_nodes
            if pm in n.get("metrics", {}) and isinstance(n["metrics"][pm], (int, float))
        ]
        if pm_vals:
            summary_stats["primary_metric_best"] = (
                max(pm_vals) if _hib else min(pm_vals)
            )
            summary_stats["primary_metric_n"] = len(pm_vals)
    out = {
        "configurations": ranked,
        "per_key_summary": per_key_summary,
        "summary_stats": summary_stats,
        "report_driven": report_driven,
    }

    # ── Declared metric-correctness contract (Phases 2-4 + plan-fidelity claims) ──
    # make_metric_spec persisted the run-level metric_contract (idea-derived: concept
    # invariants, correctness, required_measured, and falsifiable claims) next to
    # tree.json. Graft it onto science_data so the hard gate enforces the DECLARED
    # contract (not just the universal invariant registry) -- without this the
    # correctness / required_measured / recompute / claim_evidence_missing checks are
    # inert. Read BEFORE the invariant scan so declared bound invariants are scanned
    # too. Best-effort; absent on legacy runs => the gate's contract checks no-op.
    _mc = _load_run_metric_contract(nodes_json_path)
    if _mc is not None:
        out["metric_contract"] = _mc

    # ── Metric-correctness Phase 4: annotate physically-impossible metric values
    # (e.g. a normalized metric > 1) using the SAME universal invariant registry
    # the hard gate blocks on (ari-core, single source of truth — no duplicated
    # domain logic). The paper writer is told to avoid `_anomalous_metrics`; the
    # gate independently blocks the final paper if such a value survives. Safe /
    # additive; never breaks science_data generation.
    try:
        from ari.public.claim_gate import scan_science_data as _scan_invariants  # type: ignore

        _anoms = _scan_invariants(out)
        if _anoms:
            out["_anomalies"] = _anoms
            _by_cfg: dict = {}
            for _a in _anoms:
                _by_cfg.setdefault(str(_a.get("config_id")), []).append(
                    _a.get("metric")
                )
            for _c in ranked:
                _cid = str(
                    _c.get("config_id")
                    or _c.get("label")
                    or _c.get("node_id")
                    or _c.get("rank")
                    or "?"
                )
                if _cid in _by_cfg:
                    _c["_anomalous_metrics"] = sorted(set(_by_cfg[_cid]))
    except Exception:
        pass

    # ── Research Contract substrate: candidate claims[] / numeric_assertions[] ──
    # Story2Proposal integration Phase A. Deterministically derived from the
    # executed-node evidence (results.json measurements/scores or node metrics);
    # operands carry real node_id + metric_path. figures[] start empty and are
    # late-bound by the paper post-processor. Claim prose is a templated seed the
    # writer rewrites while preserving % CLAIM anchors; the hard gate re-verifies
    # the numbers. Failure here must never break science_data generation.
    try:
        from claims import build_science_claims as _build_claims  # type: ignore
    except Exception:  # pragma: no cover - import shape varies by entrypoint
        try:
            from src.claims import build_science_claims as _build_claims  # type: ignore
        except Exception:
            _build_claims = None  # type: ignore
    if _build_claims is not None:
        try:
            # Per-node execution environment from node_report (executor / CPU /
            # arch) — universal provenance, no cluster/domain knowledge. Lets the
            # claim generator tag operands and (under same_environment intent)
            # avoid cross-host comparisons.
            _node_env: dict = {}
            for _nid, _rep in (reports or {}).items():
                _ci = _rep.get("cpu_info") or {}
                _node_env[_nid] = {
                    "executor": _rep.get("executor", ""),
                    "cpu_model": _ci.get("model", ""),
                    "arch": _ci.get("arch", ""),
                }
            # Injected research intent (P4): "any" (default) | "same_environment".
            _cmp_scope = os.environ.get("ARI_COMPARISON_SCOPE", "").strip() or "any"
            _claimable_ids = {
                _nid
                for _nid, _typed in typed_results.items()
                if _typed.get("source_schema") == "canonical"
                and (_typed.get("measurement_records") or [])
                and all(
                    _record.get("execution_status") == "completed"
                    for _record in _typed.get("measurement_records") or []
                )
            }
            _claimable_nodes = [
                _node
                for _node in good_nodes
                if (_node.get("id") or _node.get("node_id")) in _claimable_ids
            ]
            _contract = _build_claims(
                _claimable_nodes,
                typed_results,
                (
                    ((_mc or {}).get("metric_contract") or {}).get("name")
                    or primary_metric
                ),
                (
                    ((_mc or {}).get("metric_contract") or {}).get("direction")
                    != "lower"
                    if _mc
                    else _hib
                ),
                node_env=_node_env,
                comparison_scope=_cmp_scope,
                run_id=_run_id,
                metric_unit=str(
                    ((_mc or {}).get("metric_contract") or {}).get("unit") or ""
                ),
                tolerance=(
                    ((_mc or {}).get("metric_contract") or {}).get("tolerance")
                    if _mc
                    else None
                ),
            )
            out["claims"] = _contract.get("claims", [])
            out["numeric_assertions"] = _contract.get("numeric_assertions", [])
            # Tag each science-facing configuration with a stable handle
            # (config_id) + its execution environment, and build a resolution map
            # so the writer can DECLARE assertions referencing configs (forward
            # declaration, Story2Proposal (c)) and the hard gate can resolve
            # config_id -> node_id without exposing node_id in the paper-facing
            # configuration. ranked[i] is built from good_nodes[i] (same order).
            _config_nodes: dict = {}
            for _i, _n in enumerate(good_nodes):
                if _i >= len(ranked):
                    break
                _nid = _n.get("id") or _n.get("node_id") or ""
                _cid = f"cfg{_i + 1}"
                ranked[_i]["config_id"] = _cid
                if _nid in _node_env:
                    ranked[_i]["environment"] = _node_env[_nid]
                # Carry metric VALUES (not just keys): the writer must pick the
                # metric_key whose recorded value equals the number it states, so
                # it has to SEE the values to declare operands correctly.
                _metric_vals = {
                    k: v
                    for k, v in (_n.get("metrics") or {}).items()
                    if isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and not str(k).startswith("_")
                }
                _config_nodes[_cid] = {
                    "node_id": _nid,
                    "environment": _node_env.get(_nid, {}),
                    "metrics": _metric_vals,
                }
            # Internal (underscore) — resolution map for the writer's forward
            # declarations; not part of the paper-facing science surface.
            out["_config_nodes"] = _config_nodes
        except Exception as _claim_exc:  # pragma: no cover - defensive
            out["claims"] = []
            out["numeric_assertions"] = []
            out["_claims_error"] = str(_claim_exc)
    try:
        _sections = build_deterministic_sections(
            nodes_json_path=nodes_json_path,
            nodes=nodes,
            reports=reports,
            typed_results=typed_results,
            deterministic_projection=out,
            metric_contract=_mc,
            primary_metric=(
                str(
                    ((_mc or {}).get("metric_contract") or {}).get("name")
                    or primary_metric
                )
            ),
            higher_is_better=(
                ((_mc or {}).get("metric_contract") or {}).get("direction") != "lower"
                if _mc
                else _hib
            ),
        )
        _interpretation = await annotate_science_data(
            nodes_json_path=nodes_json_path,
            raw_digest=_sections.raw.raw_digest,
            prompt=analysis_prompt,
            model=model,
            api_base=api_base,
            report_driven=report_driven,
        )
        return assemble_science_data(_sections, _interpretation).model_dump(mode="json")
    except Exception as _science_exc:
        return {
            "error": f"ScienceDataV1 materialization failed: {type(_science_exc).__name__}: {_science_exc}",
            "configurations": [],
        }


# ──────────────────────────────────────────────────────────────────────────
# Experiment Artifact Repository (EAR) — issue #4
# ──────────────────────────────────────────────────────────────────────────


def _safe_run(cmd: list[str], timeout: int = 10) -> str:
    """Run a shell command and return its trimmed stdout, or '' on failure."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _capture_environment() -> dict:
    """Capture python version, platform, key packages, and hardware specs."""
    env: dict = {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "hostname": platform.node(),
    }
    # Best-effort: pip list (may take a few seconds; cap timeout)
    pip_out = _safe_run(
        [sys.executable, "-m", "pip", "list", "--format=json"], timeout=15
    )
    if pip_out:
        try:
            env["installed_packages"] = json.loads(pip_out)
        except Exception:
            env["installed_packages"] = []
    else:
        env["installed_packages"] = []
    # Hardware specs (best-effort)
    cpu_count = os.cpu_count() or 0
    env["cpu_count"] = cpu_count
    # Linux memory
    try:
        with open("/proc/meminfo") as fh:
            meminfo = {}
            for line in fh:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = v.strip()
            if "MemTotal" in meminfo:
                env["mem_total"] = meminfo["MemTotal"]
    except Exception:
        pass
    return env


# ── PR #C helpers (node_report-driven generate_ear) ──────────────────────

# Whitelist of source-file extensions and basenames that may end up under
# ear/code/. These are the "publishable code surfaces"; everything else is
# either an experiment output (not published; reproduce.sh regenerates) or
# an internal artefact (logs, build caches).
_EAR_CODE_EXTS: frozenset[str] = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".hh",
        ".f",
        ".f90",
        ".for",
        ".py",
        ".ipynb",
        ".sh",
        ".bash",
        ".zsh",
        ".rs",
        ".go",
        ".java",
        ".scala",
        ".kt",
        ".cu",
        ".cuda",
        ".cl",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".mk",
        ".cmake",
        ".toml",
        ".yaml",
        ".yml",
        ".cfg",
        ".ini",
        ".r",
        ".jl",
        ".lua",
        ".swift",
        ".proto",
        ".thrift",
        ".sql",
    }
)

_EAR_CODE_BASENAMES: frozenset[str] = frozenset(
    {
        "Makefile",
        "makefile",
        "GNUmakefile",
        "CMakeLists.txt",
        "Dockerfile",
        ".dockerignore",
        "requirements.txt",
        "environment.yml",
        "environment.yaml",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "MANIFEST.in",
        "Cargo.toml",
        "go.mod",
        "package.json",
        "tsconfig.json",
        "build.gradle",
        "pom.xml",
        ".gitignore",
    }
)

# Hard blocklist (filename or filename pattern). These are never copied into
# ear/code/ even if their extension matches the whitelist.
_EAR_CODE_BLOCKLIST_NAMES: frozenset[str] = frozenset(
    {
        "memory_access.jsonl",
        "viz_access.jsonl",
        "cost_trace.jsonl",
        "nodes_tree.json",
        "tree.json",
        "bfts_tree.json",
        "science_data.json",
        "raw_metrics.json",
        "eval_scores.json",
        "node_report.json",
        ".DS_Store",
        "Thumbs.db",
    }
)

# Subdirectories never recursed into.
_EAR_CODE_BLOCKLIST_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".cache",
        ".pytest_cache",
        "__pycache__",
        "node_modules",
        ".ipynb_checkpoints",
        ".venv",
        "venv",
        "build",
        "dist",
        "target",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
    }
)

_EAR_CODE_FILE_SIZE_CAP = 256 * 1024  # 256KB / file


def _is_publishable_code_file(rel_path: str, full_path: Path) -> bool:
    """Return True if *rel_path* should be copied into ear/code/."""
    name = Path(rel_path).name
    if name in _EAR_CODE_BLOCKLIST_NAMES:
        return False
    # Block anything under a known build / cache dir.
    for part in Path(rel_path).parts[:-1]:
        if part in _EAR_CODE_BLOCKLIST_DIRS:
            return False
    # slurm-*.{out,err} are logs.
    if name.startswith("slurm-") and (name.endswith(".out") or name.endswith(".err")):
        return False
    if name in _EAR_CODE_BASENAMES:
        return True
    suffix = Path(name).suffix.lower()
    if suffix in _EAR_CODE_EXTS:
        return True
    if name.startswith("Dockerfile."):
        return True
    return False


def _resolve_pm_run_id(ckpt: Path) -> tuple[Path, str]:
    """Return (workspace_root, run_id) inferred from *ckpt*.

    The PathManager mirrors `experiments/{run_id}/{node_id}/` as a sibling of
    `checkpoints/{run_id}/`. Some test fixtures place experiments alongside
    the checkpoint instead, so we accept that fallback as well.
    """
    return (
        ckpt.parent.parent if ckpt.parent.name == "checkpoints" else ckpt.parent,
        ckpt.name,
    )


def _node_work_dir(workspace: Path, run_id: str, node_id: str) -> Path:
    """Resolve the on-disk work_dir for a node, with sensible fallbacks."""
    candidates = [
        workspace / "experiments" / run_id / node_id,
        workspace / "experiments" / node_id,  # test fixtures sometimes flatten this.
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def _load_node_reports(
    workspace: Path, run_id: str, nodes: list[dict]
) -> dict[str, dict]:
    """Load every available `node_report.json` keyed by node id."""
    reports: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        wd = _node_work_dir(workspace, run_id, nid)
        rp = wd / "node_report.json"
        if rp.is_file():
            try:
                reports[nid] = json.loads(rp.read_text())
            except Exception:
                continue
    return reports


def _resolve_best_node(nodes: list[dict]) -> dict | None:
    """argmax(_scientific_score), with `validation`-label tie-break and depth secondary.

    Excludes RQGM-erased nodes (``_valid_for_frontier: false``) — an erased
    lineage must not become the published code / EAR winner. Inert on
    non-RQGM trees (key never written).
    """
    real = [
        n for n in nodes
        if n.get("has_real_data") and n.get("metrics")
        and (n.get("metrics") or {}).get("_valid_for_frontier", True) is not False
    ]
    if not real:
        return None

    def _score(n: dict) -> float:
        return float((n.get("metrics") or {}).get("_scientific_score") or 0.0)

    real.sort(
        key=lambda n: (
            _score(n),
            1 if str(n.get("label") or "").lower() == "validation" else 0,
            int(n.get("depth") or 0),
        ),
        reverse=True,
    )
    return real[0]


def _gather_uploads(checkpoint_dir: Path) -> list[Path]:
    uploads = checkpoint_dir / "uploads"
    if not uploads.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(uploads.rglob("*")):
        if p.is_file():
            out.append(p)
    return out


def _gather_top_level_figures(checkpoint_dir: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.pdf", "*.png", "*.svg", "*.jpg", "*.jpeg"):
        for f in sorted(checkpoint_dir.glob(ext)):
            if f.is_file():
                out.append(f)
    return out


def _changed_files_summary(report: dict, *, max_paths: int = 5) -> str:
    """Compact deterministic description derived from structured file changes."""
    changed = report.get("files_changed") or {}
    parts: list[str] = []
    for bucket in ("added", "modified", "deleted"):
        paths = [
            str(entry.get("path") if isinstance(entry, dict) else entry)
            for entry in (changed.get(bucket) or [])
            if (entry.get("path") if isinstance(entry, dict) else entry)
        ]
        if paths:
            parts.append(f"{bucket}: {', '.join(paths[:max_paths])}")
    return "; ".join(parts)


def _render_evolution_md(chain: list[dict], reports: dict[str, dict]) -> str:
    """Deterministic EVOLUTION.md from the for_narrative chain.

    Step number + label is the only identifier the reader sees — opaque
    `node_id` and `depth_in_chain` strings are excluded by spec (FR-E-RENDER-2).
    """
    if not chain:
        return "# Evolution\n\n_No nodes were retained for the narrative._\n"

    # Pick the primary metric to track per-step: the metric with the most
    # successful step appearances.
    metric_counter: dict[str, int] = {}
    for n in chain:
        for k in n.get("metrics") or {}:
            if k.startswith("_"):
                continue
            metric_counter[k] = metric_counter.get(k, 0) + 1
    primary_metric = (
        max(metric_counter, key=metric_counter.get) if metric_counter else None
    )
    best_id = chain[-1].get("id")

    rows: list[str] = ["# Evolution", "", "## Search trajectory", ""]
    rows.append("| Step | Label | Headline metric | Δ vs parent | What changed |")
    rows.append("|---|---|---|---|---|")

    prev_metric: float | None = None
    per_step_blocks: list[str] = []
    for idx, node in enumerate(chain, start=1):
        nid = node.get("id")
        report = reports.get(nid) or {}
        label = str(node.get("label") or "other")
        if nid == best_id:
            label_disp = f"{label} (best)"
        else:
            label_disp = label
        # Headline metric value.
        m_val: float | None = None
        if primary_metric:
            v = (node.get("metrics") or {}).get(primary_metric)
            if isinstance(v, (int, float)):
                m_val = float(v)
        m_str = f"{m_val:.3g} {primary_metric}" if m_val is not None else "—"
        # Δ vs parent.
        if m_val is not None and prev_metric and prev_metric != 0:
            pct = (m_val - prev_metric) / abs(prev_metric) * 100.0
            sign = "+" if pct >= 0 else ""
            delta_str = f"{sign}{pct:.0f}%"
        elif m_val is not None and prev_metric is None:
            delta_str = "—"
        else:
            delta_str = "—"
        prev_metric = m_val if m_val is not None else prev_metric
        delta_text = (
            (report.get("delta_vs_parent") or "").replace("|", " ").splitlines()
        )
        delta_text_first = delta_text[0] if delta_text else ""
        if not delta_text_first:
            delta_text_first = (
                ((report.get("self_assessment") or {}).get("headline") or "")
                .replace("|", " ")
                .splitlines()[:1]
            )
            delta_text_first = delta_text_first[0] if delta_text_first else ""
        rows.append(
            f"| {idx} | {label_disp} | {m_str} | {delta_str} | "
            f"{change_text_first[:90]} |"
        )

        block = [f"### Step {idx}: {label_disp}", ""]
        if change_text_first:
            block.append(f"**What changed:** {change_text_first}")
            block.append("")
        sa = report.get("self_assessment") or {}
        if sa.get("headline"):
            block.append(f"**Headline:** {sa['headline']}")
            block.append("")
        if sa.get("concerns"):
            block.append("**Concerns:**")
            for c in sa["concerns"]:
                block.append(f"- {c}")
            block.append("")
        if nid == best_id and report.get("next_steps_hints"):
            block.append("**Suggested next steps:**")
            for h in report["next_steps_hints"]:
                block.append(f"- {h}")
            block.append("")
        per_step_blocks.append("\n".join(block).rstrip())

    rows.append("")
    rows.append("## Per-step details")
    rows.append("")
    rows.extend(per_step_blocks)
    return "\n".join(rows).rstrip() + "\n"


_BARE_VAR_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _is_substantive_command(line: str) -> bool:
    """Whether a single line actually invokes something (vs env-var setup)."""
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    if s.startswith(
        ("set ", "export ", "source ", "cd ", "module ", "ulimit ", "shopt ")
    ):
        return False
    if _BARE_VAR_ASSIGN_RE.match(s):
        return False
    return True


def _find_runnable_script_in_code(code_dir: Path) -> str | None:
    """Locate a script in code/ that can be wrapped as the run command.

    Preference: ``run_job.sh`` (BFTS executor convention) → ``run.sh`` →
    ``main.sh`` → first executable ``*.sh``. Returns the path RELATIVE to
    ``code_dir`` (e.g. ``run_job.sh``), or None if nothing usable.
    """
    if not code_dir.is_dir():
        return None
    for name in ("run_job.sh", "run.sh", "main.sh"):
        if (code_dir / name).is_file():
            return name
    for p in sorted(code_dir.glob("*.sh")):
        return p.name
    return None


def _render_reproduce_sh(
    best_report: dict | None, code_dir: Path | None = None
) -> str | None:
    """Deterministic reproduce.sh body, or None if no usable input.

    Strategy:
      1. Build from ``best_report.{build_command, run_command}`` when at
         least one is substantive (not just env-var setup).
      2. Otherwise fall back to wrapping the actual script the BFTS executor
         ran (``code/run_job.sh`` or similar). Bug 3b workaround: when the
         node_report's build/run extraction degenerated to env-var-only
         lines, the real compile + run are still in ``code/run_job.sh``.
      3. Returns None when both inputs are absent.
    """
    build = (best_report.get("build_command") or "").strip() if best_report else ""
    run = (best_report.get("run_command") or "").strip() if best_report else ""
    has_substantive = _is_substantive_command(build) or _is_substantive_command(run)

    if has_substantive:
        lines = [
            "#!/usr/bin/env bash",
            "# Generated by ARI generate_ear from node_report.json::{build_command, run_command}.",
            "# Manual review recommended: absolute paths and machine-specific flags may need",
            "# adjustment for your environment.",
            "set -euo pipefail",
            'cd "$(dirname "$0")/code"',
            "",
        ]
        if build:
            lines.append(build)
        if run:
            lines.append(run)
        return "\n".join(lines) + "\n"

    # Fallback: wrap the runnable script in code/.
    wrapped = _find_runnable_script_in_code(code_dir) if code_dir is not None else None
    if not wrapped:
        return None
    return (
        "#!/usr/bin/env bash\n"
        "# Generated by ARI generate_ear (fallback wrapper).\n"
        "# node_report.json::{build_command, run_command} did not contain\n"
        "# substantive commands; this script invokes the executor's actual\n"
        f"# run script ({wrapped}) verbatim.\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")/code"\n'
        "\n"
        "# Provide common build env vars in case the inner script omits them.\n"
        'export CXX="${CXX:-g++}"\n'
        'export CXXFLAGS="${CXXFLAGS:--O3 -march=native -fopenmp -std=c++17}"\n'
        "\n"
        f"bash {wrapped}\n"
        "rc=$?\n"
        "\n"
        "# Promote per-run output artifacts from code/ up to the repo root so\n"
        "# the rubric's expected_artifacts (repo-relative paths like\n"
        '# "results.csv") can match them. The inner script writes outputs in\n'
        "# its CWD (= code/), but the PaperBench grader looks for them at\n"
        "# repo root. Idempotent — re-runs overwrite stale copies.\n"
        "shopt -s nullglob\n"
        "for _f in *.csv *.tsv *.pdf *.png *.svg *.jpg *.jpeg *.json *.log *.txt; do\n"
        '    [ "$_f" = "run.log" ] && continue   # surfaced via stdout below instead\n'
        '    cp -f "$_f" "../$_f"\n'
        "done\n"
        "shopt -u nullglob\n"
        "\n"
        "# Surface stderr that the inner script may have redirected to a\n"
        "# local log so the Phase 2 grader (which only sees the runner-\n"
        "# captured stdout) can inspect it too.\n"
        "if [ -f run.log ]; then\n"
        '    echo "--- code/run.log (stderr from inner script) ---"\n'
        "    cat run.log\n"
        "fi\n"
        "\n"
        'exit "$rc"\n'
    )


def _render_readme(
    *,
    goal: str,
    best_node: dict | None,
    best_report: dict | None,
    impl_overview: dict | None,
    has_data_dir: bool,
    has_figures_dir: bool,
    has_evolution: bool,
    has_environment: bool,
    has_license: bool,
    has_reproduce_sh: bool,
) -> str:
    title = goal.strip() or "Experiment Artifact Repository"
    title = title.splitlines()[0][:200]

    lines = [f"# {title}", ""]
    if best_report or best_node:
        sa = (best_report or {}).get("self_assessment") or {}
        headline = (sa.get("headline") or "").strip()
        if not headline and best_node:
            headline = (best_node.get("eval_summary") or "").strip()
        lines.append("## Headline result")
        lines.append("")
        if headline:
            lines.append(headline)
            lines.append("")
        metrics = (
            (best_report or {}).get("metrics") or (best_node or {}).get("metrics") or {}
        )
        if metrics:
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for k, v in metrics.items():
                if k.startswith("_"):
                    continue
                lines.append(f"| {k} | {v} |")
            lines.append("")

    lines.append("## Build & run")
    lines.append("")
    if has_reproduce_sh:
        lines.append("```bash")
        lines.append("bash reproduce.sh")
        lines.append("```")
    else:
        lines.append(
            "_No reproduce.sh was generated; see code/ for build instructions._"
        )
    lines.append("")

    lines.append("## Layout")
    lines.append("")
    lines.append(
        "- `code/` — verbatim source files from contributing nodes in the best chain"
    )
    if has_data_dir:
        lines.append(
            "- `data/` — input data files mirrored from the uploaded "
            "dataset. Experiment outputs (CSV etc.) are NOT included; "
            "they are regenerated by `reproduce.sh`."
        )
    if has_figures_dir:
        lines.append("- `figures/` — figures referenced by the paper")
    if has_environment:
        lines.append("- `environment.json` — captured runtime environment")
    if has_license:
        lines.append("- `LICENSE` — license declared by the author")
    lines.append("")

    if impl_overview and isinstance(impl_overview, dict):
        arch = (impl_overview.get("architecture") or "").strip()
        if arch:
            lines.append("## Architecture")
            lines.append("")
            lines.append(arch)
            lines.append("")
        algos = impl_overview.get("key_algorithms") or []
        if algos:
            lines.append("## Key algorithms")
            lines.append("")
            for a in algos:
                if isinstance(a, dict) and a.get("pseudocode"):
                    lines.append(f"### {a.get('name', '(unnamed)')}")
                    lines.append("")
                    lines.append("```")
                    lines.append(a["pseudocode"])
                    lines.append("```")
                    lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(
        "Source and data files are verbatim copies from the *contributing* "
        "nodes in the best chain (determined deterministically via "
        "`node_report::files_changed`). README and reproduce.sh "
        "are rendered deterministically from each node's `node_report.json`. "
        "LLM does not modify code or data files. The full search "
        "trajectory and per-file origin audit are kept alongside the "
        "checkpoint as `EVOLUTION.md` and `_provenance.json` (outside "
        "this artifact)."
    )
    return "\n".join(lines).rstrip() + "\n"


def _read_publish_yaml(checkpoint_dir: Path) -> dict:
    py_path = checkpoint_dir / "ear" / "publish.yaml"
    if not py_path.is_file():
        return {}
    try:
        import yaml as _yaml

        return _yaml.safe_load(py_path.read_text()) or {}
    except Exception:
        return {}


_LICENSE_TEMPLATE_DIR = Path(__file__).parent / "licenses"
_SPDX_TO_TEMPLATE: dict[str, str] = {
    "MIT": "mit.txt",
    "Apache-2.0": "apache-2.0.txt",
    "BSD-3-Clause": "bsd-3-clause.txt",
    "GPL-3.0": "gpl-3.0.txt",
    "GPL-3.0-only": "gpl-3.0.txt",
    "GPL-3.0-or-later": "gpl-3.0.txt",
    "CC-BY-4.0": "cc-by-4.0.txt",
}


def _write_license_if_needed(
    ear_dir: Path,
    publish_yaml: dict,
    *,
    author: str,
    year: int,
) -> bool:
    """Write ear/LICENSE from SPDX template iff one isn't already there."""
    target = ear_dir / "LICENSE"
    if target.exists():
        return True
    spdx = (publish_yaml.get("license") or "").strip()
    if not spdx:
        return False
    template = _SPDX_TO_TEMPLATE.get(spdx)
    if not template:
        return False
    template_path = _LICENSE_TEMPLATE_DIR / template
    if not template_path.is_file():
        return False
    body = template_path.read_text()
    body = body.replace("{year}", str(year)).replace("{author}", author or "Authors")
    target.write_text(body)
    return True


def _read_meta_author(ckpt: Path) -> tuple[str, int]:
    from datetime import datetime as _dt, timezone as _tz

    year = _dt.now(_tz.utc).year
    author = ""
    meta_path = ckpt / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if isinstance(meta, dict):
                author = str(meta.get("author") or meta.get("authors") or "")
        except Exception:
            pass
    return (author, year)


def _resolve_goal(ckpt: Path, tree_data: object) -> str:
    if isinstance(tree_data, dict):
        g = tree_data.get("experiment_goal") or ""
        if g:
            return g
    exp_md = ckpt / "experiment.md"
    if exp_md.is_file():
        try:
            return exp_md.read_text().strip()
        except Exception:
            pass
    meta_path = ckpt / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if isinstance(meta, dict):
                return (
                    meta.get("experiment_goal")
                    or meta.get("goal")
                    or meta.get("research_goal")
                    or meta.get("idea")
                    or ""
                )
        except Exception:
            pass
    return ""


def _read_implementation_overview(ckpt: Path) -> dict | None:
    sd = ckpt / "science_data.json"
    if not sd.is_file():
        return None
    try:
        data = json.loads(sd.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") == "ari.science-data/v1":
        annotation = data.get("interpretation") or {}
        if annotation.get("status") != "ok":
            return None
        overview = annotation.get("implementation_overview")
    else:
        overview = data.get("implementation_overview")
    return overview if isinstance(overview, dict) else None


def _wipe_legacy_subdirs(ear_dir: Path) -> None:
    """Remove legacy v0.6.0 subdirs so re-runs converge on the new layout."""
    for sub in ("logs", "reproducibility"):
        d = ear_dir / sub
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    # RESULTS.md is the v0.6.0 name; EVOLUTION.md and _provenance.json are
    # v0.7.0 names that have since moved to checkpoint root — remove any
    # stale copies left behind under ear/.
    for stale in ("RESULTS.md", "EVOLUTION.md", "_provenance.json"):
        p = ear_dir / stale
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    # data/raw_metrics.json, data/science_data.json, data/figures are removed
    # only if `data/` exists from a previous run; handled below in the build.


@mcp.tool()
def generate_ear(
    checkpoint_dir: str,
    llm_model: str = "",
    llm_base_url: str = "",
) -> dict:
    """Generate the Experiment Artifact Repository for *checkpoint_dir*.

    The layout is *node_report-driven* and shaped like a typical
    paper-companion code repository:

        <checkpoint>/
        ├── EVOLUTION.md       (search trajectory; opaque node_ids omitted)
        ├── _provenance.json   (origin metadata; sha256 lives in manifest.lock)
        └── ear/
            ├── README.md          (deterministic + optional architecture section)
            ├── LICENSE            (SPDX template, optional)
            ├── reproduce.sh       (best report build_command + run_command literal)
            ├── environment.json   (captured runtime environment)
            ├── code/              (verbatim files from contributing chain nodes)
            ├── data/              (uploads/ mirror — input data only)
            └── figures/           (top-level *.{pdf,png,svg,jpg,jpeg})

    `EVOLUTION.md` and `_provenance.json` are ARI audit logs (search
    trajectory + per-file origin) and live at checkpoint root, *outside*
    `ear/`, so they are not bundled into the published artifact.

    Other internal ARI metadata (tree.json, science_data.json,
    raw_metrics.json, eval_scores.json, commands.md) also stays at
    checkpoint root; experiment output files (CSVs etc.) are not bundled —
    `reproduce.sh` regenerates them.

    Behaviour with respect to `node_report.json`:
    - Each contributing node's `node_report.json` is consulted via
      `select_source_files_for_publication` to decide which (node_id,
      rel_path) pairs are publishable code.
    - If reports are missing, code selection is marked unavailable.  Live
      generation never scans a work directory or trace as a substitute; old
      checkpoints must first pass through the offline migration command.
    """
    from ari.public import node_selection as _ns

    ckpt = Path(checkpoint_dir).expanduser().resolve()
    if not ckpt.exists() or not ckpt.is_dir():
        return {"error": f"checkpoint dir not found: {ckpt}"}

    tree_path = ckpt / "tree.json"
    if not tree_path.exists():
        tree_path = ckpt / "nodes_tree.json"
    if not tree_path.exists():
        return {"error": f"no tree.json or nodes_tree.json under {ckpt}"}
    try:
        tree_data = json.loads(tree_path.read_text())
    except Exception as e:
        return {"error": f"could not parse tree json: {e}"}

    nodes: list[dict] = (
        tree_data if isinstance(tree_data, list) else tree_data.get("nodes", [])
    )
    goal = _resolve_goal(ckpt, tree_data)

    workspace, run_id = _resolve_pm_run_id(ckpt)
    reports = _load_node_reports(workspace, run_id, nodes)

    best_node = _resolve_best_node(nodes)
    best_id = (best_node or {}).get("id", "")
    best_report = reports.get(best_id) if best_id else None

    # ── ear/ directory tree (replace transform-owned generated surfaces) ──
    ear = ckpt / "ear"
    from ear import reset_transform_outputs  # type: ignore

    try:
        reset_transform_outputs(ear)
    except Exception as reset_error:
        return {
            "error": f"EAR output reset failed: {type(reset_error).__name__}: {reset_error}",
            "ear_dir": str(ear),
        }
    code_dir = ear / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    _wipe_legacy_subdirs(ear)
    # Wipe any pre-existing `code/<node_id>/` subdir so the new flat layout
    # converges (only if we do have reports — fallback may still want them).
    if code_dir.exists():
        for sub in list(code_dir.iterdir()):
            if sub.is_dir() and sub.name.startswith("node_"):
                shutil.rmtree(sub, ignore_errors=True)
    # Wipe data/ ARI internals from previous runs.
    data_dir = ear / "data"
    if data_dir.exists():
        for legacy in ("raw_metrics.json", "science_data.json"):
            lp = data_dir / legacy
            if lp.is_file():
                try:
                    lp.unlink()
                except OSError:
                    pass
        legacy_figs = data_dir / "figures"
        if legacy_figs.is_dir():
            shutil.rmtree(legacy_figs, ignore_errors=True)

    file_count = 0
    verbatim_files = 0
    code_layout = "node_report_unavailable"

    # ── code/ collection ──
    written_files: list[
        tuple[str, str | None, str]
    ] = []  # (dest_rel, from_node_id, introduced_by)

    if best_id and reports:
        selection = _ns.select_source_files_for_publication(nodes, reports, best_id)

        # Map node_id -> work_dir.
        def _wd(nid: str) -> Path:
            return _node_work_dir(workspace, run_id, nid)

        loaded = _ns.load_selected_sources(
            selection,
            work_dir_for=_wd,
            size_budget=None,
        )
        for rel_path, payload in loaded.items():
            full = code_dir / rel_path
            if not _is_publishable_code_file(rel_path, full):
                continue
            if payload["size"] > _EAR_CODE_FILE_SIZE_CAP:
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload["bytes"])
            # Mark introduction event.
            from_node_id = payload["from_node_id"]
            from_report = reports.get(from_node_id) or {}
            fc = from_report.get("files_changed") or {}
            introduced_by = "modified"
            if any((e.get("path") == rel_path) for e in (fc.get("added") or [])):
                introduced_by = "added"
            elif any((e.get("path") == rel_path) for e in (fc.get("modified") or [])):
                introduced_by = "modified"
            else:
                introduced_by = "inherited_unchanged"
            written_files.append((rel_path, from_node_id, introduced_by))
            verbatim_files += 1
        if written_files:
            code_layout = "node_report"
        excluded_nodes = list(selection.excluded_nodes)
    else:
        excluded_nodes = []

    file_count += verbatim_files

    # ── data/ — uploads/ verbatim mirror (input only) ──
    data_records: list[dict] = []
    uploads_root = ckpt / "uploads"
    upload_files = _gather_uploads(ckpt)
    if upload_files:
        data_dir.mkdir(parents=True, exist_ok=True)
        for src in upload_files:
            rel = src.relative_to(uploads_root)
            dst = data_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
                data_records.append(
                    {
                        "dest": f"data/{rel.as_posix()}",
                        "from_path": f"uploads/{rel.as_posix()}",
                        "size": dst.stat().st_size,
                    }
                )
                file_count += 1
            except Exception:
                continue
    elif data_dir.exists():
        # Empty uploads — remove the now-empty data/.
        try:
            for child in list(data_dir.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            data_dir.rmdir()
        except OSError:
            pass

    has_data_dir = data_dir.is_dir()

    # ── figures/ — top-level mirror ──
    figures_dir = ear / "figures"
    fig_records: list[dict] = []
    fig_files = _gather_top_level_figures(ckpt)
    if fig_files:
        figures_dir.mkdir(parents=True, exist_ok=True)
        for src in fig_files:
            dst = figures_dir / src.name
            try:
                shutil.copy2(src, dst)
                fig_records.append(
                    {
                        "dest": f"figures/{src.name}",
                        "from_path": src.name,
                        "size": dst.stat().st_size,
                    }
                )
                file_count += 1
            except Exception:
                continue
    elif figures_dir.exists():
        # Old run left an empty dir behind.
        try:
            figures_dir.rmdir()
        except OSError:
            pass

    has_figures_dir = figures_dir.is_dir()

    # ── EVOLUTION.md ──
    chain = _ns.build_parent_chain(best_id, nodes) if best_id else []
    narrative_chain = _ns.filter_nodes(
        chain,
        reports,
        "for_narrative",
        always_include_node_ids={best_id} if best_id else (),
    )
    has_evolution = False
    if narrative_chain:
        evo = _render_evolution_md(narrative_chain, reports)
        # EVOLUTION.md is an ARI audit log, not part of the published EAR;
        # it lives at checkpoint root alongside tree.json / science_data.json.
        (ckpt / "EVOLUTION.md").write_text(evo)
        has_evolution = True

    # ── reproduce.sh ──
    repro_body = _render_reproduce_sh(best_report, code_dir=code_dir)
    has_reproduce_sh = False
    if repro_body:
        repro_path = ear / "reproduce.sh"
        repro_path.write_text(repro_body)
        try:
            repro_path.chmod(0o755)
        except OSError:
            pass
        file_count += 1
        has_reproduce_sh = True

    # ── environment.json (top-level) ──
    env_info = _capture_environment()
    (ear / "environment.json").write_text(
        json.dumps(env_info, ensure_ascii=False, indent=2)
    )
    file_count += 1
    has_environment = True

    # ── LICENSE (optional, SPDX template-driven) ──
    publish_yaml = _read_publish_yaml(ckpt)
    author, year = _read_meta_author(ckpt)
    has_license = _write_license_if_needed(
        ear,
        publish_yaml,
        author=author,
        year=year,
    )
    if has_license and (ear / "LICENSE").is_file():
        file_count += 1

    # ── README.md (deterministic + optional impl_overview) ──
    impl_overview = _read_implementation_overview(ckpt)
    readme_text = _render_readme(
        goal=goal,
        best_node=best_node,
        best_report=best_report,
        impl_overview=impl_overview,
        has_data_dir=has_data_dir,
        has_figures_dir=has_figures_dir,
        has_evolution=has_evolution,
        has_environment=has_environment,
        has_license=has_license,
        has_reproduce_sh=has_reproduce_sh,
    )
    (ear / "README.md").write_text(readme_text)
    file_count += 1

    # ── immutable locks/contracts/admission/cassette hand-off ──
    from ear import materialize_ear_evidence  # type: ignore

    try:
        evidence_result = materialize_ear_evidence(ckpt, ear)
    except Exception as evidence_error:
        return {
            "error": f"EAR evidence materialization failed: {type(evidence_error).__name__}: {evidence_error}",
            "ear_dir": str(ear),
        }
    file_count += 1 + int(evidence_result["copied"])

    # ── _provenance.json (checkpoint-root audit log; not part of EAR) ──
    # `dest` paths are checkpoint-relative so a reader of this file can
    # locate every artifact without knowing it was generated from inside
    # `ear/`. Files that live under `ear/` are recorded as `ear/...`.
    file_records: list[dict] = []
    for rel_path, from_nid, introduced_by in written_files:
        node = next((n for n in nodes if n.get("id") == from_nid), None)
        depth = int((node or {}).get("depth") or 0)
        size = (
            (code_dir / rel_path).stat().st_size
            if (code_dir / rel_path).is_file()
            else 0
        )
        file_records.append(
            {
                "dest": f"ear/code/{rel_path}",
                "from_node_id": from_nid,
                "from_filename": Path(rel_path).name,
                "verbatim": True,
                "introduced_by": introduced_by,
                "depth_in_chain": depth,
                "size": size,
            }
        )
    data_records_prov = [{**rec, "dest": f"ear/{rec['dest']}"} for rec in data_records]
    fig_records_prov = [{**rec, "dest": f"ear/{rec['dest']}"} for rec in fig_records]
    provenance = {
        "schema_version": 1,
        "best_node_id": best_id,
        "method": code_layout,
        "files": file_records,
        "data": data_records_prov,
        "figures": fig_records_prov,
        "rendered": [
            {
                "dest": "ear/README.md",
                "method": "deterministic_render",
                "source_field": "node_reports + (optional) science_data.json::implementation_overview",
            },
            {
                "dest": "EVOLUTION.md",
                "method": "deterministic_render",
                "source_field": "node_reports::delta_vs_parent + metrics",
            }
            if has_evolution
            else None,
            {
                "dest": "ear/reproduce.sh",
                "method": "deterministic_render",
                "source_field": "node_reports::{build_command, run_command}",
            }
            if has_reproduce_sh
            else None,
        ],
        "excluded_nodes": list(excluded_nodes),
        "warnings": [],
    }
    provenance["rendered"] = [r for r in provenance["rendered"] if r is not None]
    (ckpt / "_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2)
    )

    # ── checkpoint/run_config.json (moved from ear/reproducibility/) ──
    real_nodes = [n for n in nodes if n.get("has_real_data") and n.get("metrics")]
    run_config: dict = {
        "checkpoint_dir": str(ckpt),
        "experiment_goal": (goal or "")[:2000],
        "node_count": len(nodes),
        "real_data_count": len(real_nodes),
    }
    if best_node:
        run_config["top_node_id"] = best_node.get("id", "")
        run_config["top_node_label"] = best_node.get("label", "")
        run_config["top_node_metrics"] = best_node.get("metrics") or {}
    try:
        (ckpt / "run_config.json").write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2)
        )
    except Exception:
        pass

    return {
        "ear_dir": str(ear),
        "code_layout": code_layout,
        "verbatim_files": verbatim_files,
        # Back-compat alias.
        "source_files": verbatim_files,
        "rendered_files": (1 if has_evolution else 0)
        + (1 if has_reproduce_sh else 0)
        + 1,  # README.md is always rendered
        "data_count": len(data_records),
        "figure_count": len(fig_records),
        "top_node_id": best_id,
        "best_chain_depth": len(chain),
        "excluded_count": len(excluded_nodes),
        "warnings_count": 0,
        "file_count": file_count,
        "node_count": len(nodes),
        "has_readme": (ear / "README.md").exists(),
        # Back-compat: callers and existing tests expect has_results.
        "has_results": (ear / "README.md").exists(),
        "has_evolution": has_evolution,
        "has_reproduce_sh": has_reproduce_sh,
        "has_license": has_license,
        "has_environment": has_environment,
        "evidence_index_digest": evidence_result["index"]["index_digest"],
        "evidence_record_count": evidence_result["record_count"],
    }


@mcp.tool()
def curate_ear(checkpoint_dir: str) -> dict:
    """Curate {checkpoint}/ear/ into {checkpoint}/ear_published/ + manifest.lock.

    Reads {checkpoint}/ear/publish.yaml. If publish.yaml is absent, returns
    {"skipped": true} and does not touch ear_published/. The bundle digest
    (sha256 of the canonical manifest) is the value that gets baked into
    the paper's Code Availability section.
    """
    from curate import curate_to_dict  # type: ignore  # local module

    return curate_to_dict(checkpoint_dir)


@mcp.tool()
def publish_ear(
    checkpoint_dir: str,
    backend: str = "ari-registry",
    visibility: str = "staged",
    dry_run: bool = False,
) -> dict:
    """Publish {checkpoint}/ear_published/ to a backend.

    Thin MCP wrapper around ari.publish.publish so the publish step can
    be a workflow stage. Always starts at visibility=staged (FR-P5).
    """
    from publish_adapter import publish_ear_record

    return publish_ear_record(
        checkpoint_dir,
        backend=backend,
        visibility=visibility,
        dry_run=dry_run,
    )


@mcp.tool()
def promote_ear(checkpoint_dir: str, target: str = "public") -> dict:
    """Promote a previously-published artefact to a wider visibility."""
    from publish_adapter import promote_ear_record

    return promote_ear_record(checkpoint_dir, target=target)


if __name__ == "__main__":
    mcp.run()
