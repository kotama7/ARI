"""REST API: EAR (Experiment Artifact Record) curate/publish/clone helpers.

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

# Phase 3B PR-3B-2: module-level publish.yaml default restored from
# the legacy ``api_state.py``.
_PUBLISH_YAML_DEFAULT = {
    "include": ["**/*.py", "README.md", "reproduce.sh", "environment.json"],
    "exclude": ["**/__pycache__/**", "**/*.pyc", "**/.ipynb_checkpoints/**"],
    "max_file_mb": 100,
    "license": "MIT",
    "visibility": "staged",
    "required": False,
    "auto_promote": False,
}


# Phase 3B PR-3B-2: bare-name wrappers that defer to ``api_state``
# at call time so ``monkeypatch.setattr(api_state, name, ...)``
# in tests intercepts the helper this module's functions call.
def _resolve_checkpoint_dir(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._resolve_checkpoint_dir(*args, **kwargs)



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

