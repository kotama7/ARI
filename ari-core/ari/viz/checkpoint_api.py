"""REST API: model list, checkpoint list/summary, lineage decisions.

Phase 3B PR-3B-2 (viz/REFACTORING.md §2 Step 2): extracted from
``ari/viz/api_state.py``.  ``api_state.py`` keeps a re-export facade
so downstream callers (and the route table inside ``server.py``) see
the same names regardless of where each function landed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


log = logging.getLogger(__name__)

# Phase 3B PR-3B-2: bare-name wrappers that defer to ``api_state``
# at call time so ``monkeypatch.setattr(api_state, name, ...)``
# in tests intercepts the helper this module's functions call.
def _check_pid_alive(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._check_pid_alive(*args, **kwargs)

def _checkpoint_search_bases(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._checkpoint_search_bases(*args, **kwargs)

def _resolve_checkpoint_dir(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._resolve_checkpoint_dir(*args, **kwargs)

def _synth_repro_report_from_ors(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._synth_repro_report_from_ors(*args, **kwargs)


def _load_nodes_tree(checkpoint_dir):
    """Resolve a checkpoint's node tree via the canonical loader.

    Lazily imports ``ari.checkpoint.load_nodes_tree`` (the single resolver that
    also honors the legacy ``node_*/tree.json`` layout, used by the live
    WebSocket path) so the checkpoint list/summary cards agree with it.
    """
    from ari.checkpoint import load_nodes_tree as _load
    return _load(checkpoint_dir)




# ──────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────


def _api_models() -> dict:
    """Return available LLM providers and their model suggestions."""
    return {
        "providers": [
            {"id": "openai",    "name": "OpenAI",     "models": ["gpt-5.4", "gpt-5.2", "gpt-4o", "gpt-4o-mini", "o4-mini", "o3", "o3-mini"]},
            {"id": "anthropic", "name": "Anthropic (Claude)", "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]},
            {"id": "gemini",    "name": "Google Gemini", "models": ["gemini/gemini-2.5-pro", "gemini/gemini-2.0-flash", "gemini/gemini-1.5-pro"]},
            {"id": "ollama",    "name": "Ollama (Local)", "models": ["ollama_chat/llama3.3", "ollama_chat/qwen3:8b", "ollama_chat/gemma3:9b", "ollama_chat/mistral"]},
            {"id": "cli-shim",  "name": "CLI Shim (claude/codex)", "models": ["claude-cli", "claude-cli-agent", "codex-cli", "codex-cli-agent"]},
        ]
    }




def _api_checkpoints() -> list:
    """List checkpoint directories."""
    ckpt_dirs = []
    search_paths = _checkpoint_search_bases()
    seen = set()
    _seen_resolved: set[str] = set()  # track resolved paths for stale-proc cleanup
    for base in search_paths:
        if not base.exists():
            continue
        _SKIP = {"experiments", "__pycache__", ".git"}
        _TS_PAT = re.compile(r'^[0-9]{8,14}_')
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if not d.is_dir() or d in seen or d.name in _SKIP:
                continue
            # Only treat directories matching YYYYMMDDHHMMSS_* as valid checkpoints
            if not _TS_PAT.match(d.name):
                continue
            seen.add(d)
            info = {"id": d.name, "path": str(d), "status": "unknown",
                    "node_count": 0, "review_score": None, "best_metric": None, "mtime": 0}
            try:
                info["mtime"] = int(d.stat().st_mtime)
                _resolved = str(Path(d).resolve())
                _seen_resolved.add(_resolved)
                # Check if this is the active checkpoint with a tracked process
                _is_active = bool(
                    _st._checkpoint_dir
                    and _resolved == str(Path(_st._checkpoint_dir).resolve())
                )
                # Check in-memory process tracking (supports multiple experiments)
                _tracked_proc = _st._running_procs.get(_resolved)
                if _tracked_proc and _tracked_proc.poll() is not None:
                    # Process finished — remove from tracking
                    del _st._running_procs[_resolved]
                    _tracked_proc = None
                _proc_alive = bool(
                    (_is_active and _st._last_proc and _st._last_proc.poll() is None)
                    or _tracked_proc
                )
                # Phase 1: Determine status from process tracking / PID file
                if _proc_alive:
                    info["status"] = "running"
                else:
                    # Both active and non-active: fall back to .ari_pid on disk.
                    # Active checkpoint also needs this so status survives GUI
                    # restarts (in-memory _last_proc is lost but the run keeps
                    # going and writes its PID file).
                    _pid_status = _check_pid_alive(d)
                    if _pid_status == "running":
                        info["status"] = "running"
                    elif _is_active:
                        info["status"] = "stopped"
                    # else: leave "unknown" for tree.json to refine
                # Phase 2: Refine status from tree.json node data.
                # The flat tree.json/nodes_tree.json probe is kept verbatim (incl.
                # the st_size>0 guard and errors="replace") so its corrupt-file
                # corner cases stay byte-identical; we ADD the canonical
                # ari.checkpoint.load_nodes_tree fallback only when NEITHER flat
                # file is present, so the legacy `node_*/tree.json` layout is now
                # honored here too — it used to render node_count=0 in this list
                # (req 07, divergence #1). Symmetric with _api_checkpoint_summary.
                nt = d / "nodes_tree.json"
                tf = d / "tree.json"
                if tf.exists() and tf.stat().st_size > 0:
                    nt = tf
                tree = None
                if nt.exists() and nt.stat().st_size > 0:
                    try:
                        tree = json.loads(nt.read_text(encoding="utf-8", errors="replace"))
                    except Exception:
                        log.debug("checkpoint node parsing error: %s", d.name, exc_info=True)
                        tree = None
                elif not tf.exists() and not (d / "nodes_tree.json").exists():
                    # No flat tree files — fall back to the legacy node_*/tree.json
                    # layout via the canonical loader (matches the live path).
                    tree = _load_nodes_tree(d)
                if isinstance(tree, dict):
                    nodes = tree.get("nodes", [])
                    info["node_count"] = len(nodes)
                    statuses = {n.get("status") for n in nodes}
                    # Only refine status when process-based checks left it "unknown"
                    if nodes and info["status"] not in ("running", "stopped"):
                        if "running" in statuses:
                            # Tree says running but no live process → orphaned
                            info["status"] = "stopped"
                        else:
                            info["status"] = "completed"
                    # Fallback score from scientific_score if no review
                    if nodes:
                        sci_scores = [
                            n.get("metrics", {}).get("_scientific_score")
                            for n in nodes
                            if n.get("metrics", {}).get("_scientific_score") is not None
                        ]
                        if sci_scores:
                            info["best_scientific_score"] = round(max(sci_scores), 2)
                rr = d / "review_report.json"
                if rr.exists() and rr.stat().st_size > 0:
                    try:
                        r = json.loads(rr.read_text(encoding="utf-8", errors="replace"))
                        info["review_score"] = r.get("overall_score") or r.get("score")
                        info["status"] = "completed"
                    except Exception:
                        log.debug("review_report.json parse error: %s", d.name, exc_info=True)
                        pass
            except Exception:
                log.warning("checkpoint listing error: %s", d.name, exc_info=True)
                pass
            ckpt_dirs.append(info)
    # Prune _running_procs entries whose checkpoint dirs no longer exist on disk
    for _stale_key in list(_st._running_procs.keys()):
        if _stale_key not in _seen_resolved:
            _st._running_procs.pop(_stale_key, None)
    return ckpt_dirs



def _api_checkpoint_summary(ckpt_id: str) -> dict:
    """Return summary for a specific checkpoint."""
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "not found"}

    result = {"id": ckpt_id, "path": str(d)}
    # Also check repro/ subdir for reproducibility_report.json
    repro_json = d / "reproducibility_report.json"
    if not repro_json.exists():
        repro_json = d / "repro" / "reproducibility_report.json"
    if repro_json.exists() and repro_json.stat().st_size > 0:
        try:
            result["reproducibility_report"] = json.loads(repro_json.read_text())
        except Exception:
            log.debug("reproducibility_report parse error", exc_info=True)
            pass

    # Fallback: synthesize a reproducibility_report from the PaperBench-format
    # ORS files (ors_grade.json + ors_phase1.json + ors_replicator.json) when
    # the legacy report is absent. This lets the existing GUI renderer show
    # something useful for runs that produced ors_*.json (post-§4.1 rewrite).
    if "reproducibility_report" not in result:
        synth = _synth_repro_report_from_ors(d)
        if synth is not None:
            result["reproducibility_report"] = synth

    # Surface raw ORS-chain payloads alongside the synthesized verdict so the
    # rich PaperBench-aware GUI section can render per-stage status cards
    # (Rubric → Replicator → Seed → Phase 1 → Phase 2) plus the per-leaf
    # judge report. The keys are namespaced with ``ors_`` so they don't
    # collide with legacy summary fields.
    for fname, key in (
        ("ors_rubric.json",       "ors_rubric"),         # full TaskNode tree
        ("ors_rubric.meta.json",  "ors_rubric_meta"),    # generator metadata
        ("ors_replicator.json",   "ors_replicator"),     # LLM replicator output
        ("ors_seed.json",         "ors_seed"),           # fetch_code_bundle result
        ("ors_phase1.json",       "ors_phase1"),         # run_reproduce result
        ("ors_grade.json",        "ors_grade"),          # SimpleJudge result
    ):
        p = d / fname
        if p.exists() and p.stat().st_size > 0:
            try:
                result[key] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                # Surface MCP error envelopes (e.g. {"result": "Error: ..."})
                # as-is so the renderer can flag them.
                try:
                    result[key] = {"_parse_error": True, "_raw": p.read_text()[:500]}
                except Exception:
                    pass

    # Load tree data (prefer tree.json, fallback to nodes_tree.json). The flat
    # files are read directly so a parse failure still surfaces a {_parse_error}
    # envelope to the renderer. When NEITHER flat file is present, fall back to
    # the canonical loader so the legacy `node_*/tree.json` layout is honored
    # here too (req 07, divergence #1) — matching the live WebSocket path.
    _tree_loaded = False
    for _tree_fname in ("tree.json", "nodes_tree.json"):
        _tp = d / _tree_fname
        if _tp.exists() and _tp.stat().st_size > 0:
            try:
                result["nodes_tree"] = json.loads(_tp.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                result["nodes_tree"] = {"_parse_error": str(e)}
            _tree_loaded = True
            break
    if not _tree_loaded:
        _legacy_tree = _load_nodes_tree(d)
        if _legacy_tree is not None:
            result["nodes_tree"] = _legacy_tree

    for fname in ("review_report.json", "science_data.json",
                  "figures_manifest.json", "vlm_review.json"):
        p = d / fname
        if p.exists() and p.stat().st_size > 0:
            try:
                result[fname.replace(".json", "")] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                result[fname.replace(".json", "")] = {"_parse_error": str(e)}

    # review_report.json already contains ensemble_reviews + meta_review
    # inline (the unified review_compiled_paper tool writes them directly).
    # Attach VLM findings so the GUI ReviewPanel can render them alongside.
    rr = result.get("review_report")
    if isinstance(rr, dict):
        if isinstance(result.get("vlm_review"), (dict, list)):
            rr["vlm_findings"] = result["vlm_review"]
    # paper tex snippet — check checkpoint root first, then paper/ subdir.
    # Older runs wrote full_paper.tex/pdf at the checkpoint root; newer
    # runs (or those edited via the Overleaf-like UI) may keep them only
    # under paper/. Pair the .pdf with whichever directory the .tex was
    # found in, so the GUI shows a coherent set.
    for tex in (d / "full_paper.tex", d / "paper" / "full_paper.tex"):
        if tex.exists():
            try:
                result["paper_tex"] = tex.read_text(encoding="utf-8", errors="replace")
                pdf = tex.parent / "full_paper.pdf"
                result["has_pdf"] = pdf.exists()
            except Exception:
                result["paper_tex"] = ""
            break
    return result



def _api_lineage_decisions(ckpt_id: str) -> dict:
    """lineage decisions GUI: read ``{checkpoint}/lineage_decisions.jsonl``.

    Returns ``{records: [...], n: int}`` with the records in chronological
    (write) order. Empty list when the file is missing — common case for
    runs that completed without any lineage-decision firing.
    """
    ckpt = _resolve_checkpoint_dir(ckpt_id)
    if ckpt is None:
        return {"error": f"unknown checkpoint: {ckpt_id}", "records": [], "n": 0}
    path = ckpt / "lineage_decisions.jsonl"
    if not path.exists():
        return {"records": [], "n": 0}
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as e:
        return {"error": str(e), "records": [], "n": 0}
    return {"records": records, "n": len(records)}

