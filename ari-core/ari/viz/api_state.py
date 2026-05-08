from __future__ import annotations
import re
"""ARI viz: api_state — checkpoint discovery, tree loading, broadcasting."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st

import logging
log = logging.getLogger(__name__)


def _checkpoint_search_bases() -> list[Path]:
    """Return the canonical list of directories that may contain checkpoint subdirs."""
    _ari_root = Path(__file__).parent.parent.parent.parent  # ARI/
    return [
        _ari_root / "workspace" / "checkpoints",
        _ari_root / "checkpoints",
        Path(__file__).parent.parent.parent / "checkpoints",   # ari-core/checkpoints
        _ari_root / "ari-core" / "checkpoints",
        Path.cwd() / "checkpoints",
        Path.cwd() / "ari-core" / "checkpoints",
        Path(__file__).resolve().parents[2] / "checkpoints",
    ]


def _check_pid_alive(checkpoint_dir: Path) -> str:
    """Check if the process that owns a checkpoint is still alive via .ari_pid."""
    from ari.pidfile import check_pid
    return check_pid(checkpoint_dir)


def _load_nodes_tree() -> dict | None:
    """Load the active checkpoint's node tree (Phase 2 §6-1 delegation).

    Search order, retry-on-mid-write semantics, and the empty-dict
    rejection rule live in ``ari.checkpoint.load_nodes_tree``; this
    wrapper only feeds it the active checkpoint dir from ``_st``.
    """
    if _st._checkpoint_dir is None:
        return None
    from ari.checkpoint import load_nodes_tree as _load
    return _load(_st._checkpoint_dir)



def _broadcast(data: dict) -> None:
    if not _st._clients or _st._loop is None:
        return
    msg = json.dumps({"type": "update", "data": data,
                       "timestamp": datetime.now(timezone.utc).isoformat()})
    asyncio.run_coroutine_threadsafe(_do_broadcast(msg), _st._loop)



async def _do_broadcast(msg: str) -> None:
    dead = set()
    for ws in list(_st._clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _st._clients.difference_update(dead)


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
                # Phase 2: Refine status from tree.json node data
                nt = d / "nodes_tree.json"
                tf = d / "tree.json"
                if tf.exists() and tf.stat().st_size > 0:
                    nt = tf
                if nt.exists() and nt.stat().st_size > 0:
                    try:
                        tree = json.loads(nt.read_text(encoding="utf-8", errors="replace"))
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
                    except Exception:
                        log.debug("checkpoint node parsing error: %s", d.name, exc_info=True)
                        pass
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



def _resolve_checkpoint_dir(ckpt_id: str) -> Path | None:
    """Locate a checkpoint directory by id across known search paths."""
    for base in _checkpoint_search_bases():
        p = base / ckpt_id
        if p.exists():
            return p
    return None


def _api_ear(run_id: str) -> dict:
    """Return Experiment Artifact Repository contents for a checkpoint.

    Lists the directory tree under <ckpt>/ear/, returns README/RESULTS
    markdown content inline, and exposes file metadata for the GUI.
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    ear_dir = d / "ear"
    if not ear_dir.exists():
        return {"error": "no EAR directory for this checkpoint", "ear_dir": str(ear_dir)}

    files: list[dict] = []
    for f in sorted(ear_dir.rglob("*")):
        try:
            rel = str(f.relative_to(ear_dir))
        except ValueError:
            continue
        if f.is_dir():
            files.append({"path": rel, "type": "dir"})
            continue
        try:
            size = f.stat().st_size
        except Exception:
            size = 0
        files.append({"path": rel, "type": "file", "size": size})

    def _read(name: str) -> str:
        p = ear_dir / name
        if not p.exists() or not p.is_file():
            return ""
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:200_000]
        except Exception:
            return ""

    # ── Curation surface ──
    # If ear_published/manifest.lock exists, include a "published" block
    # so the Results page can surface bundle digest, file count, and
    # visibility without re-running the curator.
    published: dict | None = None
    pub_dir = d / "ear_published"
    pub_manifest = pub_dir / "manifest.lock"
    publish_yaml = ear_dir / "publish.yaml"
    if pub_manifest.exists():
        try:
            mf = json.loads(pub_manifest.read_text(encoding="utf-8"))
            published = {
                "ear_published_dir": str(pub_dir),
                "bundle_sha256": mf.get("bundle_sha256", ""),
                "file_count": len(mf.get("files", [])),
                "visibility": (mf.get("publish") or {}).get("visibility"),
                "excluded_count": mf.get("excluded_count", 0),
                "files": [f.get("path") for f in mf.get("files", [])],
                "created_at": mf.get("created_at"),
            }
        except Exception as e:
            published = {"error": f"manifest parse failed: {e}"}

    # RESULTS.md (v0.6.0) lived under ear/. EVOLUTION.md is now an audit
    # log at checkpoint root, not bundled into ear/. Surface whichever is
    # present so the GUI's "results" panel keeps working.
    def _read_ckpt(name: str) -> str:
        p = d / name
        if not p.exists() or not p.is_file():
            return ""
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:200_000]
        except Exception:
            return ""

    results_md = _read("RESULTS.md") or _read_ckpt("EVOLUTION.md")

    return {
        "run_id": run_id,
        "ear_dir": str(ear_dir),
        "files": files,
        "readme": _read("README.md"),
        "results": results_md,
        "file_count": sum(1 for f in files if f.get("type") == "file"),
        "publish_yaml_present": publish_yaml.exists(),
        "published": published,
    }


def _api_node_report(run_id: str, node_id: str) -> dict:
    """Return the node_report.json for a given (run_id, node_id), or an
    error if the report doesn't exist.

    Used by the GUI Tree page's Report tab to surface a node's structured
    self-report (files_changed diff, concerns, next_steps_hints, etc.)
    without re-running anything.
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    # PathManager-style layout: workspace/experiments/{run_id}/{node_id}/.
    # If the checkpoint is at {workspace}/checkpoints/{run_id}/, the
    # experiments root sits as a sibling.
    workspace = d.parent.parent if d.parent.name == "checkpoints" else d.parent
    candidates = [
        workspace / "experiments" / run_id / node_id / "node_report.json",
        workspace / "experiments" / node_id / "node_report.json",
    ]
    for rp in candidates:
        if rp.is_file():
            try:
                return {"run_id": run_id, "node_id": node_id,
                        "report": json.loads(rp.read_text(encoding="utf-8"))}
            except Exception as exc:
                return {"error": f"failed to parse node_report: {exc}"}
    return {"error": "no node_report for this node",
            "run_id": run_id, "node_id": node_id}


def _api_ear_clone_verify(body: bytes) -> dict:
    """POST /api/ear/clone-verify — wraps `ari clone` in a non-network-effecting
    digest-verify mode. Used by the GUI to confirm a paper's digest against a
    locally-available bundle (file:// or https://).

    Body: {"ref": "...", "dest": "...", "expect_sha256": "...", "extract": bool}
    """
    try:
        payload = json.loads(body or b"{}") if body else {}
    except Exception:
        return {"error": "invalid JSON body"}
    ref = (payload.get("ref") or "").strip()
    dest = (payload.get("dest") or "").strip()
    expect_sha256 = (payload.get("expect_sha256") or "").strip() or None
    extract = bool(payload.get("extract", True))
    if not ref or not dest:
        return {"error": "ref and dest are required"}
    try:
        from ari.clone import clone, CloneError
    except Exception as e:
        return {"error": f"ari.clone not importable: {e}"}
    try:
        result = clone(ref, dest=Path(dest), expect_sha256=expect_sha256, extract=extract)
    except CloneError as e:
        return {"error": str(e), "kind": "CloneError"}
    except NotImplementedError as e:
        return {"error": str(e), "kind": "NotImplementedError"}
    return {
        "ref": result.ref,
        "dest": str(result.dest),
        "bundle_sha256": result.bundle_sha256,
        "file_count": result.file_count,
        "extracted": result.extracted,
    }


def _api_ear_curate(run_id: str) -> dict:
    """POST /api/ear/<run_id>/curate — run the EAR curator for a checkpoint.

    Wires the GUI Results page to the `ari ear curate` CLI. Returns
    the curate result (bundle_sha256, included_files, ...) or {"skipped":
    True} when publish.yaml is absent.
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    if not (d / "ear").is_dir():
        return {"error": "no EAR directory for this checkpoint"}

    # Locate the curate module without requiring an editable install of the
    # transform skill (matches the dev-checkout fallback used in cli_ear).
    import sys as _sys
    try:
        import curate as _curate  # type: ignore
    except ModuleNotFoundError:
        _here = Path(__file__).resolve()
        for parent in [_here, *_here.parents]:
            cand = parent / "ari-skill-transform" / "src"
            if cand.is_dir():
                _sys.path.insert(0, str(cand))
                break
        try:
            import curate as _curate  # type: ignore
        except ModuleNotFoundError:
            return {"error": "ari-skill-transform/curate.py not importable"}

    try:
        res = _curate.curate(d)
    except _curate.CurateError as e:
        return {"error": str(e), "kind": "CurateError"}

    return {
        "ear_published_dir": str(res.ear_published_dir),
        "manifest_path": str(res.manifest_path),
        "bundle_sha256": res.bundle_sha256,
        "included_files": res.included_files,
        "excluded_count": res.excluded_count,
        "skipped": res.skipped,
    }


_PUBLISH_YAML_DEFAULT = {
    "include": ["**/*.py", "README.md", "reproduce.sh", "environment.json"],
    "exclude": ["**/__pycache__/**", "**/*.pyc", "**/.ipynb_checkpoints/**"],
    "max_file_mb": 100,
    "license": "MIT",
    "visibility": "staged",
    "required": False,
    "auto_promote": False,
}


def _api_ear_publish_yaml_get(run_id: str) -> dict:
    """GET /api/ear/<run_id>/publish-yaml.

    Returns the current publish.yaml content (raw text + parsed dict) or, if
    the file is absent, a default template the GUI editor can pre-fill so the
    user can customise then save in one click.
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    ear_dir = d / "ear"
    if not ear_dir.is_dir():
        return {"error": "no EAR directory for this checkpoint",
                "ear_dir": str(ear_dir), "exists": False}
    yml = ear_dir / "publish.yaml"
    if not yml.exists():
        try:
            import yaml as _yaml
            text = _yaml.safe_dump(_PUBLISH_YAML_DEFAULT, sort_keys=False, allow_unicode=True)
        except Exception:
            text = ""
        return {
            "exists": False,
            "path": str(yml),
            "text": text,
            "data": dict(_PUBLISH_YAML_DEFAULT),
        }
    text = yml.read_text(encoding="utf-8")
    parsed: dict | None = None
    try:
        import yaml as _yaml
        parsed = _yaml.safe_load(text) or {}
        if not isinstance(parsed, dict):
            parsed = {"_parse_error": "top-level must be a mapping"}
    except Exception as e:
        parsed = {"_parse_error": str(e)}
    return {"exists": True, "path": str(yml), "text": text, "data": parsed}


def _api_ear_publish_yaml_set(run_id: str, body: bytes) -> dict:
    """POST /api/ear/<run_id>/publish-yaml.

    Accepts either {"text": "<raw yaml>"} or a dict matching the publish.yaml
    schema. Writes <ckpt>/ear/publish.yaml. Validates that the result is a
    YAML mapping with list-typed include/exclude (curate.py's hard contract).
    """
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return {"error": "checkpoint not found"}
    ear_dir = d / "ear"
    if not ear_dir.is_dir():
        return {"error": "no EAR directory for this checkpoint"}
    try:
        payload = json.loads(body or b"{}")
    except Exception as e:
        return {"error": f"invalid JSON body: {e}"}
    try:
        import yaml as _yaml
    except Exception as e:
        return {"error": f"pyyaml unavailable: {e}"}

    if "text" in payload:
        text = str(payload.get("text") or "")
        try:
            parsed = _yaml.safe_load(text) or {}
        except Exception as e:
            return {"error": f"YAML parse error: {e}"}
    else:
        parsed = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        text = _yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)

    if not isinstance(parsed, dict):
        return {"error": "publish.yaml must be a YAML mapping at the top level"}
    if not isinstance(parsed.get("include", []), list) or not isinstance(parsed.get("exclude", []), list):
        return {"error": "`include` and `exclude` must be lists of glob strings"}

    yml = ear_dir / "publish.yaml"
    yml.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(yml), "text": text, "data": parsed}


def _synth_repro_report_from_ors(d: Path) -> dict | None:
    """Build a GUI-friendly reproducibility_report dict from ors_*.json.

    Returns None when no usable ORS file is present. Otherwise returns a
    dict with verdict / summary / fields the existing GUI renderer expects
    (ResultsPage.tsx renderRepro). When ``ors_grade.json`` is itself an
    error string from the MCP layer, surfaces that as a red FAILED verdict
    instead of a parse failure.
    """
    grade_p = d / "ors_grade.json"
    phase1_p = d / "ors_phase1.json"
    repl_p = d / "ors_replicator.json"
    if not any(p.exists() and p.stat().st_size > 0 for p in (grade_p, phase1_p, repl_p)):
        return None

    grade: dict | None = None
    if grade_p.exists() and grade_p.stat().st_size > 0:
        try:
            grade = json.loads(grade_p.read_text())
        except Exception:
            log.debug("ors_grade parse error", exc_info=True)
            grade = {"_parse_error": True}

    # MCP error envelope: ``{"result": "Error executing tool ...: <msg>"}``.
    if isinstance(grade, dict) and "result" in grade and "error" in str(grade.get("result", "")).lower():
        return {
            "verdict": "FAILED",
            "summary": "Reproducibility grading failed (see ors_grade.json).",
            "error": str(grade["result"])[:500],
        }

    phase1: dict | None = None
    if phase1_p.exists() and phase1_p.stat().st_size > 0:
        try:
            phase1 = json.loads(phase1_p.read_text())
        except Exception:
            phase1 = None

    replicator: dict | None = None
    if repl_p.exists() and repl_p.stat().st_size > 0:
        try:
            replicator = json.loads(repl_p.read_text())
        except Exception:
            replicator = None

    if not isinstance(grade, dict) or "ors_score" not in grade:
        # No grade yet — but other ORS files exist, so report intermediate state.
        if phase1 and not phase1.get("executed", False):
            return {
                "verdict": "PENDING",
                "summary": phase1.get("skipped_reason")
                or phase1.get("error")
                or "reproduce.sh did not run",
            }
        if replicator and replicator.get("populated"):
            return {
                "verdict": "PENDING",
                "summary": "Replicator wrote reproduce.sh; awaiting Phase 1 / Phase 2.",
                "replicator_files": replicator.get("files"),
            }
        return None

    score = float(grade.get("ors_score") or 0.0)
    leaves = grade.get("leaf_grades") or []
    passed = sum(1 for lg in leaves if (lg.get("passed_runs") or 0) > 0)
    total = len(leaves)

    # Verdict thresholds: tuned to PaperBench's adversarial rubric severity.
    if score >= 0.7:
        verdict = "REPRODUCED"
    elif score >= 0.3:
        verdict = "PARTIAL"
    else:
        verdict = "NOT_REPRODUCED"

    if grade.get("degraded"):
        # Degraded run — the sandbox was empty / missing. Make this explicit.
        verdict = "ENVIRONMENT_MISMATCH"
        summary = (
            grade.get("degraded_reason")
            or "Graded against an empty submission (degraded path)."
        )
    else:
        summary = (
            f"PaperBench grading: {passed}/{total} leaves passed "
            f"(weighted score {score:.3f})."
        )

    out: dict = {
        "verdict": verdict,
        "summary": summary,
        "ors_score": round(score, 4),
        "raw_score": round(float(grade.get("raw_score") or 0.0), 4),
        "passed_leaves": passed,
        "total_leaves": total,
        "judge_model": grade.get("judge_model"),
        "n_runs": grade.get("n_runs"),
        "elapsed_sec": grade.get("elapsed_sec"),
    }
    if replicator and replicator.get("populated"):
        out["replicator_model"] = replicator.get("model")
    if phase1 is not None:
        out["phase1_executed"] = bool(phase1.get("executed", False))
        if phase1.get("missing"):
            out["phase1_missing_artifacts"] = phase1["missing"]
    return out


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

    # Load tree data (prefer tree.json, fallback to nodes_tree.json)
    for _tree_fname in ("tree.json", "nodes_tree.json"):
        _tp = d / _tree_fname
        if _tp.exists() and _tp.stat().st_size > 0:
            try:
                result["nodes_tree"] = json.loads(_tp.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                result["nodes_tree"] = {"_parse_error": str(e)}
            break

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


# ── Checkpoint paper/ directory management (Overleaf-like editing) ──────────

PAPER_DIR_NAME = "paper"

_TEXT_EXTENSIONS = {
    ".tex", ".bib", ".sty", ".cls", ".bst", ".bbl",
    ".txt", ".md", ".csv",
}


_PAPER_ROOT_ARTEFACTS = (
    "full_paper.tex", "full_paper.pdf", "full_paper.bbl", "refs.bib",
)
_FIGURE_GLOBS = (
    "fig_*.pdf", "fig_*.png", "fig_*.eps", "fig_*.svg",
    "fig_*.jpg", "fig_*.jpeg", "fig_*.tiff",
)


def _ensure_paper_dir(ckpt_id: str) -> tuple[Path | None, str | None]:
    """Return the paper/ dir for a checkpoint, creating & seeding it if needed.

    Historically this only seeded when paper/ did not yet exist. That left
    the dir permanently empty when a first (failing) pipeline run created
    paper/figures/ and a subsequent successful run wrote full_paper.tex at
    the checkpoint root — the GUI's "Files" tab then showed "0 files".

    This version also detects drift: if any root-level paper artefact
    (full_paper.tex/pdf/bbl, refs.bib, fig_*.{pdf,png,...}) is newer than —
    or missing from — the paper/ subdir, it gets (re-)copied. mtime-based
    so user edits inside paper/ are preserved unless the root version is
    newer.

    Returns (paper_dir, error).  On success error is None.
    """
    import shutil
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return None, "checkpoint not found"
    paper = d / PAPER_DIR_NAME
    paper.mkdir(parents=True, exist_ok=True)
    fig_dir = paper / "figures"
    fig_dir.mkdir(exist_ok=True)

    def _copy_if_newer(src: Path, dst: Path) -> None:
        """Copy src → dst if dst is missing or older than src."""
        try:
            if not dst.exists():
                shutil.copy2(str(src), str(dst))
                return
            if src.stat().st_mtime > dst.stat().st_mtime + 1e-3:
                shutil.copy2(str(src), str(dst))
        except Exception as e:
            log.debug("paper-dir seed: %s → %s failed: %s", src, dst, e)

    # Root-level paper artefacts
    for name in _PAPER_ROOT_ARTEFACTS:
        src = d / name
        if src.exists() and src.is_file():
            _copy_if_newer(src, paper / name)

    # Figure images (only the primary PDF/PNG go to the LaTeX editor;
    # keep the PNG companions so the GUI can render previews).
    for pattern in _FIGURE_GLOBS:
        for src in d.glob(pattern):
            if src.is_file():
                _copy_if_newer(src, fig_dir / src.name)

    return paper, None


def _api_checkpoint_files(ckpt_id: str) -> dict:
    """List files inside checkpoint paper/ directory."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    files: list[dict] = []
    for f in sorted(paper.rglob("*")):
        if f.is_dir():
            continue
        try:
            rel = str(f.relative_to(paper))
        except ValueError:
            continue
        try:
            size = f.stat().st_size
        except Exception:
            size = 0
        ext = f.suffix.lower()
        files.append({
            "name": rel,
            "size": size,
            "editable": ext in _TEXT_EXTENSIONS,
            "ext": ext,
            "abs_path": str(f),
        })
    return {"id": ckpt_id, "path": str(paper), "files": files}


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


def _api_checkpoint_file_read(ckpt_id: str, filename: str) -> dict:
    """Read content of a single file in checkpoint paper/ dir."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target = (paper / filename).resolve()
    try:
        target.relative_to(paper.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    if not target.exists() or not target.is_file():
        return {"error": "file not found"}
    if target.stat().st_size > 5_000_000:
        return {"error": "file too large (>5MB)"}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}
    return {"name": filename, "content": content}


def _resolve_paper_file(ckpt_id: str, filename: str) -> tuple[Path | None, str | None]:
    """Resolve a file path inside paper/ dir.  Returns (path, error)."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return None, err
    target = (paper / filename).resolve()
    try:
        target.relative_to(paper.resolve())
    except ValueError:
        return None, "path traversal denied"
    if not target.exists() or not target.is_file():
        return None, "file not found"
    if target.stat().st_size > 20_000_000:
        return None, "file too large (>20MB)"
    return target, None


def _api_checkpoint_file_save(body: bytes) -> dict:
    """Save (overwrite) a text file in checkpoint paper/ dir."""
    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    filename = data.get("filename", "")
    content = data.get("content", "")
    if not ckpt_id or not filename:
        return {"error": "checkpoint_id and filename required"}
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target = (paper / filename).resolve()
    try:
        target.relative_to(paper.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "path": str(target), "size": len(content.encode("utf-8"))}


def _api_checkpoint_file_upload(ckpt_id: str, filename: str, data: bytes) -> dict:
    """Upload a file into checkpoint paper/ dir."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    safe_name = Path(filename).name
    if not safe_name:
        return {"error": "invalid filename"}
    target = (paper / safe_name).resolve()
    try:
        target.relative_to(paper.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    try:
        target.write_bytes(data)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "name": safe_name, "path": str(target), "size": len(data)}


def _api_checkpoint_file_delete(body: bytes) -> dict:
    """Delete a single file from checkpoint paper/ dir."""
    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    filename = data.get("filename", "")
    if not ckpt_id or not filename:
        return {"error": "checkpoint_id and filename required"}
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target = (paper / filename).resolve()
    try:
        target.relative_to(paper.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    if not target.exists():
        return {"error": "file not found"}
    try:
        target.unlink()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "deleted": filename}


def _api_checkpoint_compile(body: bytes) -> dict:
    """Compile LaTeX in checkpoint paper/ directory.

    Runs: pdflatex → bibtex → pdflatex → pdflatex  (standard 4-pass).
    """
    import subprocess as _sp
    import shutil

    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    main_file = data.get("main_file", "full_paper.tex")
    if not ckpt_id:
        return {"error": "checkpoint_id required"}

    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}

    tex_path = paper / main_file
    if not tex_path.exists():
        return {"error": f"{main_file} not found in paper/"}

    pdflatex = os.environ.get("PDFLATEX_PATH", "pdflatex")
    bibtex = os.environ.get("BIBTEX_PATH", "bibtex")
    stem = main_file.replace(".tex", "")
    cwd = str(paper)
    logs: list[str] = []

    try:
        cmds = [
            [pdflatex, "-interaction=nonstopmode", main_file],
            [bibtex, stem],
            [pdflatex, "-interaction=nonstopmode", main_file],
            [pdflatex, "-interaction=nonstopmode", main_file],
        ]
        for cmd in cmds:
            r = _sp.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
            logs.append(f"$ {' '.join(cmd)}  (exit {r.returncode})")
            if r.stdout:
                logs.append(r.stdout[-1500:])
            if r.stderr:
                logs.append(r.stderr[-500:])
    except _sp.TimeoutExpired:
        logs.append("ERROR: compilation timed out")
        return {"ok": False, "log": "\n".join(logs)}
    except FileNotFoundError:
        return {"ok": False, "log": f"pdflatex not found ({pdflatex}). Install a LaTeX distribution."}

    pdf_path = paper / f"{stem}.pdf"
    success = pdf_path.exists() and pdf_path.stat().st_size > 1024

    # Copy PDF back to checkpoint root so the PDF viewer picks it up
    if success:
        d = _resolve_checkpoint_dir(ckpt_id)
        if d:
            try:
                shutil.copy2(str(pdf_path), str(d / f"{stem}.pdf"))
            except Exception:
                pass

    return {"ok": success, "log": "\n".join(logs)}


def _api_delete_checkpoint(body: bytes) -> dict:
    """Delete a checkpoint directory and associated log files."""
    import shutil
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    # Resolve symlinks (e.g. /home/ may be a symlink on some HPC systems)
    try:
        p = p.resolve()
    except Exception:
        log.debug("path resolve failed: %s", path, exc_info=True)
        pass
    if not p.exists():
        # Try without resolving (path might already be canonical)
        p = Path(path)
        if not p.exists():
            return {"error": f"not found: {path}"}
    # Safety: must be inside a checkpoints directory
    if "checkpoints" not in str(p) and "checkpoints" not in str(path):
        return {"error": "refusing to delete outside checkpoints/"}
    try:
        _resolved_del = str(p.resolve())
        if _st._checkpoint_dir and str(Path(_st._checkpoint_dir).resolve()) == _resolved_del:
            _st.set_active_checkpoint(None)  # Deselect if deleting active checkpoint
            _st._last_log_path = None   # Clear log path to stop stale log display
            _st._last_experiment_md = None
            _st._last_proc = None       # Clear process ref to stop log streaming
        _st._running_procs.pop(_resolved_del, None)  # Clean up process tracking
        # Clean up sub-experiment cache for the deleted checkpoint
        _del_name = p.name
        _st._sub_experiments.pop(_del_name, None)
        # Collect log files in parent dir that were created around the same time
        parent = p.parent
        deleted_logs = []
        try:
            ckpt_mtime = p.stat().st_mtime
            for log_f in parent.glob("ari_run_*.log"):
                # Delete logs created within 60s of the checkpoint
                if abs(log_f.stat().st_mtime - ckpt_mtime) < 60:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("log cleanup error", exc_info=True)
            pass
        # Best-effort memory purge before removing the checkpoint dir so the
        # Letta agent + archival entries bound to this checkpoint are cleaned.
        # Failures are logged but never block the on-disk delete.
        try:
            from ari_skill_memory.backends import get_backend
            backend = get_backend(checkpoint_dir=p)
            backend.purge_checkpoint()
        except Exception as _e:
            log.warning("memory purge failed for %s: %s", p, _e)
        shutil.rmtree(str(p))
        # Also remove the sibling experiments/{run_id}/ directory that
        # holds per-node work_dirs created by PathManager.ensure_node_work_dir.
        # Without this, deleting a checkpoint leaves orphan node work_dirs
        # under {workspace}/experiments/ that nothing references anymore.
        #
        # Historically the CLI minted its own run_id (LLM title + fresh
        # timestamp) that differed from the GUI-prepared checkpoint dir
        # name, so the naive join below missed the real experiments dir.
        # We now also search for siblings that share the 14-char timestamp
        # prefix or any node_{checkpoint_name}_* subdir — covering both
        # aligned and legacy orphans.
        deleted_experiments = []
        try:
            from ari.paths import PathManager as _PM_del
            _pm_del = _PM_del.from_checkpoint_dir(p)
            _exp_root = _pm_del.experiments_root
            _primary = _exp_root / _del_name
            if _primary.is_dir():
                shutil.rmtree(str(_primary))
                deleted_experiments.append(str(_primary))
            # Fallbacks only kick in when the aligned-name match was not
            # found — otherwise we would risk deleting unrelated projects
            # that happen to share the same 14-digit timestamp second.
            if not deleted_experiments and _exp_root.is_dir():
                # Node-directory match: experiments/*/node_{ckpt_name}_*.
                # This handles legacy orphans where the CLI minted its own
                # run_id (so the dir name differs) but node_ids still embed
                # the checkpoint name. Precise enough that same-timestamp
                # siblings belonging to other projects stay intact.
                for _cand in _exp_root.iterdir():
                    if not _cand.is_dir():
                        continue
                    try:
                        _node_dirs = list(_cand.glob(f"node_{_del_name}_*"))
                    except OSError:
                        _node_dirs = []
                    if _node_dirs:
                        shutil.rmtree(str(_cand))
                        deleted_experiments.append(str(_cand))
        except Exception:
            log.debug("experiments dir cleanup error", exc_info=True)
            pass
        # Also clean up zero-byte orphan logs in parent
        try:
            for log_f in parent.glob("ari_run_*.log"):
                if log_f.stat().st_size == 0:
                    log_f.unlink()
                    deleted_logs.append(log_f.name)
        except Exception:
            log.debug("empty log cleanup error", exc_info=True)
            pass
        result = {"ok": True, "deleted": str(p), "cleaned_logs": len(deleted_logs)}
        if deleted_experiments:
            result["deleted_experiments"] = deleted_experiments
            result["experiments_cleaned"] = len(deleted_experiments)
        return result
    except Exception as e:
        return {"error": str(e)}



def _api_switch_checkpoint(body: bytes) -> dict:
    """Switch active checkpoint directory."""
    data = json.loads(body)
    path = data.get("path", "")
    if not path:
        return {"error": "path required"}
    p = Path(path)
    if not p.exists():
        return {"error": f"not found: {path}"}
    _st.set_active_checkpoint(p)
    _st._last_mtime = 0.0  # force reload
    # Clear stale project-specific state from previous checkpoint
    if _st._last_log_fh:
        try:
            _st._last_log_fh.close()
        except Exception:
            pass
    _st._last_log_fh = None
    _st._last_experiment_md = None
    # Restore log path from checkpoint (project-isolated log)
    _log_candidates = sorted(
        p.glob("ari_run_*.log"),
        key=lambda f: f.stat().st_mtime, reverse=True
    ) if p.exists() else []
    _log_candidates = [c for c in _log_candidates if c.stat().st_size > 0]
    if _log_candidates:
        _st._last_log_path = _log_candidates[0]
    else:
        _st._last_log_path = None
    # Restore launch_config from checkpoint so /state shows correct values.
    # If launch_config.json does not exist, clear stale config from previous project.
    _lc_path = p / "launch_config.json"
    if _lc_path.exists():
        try:
            _st._launch_config = json.loads(_lc_path.read_text())
            _st._launch_llm_model = _st._launch_config.get("llm_model", "")
            _st._launch_llm_provider = _st._launch_config.get("llm_provider", "")
        except Exception:
            pass
    else:
        _st._launch_config = None
        _st._launch_llm_model = None
        _st._launch_llm_provider = None
    # Broadcast updated tree immediately
    tree = _load_nodes_tree()
    if tree:
        _broadcast(tree)
    return {"ok": True, "path": str(p)}



def _watcher_thread() -> None:
    _last_mtimes: dict[str, float] = {}
    _last_ckpt: "Path | None" = None
    while True:
        time.sleep(1)
        if _st._checkpoint_dir is None:
            continue
        # Reset mtime cache when checkpoint directory changes
        if _st._checkpoint_dir != _last_ckpt:
            _last_mtimes.clear()
            _last_ckpt = _st._checkpoint_dir
        # Check both files for changes (tree.json preferred by _load_nodes_tree)
        changed = False
        for fname in ("tree.json", "nodes_tree.json"):
            p = _st._checkpoint_dir / fname
            if not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
                if mtime != _last_mtimes.get(fname, 0):
                    _last_mtimes[fname] = mtime
                    changed = True
            except Exception:
                log.debug("watcher mtime check error", exc_info=True)
                pass
        # Also watch node_*/tree.json for experiments where tree lives in subdirs
        if not changed:
            try:
                for _nf in _st._checkpoint_dir.glob("node_*/tree.json"):
                    try:
                        _nf_key = str(_nf)
                        _nf_mtime = _nf.stat().st_mtime
                        if _nf_mtime != _last_mtimes.get(_nf_key, 0):
                            _last_mtimes[_nf_key] = _nf_mtime
                            changed = True
                    except OSError:
                        continue
            except Exception:
                pass
        if not changed:
            continue
        data = _load_nodes_tree()
        if data:
            _broadcast(data)


# ── Checkpoint file-tree browsing (working-directory explorer) ─────────

_BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".dylib", ".exe",
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".ico",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".bin", ".dat", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5",
    ".pt", ".pth", ".ckpt", ".safetensors",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}

_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".tox", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "dist", ".eggs", "*.egg-info"}


def _resolve_node_work_dir(ckpt_dir: Path, node_id: str) -> Path | None:
    """Locate a node's work directory under the checkpoint's workspace.

    Layout: ``{workspace_root}/experiments/{run_id}/{node_id}/`` where
    ``run_id == ckpt_dir.name``. A legacy fallback scans
    ``experiments/*/{node_id}/`` for directories produced before the
    run_id-keyed layout was introduced.
    """
    from ari.paths import PathManager
    pm = PathManager.from_checkpoint_dir(ckpt_dir)
    run_id = ckpt_dir.name
    candidate = pm.experiments_root / run_id / node_id
    if candidate.exists() and candidate.is_dir():
        return candidate
    # Legacy fallback: older runs wrote experiments/{topic_slug}/{node_id}/.
    # Prefer a bucket whose name matches the run_id's topic slug suffix
    # (``YYYYMMDDHHMMSS_<slug>``) so same-topic runs don't collide.
    legacy_slug: str | None = None
    m = re.match(r'^[0-9]{8,14}_(.+)$', run_id)
    if m:
        legacy_slug = m.group(1)
    exp_root = pm.experiments_root
    if exp_root.exists():
        if legacy_slug is not None:
            cand = exp_root / legacy_slug / node_id
            if cand.exists() and cand.is_dir():
                return cand
        for bucket in exp_root.iterdir():
            if not bucket.is_dir():
                continue
            cand = bucket / node_id
            if cand.exists() and cand.is_dir():
                return cand
    return None


def _api_checkpoint_filetree(ckpt_id: str, node_id: str = "") -> dict:
    """Return the directory tree for a checkpoint, or a specific node.

    When *node_id* is provided, return the tree of that node's work
    directory under ``experiments/{run_id}/{node_id}/``. Otherwise, return
    the full checkpoint directory tree.
    """
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}
    is_node_view = bool(node_id)
    if is_node_view:
        nd = _resolve_node_work_dir(d, node_id)
        if nd is None:
            return {"error": f"node work_dir not found for {node_id}"}
        d = nd

    from ari.paths import PathManager

    def _build_tree(base: Path, rel_prefix: str = "") -> list[dict]:
        entries: list[dict] = []
        try:
            children = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return entries
        for child in children:
            name = child.name
            if name.startswith(".") and name not in (".env",):
                continue
            # When viewing a node's work_dir, hide ARI metadata files
            # (node_report.json, viz_access.jsonl, memory_access.jsonl, …)
            # so they don't masquerade as experiment artefacts.
            if is_node_view and child.is_file() and PathManager.is_meta_file(name):
                continue
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if child.is_dir():
                if name in _SKIP_DIRS or name.endswith(".egg-info"):
                    continue
                sub = _build_tree(child, rel)
                entries.append({"name": name, "path": rel, "type": "dir", "children": sub})
            elif child.is_file():
                ext = child.suffix.lower()
                try:
                    size = child.stat().st_size
                except Exception:
                    size = 0
                is_text = ext not in _BINARY_EXTENSIONS and size < 10_000_000
                entries.append({
                    "name": name,
                    "path": rel,
                    "type": "file",
                    "size": size,
                    "ext": ext,
                    "readable": is_text,
                })
        return entries

    tree = _build_tree(d)
    return {"id": ckpt_id, "path": str(d), "tree": tree}


def _api_checkpoint_filecontent(ckpt_id: str, filepath: str, node_id: str = "") -> dict:
    """Read a file's content from a checkpoint directory, or a node's work dir."""
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}
    if node_id:
        nd = _resolve_node_work_dir(d, node_id)
        if nd is None:
            return {"error": f"node work_dir not found for {node_id}"}
        d = nd
    target = (d / filepath).resolve()
    # Security: must be inside base dir
    try:
        target.relative_to(d.resolve())
    except ValueError:
        return {"error": "path traversal denied"}
    if not target.exists() or not target.is_file():
        return {"error": "file not found"}
    if target.stat().st_size > 5_000_000:
        return {"error": "file too large (>5MB)"}
    ext = target.suffix.lower()
    if ext in _BINARY_EXTENSIONS:
        return {"error": "binary file — cannot display"}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}
    return {"name": filepath, "content": content}


def _api_checkpoint_memory(ckpt_id: str) -> dict:
    """Return memory entries for a checkpoint, grouped by node_id.-process backend library — viz never spawns the MCP skill.
    """
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return {"error": "checkpoint not found"}

    entries: list[dict] = []
    err: str | None = None

    try:
        from ari.paths import PathManager as _PM_mem
        _PM_mem.set_checkpoint_dir_env(d)
        from ari_skill_memory.backends import get_backend
        backend = get_backend(checkpoint_dir=d)
        # node-scope entries
        for nid, lst in backend.list_all_nodes().get("by_node", {}).items():
            for e in lst:
                entries.append({
                    "node_id": nid,
                    "text": e.get("text", ""),
                    "metadata": e.get("metadata", {}) or {},
                    "ts": e.get("ts"),
                    "source": "mcp",
                })
        # react-trace entries
        for e in backend.list_react_entries():
            md = e.get("metadata", {}) or {}
            entries.append({
                "node_id": md.get("node_id", ""),
                "text": e.get("content", ""),
                "metadata": md,
                "ts": e.get("ts"),
                "source": "file_client",
            })
    except Exception as e:  # pragma: no cover - depends on Letta deployment
        err = f"memory backend unavailable: {e}"
        log.warning("viz: %s", err)

    by_node: dict[str, list[dict]] = {}
    for e in entries:
        by_node.setdefault(e.get("node_id") or "_unscoped", []).append(e)

    return {
        "id": ckpt_id,
        "entries": entries,
        "by_node": by_node,
        # Global memory is removed in v0.6.0. The field is retained
        # so the existing frontend schema keeps working.
        "global": [],
        "error": err,
        "count": len(entries),
    }


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────
