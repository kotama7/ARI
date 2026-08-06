"""Deterministic synthetic run-checkpoint factory for the GUI refresh
program (Wave 0 / G0 — reference small/medium/large run fixtures).

``make_run_checkpoint(dest, nodes=N, seed=S)`` writes a schema-faithful
checkpoint directory that :func:`ari.checkpoint.load_nodes_tree` (and the
viz/GUI readers built on it) can consume, without ever running a real BFTS
loop:

- ``tree.json``        — rich CLI layout (``ari/cli/bfts_loop.py:_save_checkpoint``):
  ``{run_id, experiment_file, experiment_file_sha256, experiment_file_len,
  created_at, nodes:[Node.to_dict(), ...]}``.
- ``nodes_tree.json``  — lightweight pipeline export
  ``{experiment_goal, nodes}`` (same node list object).
- ``results.json``     — ``{run_id, nodes: {id: {artifacts, metrics,
  has_real_data, eval_summary, status, error_log}}}``.
- ``experiment.md``    — fixed goal text (source of ``experiment_goal`` and
  of the sha256/len recorded in ``tree.json``).
- ``idea.json``        — minimal lineage catalog ``{"ideas": [...]}``.
- ``meta.json``        — minimal run metadata (``run_id`` is what
  ``ari/lineage.py`` reads).
- ``cost_trace.jsonl`` — a few ``CallRecord``-shaped lines
  (``ari/cost_tracker.py`` writer field set, ``epoch`` omitted).

Determinism (design principle P2): every value is either a fixed literal or
derived from ``(seed, node_index, field)`` via :mod:`hashlib` — never the
``random`` module, never ``datetime.now()``. Node timestamps are computed by
fixed arithmetic on the literal base ``2026-07-23T00:00:00Z``. Two calls
with the same ``(nodes, seed)`` produce byte-identical files.

Corrupt modes (robustness-gate inputs), applied *after* a normal write:

- ``"truncated_jsonl"`` — ``cost_trace.jsonl`` ends mid-line (torn append).
- ``"invalid_json"``    — ``tree.json`` is syntactically broken (torn write).
- ``"partial_write"``   — ``nodes_tree.json`` valid but ``tree.json`` missing
  (crash between the two writes of the checkpoint flush).

The topology is BFTS-ish: a rooted 3-ary tree (``parent(i) = (i-1)//3``)
with parent links, ``children`` lists, and root→parent ``ancestor_ids``
exactly as ``ari/orchestrator/node.py`` maintains them.

Optional result layers (gui_refresh task 07 Wave 4d — inputs for the
``/api/v1/runs/{run_id}/results`` and ``/ear`` read models; all default OFF
so existing fixtures stay byte-identical):

- ``paper=True``   — ``full_paper.tex`` + ``full_paper.pdf`` (fixed bytes).
- ``review=True``  — ``review_report.json`` (overall/abstract/body scores,
  decision, confidence, rubric ``score_dimensions``; seed-derived).
- ``ors=True``     — the ORS chain files ``ors_rubric.meta.json`` /
  ``ors_replicator.json`` / ``ors_phase1.json`` / ``ors_grade.json``
  (grade shaped for ``ari.viz.ear._synth_repro_report_from_ors``).
- ``ear=...``      — ``None`` (off) or one of :data:`EAR_STAGES`:
  ``"bare"`` (``ear/`` + publish.yaml + README), ``"curated"`` (+
  ``ear_published/manifest.lock``), ``"published"`` (+
  ``publish_record.json``, staged), ``"promoted"`` (+ ``promoted_at``,
  public visibility).

Charter reference:
``docs/plans/gui_refresh/00_program_charter_and_baseline.md`` §Deliverables
("reference small/medium/large run fixture"). Fixture data is generated on
demand into a caller-supplied directory (``tmp_path`` in tests) and is
NEVER committed to the repository.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ari.checkpoint import (
    save_nodes_tree_json,
    save_results_json,
    save_tree_json,
)

# Fixed literal timestamps only — never datetime.now() (P2).
FIXED_CREATED_AT = "2026-07-23T00:00:00Z"
_BASE_DT = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)

CORRUPT_MODES = ("truncated_jsonl", "invalid_json", "partial_write")

# Wave 4d result layers: cumulative EAR lineage stages (curate -> publish ->
# promote; "bare" is an ear/ directory that was never curated).
EAR_STAGES = ("bare", "curated", "published", "promoted")

_STATUSES = (
    # Weighted, deterministic pick-list: mostly terminal successes with a
    # sprinkling of every other NodeStatus so all GUI status-render paths
    # get exercised.
    "success", "success", "success", "success", "success", "success",
    "failed", "failed", "running", "pending", "abandoned",
)
_LABELS = ("improve", "debug", "ablation", "validation", "draft", "other")
_MODELS = ("claude-sonnet-4-5", "claude-haiku-4-5")


def _hval(seed: int, *parts: object) -> int:
    """Deterministic 64-bit value from (seed, *parts) via sha256 — no random."""
    key = ":".join(str(p) for p in ("gui_refresh_fixture", seed, *parts))
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def _hfloat(seed: int, *parts: object) -> float:
    """Deterministic float in [0, 1) with a short stable repr."""
    return (_hval(seed, *parts) % 10_000) / 10_000.0


def _ts(offset_s: int) -> str:
    """Fixed-base timestamp: 2026-07-23T00:00:00Z + offset (pure arithmetic)."""
    return (_BASE_DT + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_nodes(n_nodes: int, seed: int, run_id: str) -> list[dict]:
    """Build ``Node.to_dict()``-shaped dicts forming a rooted 3-ary tree."""
    nodes: list[dict] = []
    for i in range(n_nodes):
        nid = f"node_{i:05d}"
        if i == 0:
            parent_idx: int | None = None
            depth = 0
            ancestor_ids: list[str] = []
        else:
            parent_idx = (i - 1) // 3
            parent = nodes[parent_idx]
            depth = parent["depth"] + 1
            ancestor_ids = parent["ancestor_ids"] + [parent["id"]]

        status = _STATUSES[_hval(seed, i, "status") % len(_STATUSES)]
        if i == 0:
            label, raw_label = "draft", ""
        else:
            label = _LABELS[_hval(seed, i, "label") % len(_LABELS)]
            raw_label = "replication" if label == "other" else ""

        created_at = _ts(i * 60)
        terminal = status in ("success", "failed", "abandoned")
        completed_at = _ts(i * 60 + 45) if terminal else ""

        if status == "success":
            sci = round(_hfloat(seed, i, "sci"), 4)
            metrics = {
                "GFlops": round(50.0 + 250.0 * _hfloat(seed, i, "gflops"), 2),
                "_scientific_score": sci,
            }
            has_real_data = True
            eval_summary = (
                f"Deterministic fixture evaluation for {nid}: "
                f"scientific score {sci}."
            )
            artifacts = [
                {
                    "path": f"experiments/{run_id}/{nid}/results.csv",
                    "description": "primary metrics table (synthetic)",
                }
            ]
            error_log = None
        elif status == "failed":
            metrics = {}
            has_real_data = False
            eval_summary = None
            artifacts = []
            error_log = f"synthetic failure injected for {nid} (fixture)"
        else:  # running / pending / abandoned
            metrics = {}
            has_real_data = False
            eval_summary = None
            artifacts = []
            error_log = None

        nodes.append(
            {
                "id": nid,
                "parent_id": None if parent_idx is None else nodes[parent_idx]["id"],
                "depth": depth,
                "status": status,
                "retry_count": _hval(seed, i, "retry") % 3,
                "children": [],  # filled below
                "created_at": created_at,
                "completed_at": completed_at,
                "artifacts": artifacts,
                "metrics": metrics,
                "has_real_data": has_real_data,
                # Per-case evaluation detail carried by Node.to_dict(); the
                # fixture keeps them empty (deterministic, no clock/scores).
                "evaluation_cases": {},
                "evaluation_status": "",
                "eval_summary": eval_summary,
                "label": label,
                "raw_label": raw_label,
                "name": f"fixture step {i}",
                "error_log": error_log,
                "ancestor_ids": ancestor_ids,
                "trace_log": [f"tool_call {k}: run_experiment({nid})" for k in range(2)],
                "original_direction": (
                    None if i == 0 else f"Explore direction {i} proposed by parent."
                ),
                "producer_component_id": "",
                "producer_prompt_hash": "",
                "producer_epoch_id": "",
                "node_report_path": None,
            }
        )
        if parent_idx is not None:
            nodes[parent_idx]["children"].append(nid)
    return nodes


def _cost_trace_lines(seed: int, nodes: list[dict], n_records: int = 5) -> list[str]:
    """CallRecord-shaped JSONL lines matching ari/cost_tracker.py's writer
    (full asdict field set, ``epoch`` popped when None, plain json.dumps)."""
    lines: list[str] = []
    for k in range(min(n_records, len(nodes))):
        prompt_toks = 500 + _hval(seed, k, "pt") % 1500
        completion_toks = 100 + _hval(seed, k, "ct") % 900
        rec = {
            "timestamp": _ts(k * 30),
            "node_id": nodes[k]["id"],
            "phase": "bfts",
            "skill": "experiment-runner",
            "model": _MODELS[_hval(seed, k, "model") % len(_MODELS)],
            "prompt_tokens": prompt_toks,
            "completion_tokens": completion_toks,
            "total_tokens": prompt_toks + completion_toks,
            "estimated_cost_usd": round(_hfloat(seed, k, "cost") / 100, 6),
            "component": None,
            "op": None,
            "backend": None,
            "embedding_tokens": 0,
            "latency_ms": None,
        }
        lines.append(json.dumps(rec))
    return lines


# ── Wave 4d optional result layers (deterministic, default OFF) ────────────


def _write_json(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_paper_layer(dest: Path) -> None:
    """full_paper.tex + full_paper.pdf at the checkpoint root (fixed bytes)."""
    (dest / "full_paper.tex").write_text(
        "\\documentclass{article}\\begin{document}Fixture paper."
        "\\end{document}\n",
        encoding="utf-8",
    )
    (dest / "full_paper.pdf").write_bytes(b"%PDF-1.4\n%gui_refresh fixture\n")


def _write_review_layer(dest: Path, seed: int) -> None:
    """review_report.json with seed-derived bounded scalars (rubric shape)."""
    overall = round(4.0 + 5.0 * _hfloat(seed, "review", "overall"), 2)
    _write_json(
        dest / "review_report.json",
        {
            "overall_score": overall,
            "abstract_score": round(3.0 + 6.0 * _hfloat(seed, "review", "abs"), 2),
            "body_score": round(3.0 + 6.0 * _hfloat(seed, "review", "body"), 2),
            "decision": "accept" if overall >= 6.0 else "borderline",
            "confidence": round(2.0 + 2.0 * _hfloat(seed, "review", "conf"), 2),
            "rubric_id": "neurips",
            "rubric_version": "v1",
            "score_dimensions": [
                {
                    "name": name,
                    "value": round(1.0 + 9.0 * _hfloat(seed, "review", name), 2),
                    "scale": [0, 10],
                }
                for name in ("soundness", "novelty")
            ],
            "strengths": "Deterministic fixture strengths.",
        },
    )


def _write_ors_layer(dest: Path, seed: int) -> None:
    """ORS chain files shaped for ``_synth_repro_report_from_ors``."""
    _write_json(
        dest / "ors_rubric.meta.json",
        {"model": "claude-sonnet-4-5", "leaves": 4, "expected_artifacts": 2},
    )
    _write_json(
        dest / "ors_replicator.json",
        {"populated": True, "model": "claude-sonnet-4-5",
         "files": ["reproduce.sh"]},
    )
    _write_json(
        dest / "ors_phase1.json",
        {"executed": True, "exit_code": 0, "missing": []},
    )
    ors_score = round(0.5 + 0.5 * _hfloat(seed, "ors", "score"), 4)
    _write_json(
        dest / "ors_grade.json",
        {
            "ors_score": ors_score,
            "raw_score": round(ors_score * 0.9, 4),
            "leaf_grades": [
                {"leaf_id": f"leaf_{k}", "passed_runs": 1 if k < 3 else 0}
                for k in range(4)
            ],
            "judge_model": "claude-haiku-4-5",
            "n_runs": 1,
            "elapsed_sec": 42,
        },
    )


def _write_ear_layer(dest: Path, seed: int, stage: str) -> None:
    """Cumulative EAR lineage: bare -> curated -> published -> promoted."""
    ear_dir = dest / "ear"
    ear_dir.mkdir(parents=True, exist_ok=True)
    (ear_dir / "README.md").write_text(
        "# Fixture EAR\n\nDeterministic gui_refresh EAR layer.\n",
        encoding="utf-8",
    )
    (ear_dir / "reproduce.sh").write_text(
        "#!/bin/sh\necho fixture\n", encoding="utf-8"
    )
    (ear_dir / "publish.yaml").write_text(
        "include:\n  - '**/*.sh'\nexclude: []\nvisibility: staged\n",
        encoding="utf-8",
    )
    if stage == "bare":
        return

    bundle_sha = hashlib.sha256(
        f"gui_refresh_fixture_bundle:{seed}".encode("utf-8")
    ).hexdigest()
    pub_dir = dest / "ear_published"
    pub_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        pub_dir / "manifest.lock",
        {
            "bundle_sha256": bundle_sha,
            "files": [
                {"path": "README.md", "sha256": bundle_sha[:16]},
                {"path": "reproduce.sh", "sha256": bundle_sha[16:32]},
            ],
            "excluded_count": 1,
            "publish": {"visibility": "staged", "license": "MIT"},
            "created_at": FIXED_CREATED_AT,
        },
    )
    if stage == "curated":
        return

    record = {
        "backend": "local_tarball",
        "ref": f"ear://fixture/{bundle_sha[:12]}",
        "bundle_sha256": bundle_sha,
        "visibility": "staged",
        "dry_run": False,
        "timestamp": FIXED_CREATED_AT,
    }
    if stage == "promoted":
        record["visibility"] = "public"
        record["promoted_at"] = _ts(3600)
    _write_json(dest / "publish_record.json", record)


def make_run_checkpoint(
    dest: Path,
    *,
    nodes: int,
    seed: int = 0,
    corrupt: str | None = None,
    paper: bool = False,
    review: bool = False,
    ors: bool = False,
    ear: str | None = None,
) -> dict:
    """Write a deterministic synthetic checkpoint into *dest*.

    Parameters
    ----------
    dest    : directory to populate (created if missing) — use ``tmp_path``.
    nodes   : node count (10 = small, 1000 = medium, 10000 = large).
    seed    : determinism seed; same (nodes, seed) → byte-identical files.
    corrupt : None, or one of :data:`CORRUPT_MODES`.
    paper   : write ``full_paper.tex`` + ``full_paper.pdf`` (Wave 4d).
    review  : write a deterministic ``review_report.json`` (Wave 4d).
    ors     : write the deterministic ORS chain files (Wave 4d).
    ear     : None, or one of :data:`EAR_STAGES` (Wave 4d lineage stage).

    Returns a manifest dict ``{run_id, nodes, seed, corrupt, files}`` so
    callers can assert counts without re-parsing the large JSON.
    """
    if nodes < 1:
        raise ValueError("nodes must be >= 1")
    if corrupt is not None and corrupt not in CORRUPT_MODES:
        raise ValueError(f"unknown corrupt mode: {corrupt!r} (choose from {CORRUPT_MODES})")
    if ear is not None and ear not in EAR_STAGES:
        raise ValueError(f"unknown ear stage: {ear!r} (choose from {EAR_STAGES})")

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    run_id = f"fixture_{nodes}n"

    # experiment.md — fixed goal text; sha256/len recorded in tree.json the
    # same way _save_checkpoint's _hash_experiment_file does (sha256[:16]).
    exp_text = (
        f"# Synthetic GUI-refresh fixture run ({run_id})\n\n"
        "Goal: deterministic reference checkpoint for the gui_refresh G0 "
        "performance and robustness gates. No real experiment was run.\n"
    )
    exp_bytes = exp_text.encode("utf-8")
    (dest / "experiment.md").write_bytes(exp_bytes)

    node_dicts = _build_nodes(nodes, seed, run_id)

    tree = {
        "run_id": run_id,
        "experiment_file": "experiment.md",
        "experiment_file_sha256": hashlib.sha256(exp_bytes).hexdigest()[:16],
        "experiment_file_len": len(exp_bytes),
        "created_at": FIXED_CREATED_AT,
        "nodes": node_dicts,
    }
    save_tree_json(dest, tree)

    nodes_tree = {"experiment_goal": exp_text[:3000], "nodes": node_dicts}
    save_nodes_tree_json(dest, nodes_tree)

    results = {
        "run_id": run_id,
        "nodes": {
            n["id"]: {
                "artifacts": n["artifacts"],
                "metrics": n["metrics"],
                "has_real_data": n["has_real_data"],
                "eval_summary": n["eval_summary"],
                "status": n["status"],
                "error_log": n["error_log"],
            }
            for n in node_dicts
        },
    }
    save_results_json(dest, results)

    idea = {
        "ideas": [
            {
                "idea_id": "idea_0",
                "title": "Synthetic reference idea",
                "description": (
                    "Placeholder idea catalog entry for the gui_refresh "
                    "reference fixture — deterministic, non-scientific."
                ),
            }
        ]
    }
    (dest / "idea.json").write_text(
        json.dumps(idea, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    meta = {
        "run_id": run_id,
        "created_at": FIXED_CREATED_AT,
        "experiment_file": "experiment.md",
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    trace_lines = _cost_trace_lines(seed, node_dicts)
    (dest / "cost_trace.jsonl").write_text(
        "\n".join(trace_lines) + "\n", encoding="utf-8"
    )

    # ── Wave 4d optional result layers (all default OFF) ───────────────
    if paper:
        _write_paper_layer(dest)
    if review:
        _write_review_layer(dest, seed)
    if ors:
        _write_ors_layer(dest, seed)
    if ear is not None:
        _write_ear_layer(dest, seed, ear)

    # ── corruption pass (applied after a fully valid write) ────────────
    if corrupt == "truncated_jsonl":
        # Torn append: the final record stops mid-line (no trailing newline,
        # syntactically invalid JSON on the last line).
        full = (dest / "cost_trace.jsonl").read_text(encoding="utf-8")
        keep = "\n".join(trace_lines[:-1])
        torn = trace_lines[-1][: max(5, len(trace_lines[-1]) // 2)]
        (dest / "cost_trace.jsonl").write_text(
            (keep + "\n" if keep else "") + torn, encoding="utf-8"
        )
        assert (dest / "cost_trace.jsonl").read_text(encoding="utf-8") != full
    elif corrupt == "invalid_json":
        # Torn write: chop the tail off tree.json so json.loads raises.
        raw = (dest / "tree.json").read_bytes()
        (dest / "tree.json").write_bytes(raw[: len(raw) - 40])
    elif corrupt == "partial_write":
        # Crash between the nodes_tree.json and tree.json writes.
        (dest / "tree.json").unlink()

    files = sorted(p.name for p in dest.iterdir() if p.is_file())
    return {
        "run_id": run_id,
        "nodes": nodes,
        "seed": seed,
        "corrupt": corrupt,
        "files": files,
    }
