from __future__ import annotations
"""ARI viz: api_orchestrator — sub-experiment registry, launch, and listing.

Backs the GUI sub-experiment endpoints. Sub-experiment records live alongside
checkpoints as ``meta.json`` files; this module reads them, caches them in
``state._sub_experiments``, and exposes a launch helper that enforces the
recursion-depth ceiling.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import state as _st


DEFAULT_MAX_RECURSION_DEPTH = 3


def _logs_root() -> Path:
    """Resolve the directory under which sub-experiment checkpoints live.

    Honors ``ARI_ORCHESTRATOR_LOGS`` for tests; otherwise defaults to the
    workspace's ``checkpoints/`` directory adjacent to the project root.
    """
    override = os.environ.get("ARI_ORCHESTRATOR_LOGS")
    if override:
        return Path(override)
    return Path(_st._ari_root) / "workspace" / "checkpoints"


def _scan_disk() -> dict:
    """Scan checkpoint dirs for meta.json files and return {run_id: meta}."""
    found: dict = {}
    base = _logs_root()
    if not base.exists():
        return found
    for ck in base.iterdir():
        if not ck.is_dir():
            continue
        meta_file = ck / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue
        run_id = meta.get("run_id") or ck.name
        record = dict(meta)
        record["checkpoint_dir"] = str(ck)
        found[run_id] = record
    return found


def _api_list_sub_experiments() -> dict:
    """Return all known sub-experiments (disk-authoritative).

    Replaces the in-memory cache with what is actually on disk so that
    deleted checkpoints no longer appear in the listing.
    """
    disk = _scan_disk()
    # Replace cache entirely — stale entries for deleted checkpoints are dropped.
    _st._sub_experiments.clear()
    for rid, meta in disk.items():
        _st.set_sub_experiment(rid, meta)
    items = list(_st.get_sub_experiments().values())
    items.sort(
        key=lambda m: (m.get("created_at") or "", m.get("run_id") or ""),
        reverse=True,
    )
    return {"sub_experiments": items}


def _api_get_sub_experiment(run_id: str) -> dict:
    if not run_id:
        return {"error": "run_id required"}
    disk = _scan_disk()
    if run_id in disk:
        _st.set_sub_experiment(run_id, disk[run_id])
        return disk[run_id]
    cache = _st.get_sub_experiments()
    if run_id in cache:
        return cache[run_id]
    return {"error": f"run_id '{run_id}' not found"}


def _slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "_", text or "experiment")
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:maxlen] or "experiment"


def _api_launch_sub_experiment(body: bytes) -> dict:
    """Launch a child experiment with recursion-depth enforcement.

    Body fields:
      experiment_md (str, required)
      max_recursion_depth (int, default 3)
      parent_run_id (str, optional)
      recursion_depth (int, optional, default 0)
      inherit_idea_index (int, optional) — when set with a parent_run_id,
          materialise the parent's ideas[N] as the child's plan by appending
          a Selected-research-idea block to experiment_md. Catalog access
          (lineage walk) — does NOT touch the parent's plan.md, so children
          remain free to pivot. The directive arrives only because the
          caller explicitly opted in via this field.
      dry_run (bool, optional) — skip subprocess launch (used by tests)
    """
    try:
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return {"ok": False, "error": f"Invalid request body: {e}"}

    experiment_md = data.get("experiment_md", "")
    parent_run_id = data.get("parent_run_id") or None
    recursion_depth = int(data.get("recursion_depth", 0) or 0)
    _raw_mrd = data.get("max_recursion_depth")
    max_recursion_depth = int(_raw_mrd) if _raw_mrd is not None else DEFAULT_MAX_RECURSION_DEPTH
    dry_run = bool(data.get("dry_run"))
    inherit_idea_index = data.get("inherit_idea_index")
    synthetic_idea_data: dict | None = None

    if recursion_depth >= max_recursion_depth:
        return {
            "ok": False,
            "error": (
                f"Recursion limit reached: recursion_depth={recursion_depth} "
                f">= max_recursion_depth={max_recursion_depth}"
            ),
            "recursion_depth": recursion_depth,
            "max_recursion_depth": max_recursion_depth,
            "parent_run_id": parent_run_id,
        }

    # lineage decisions: refuse to launch when the parent BFTS already chose
    # ``terminate`` for the lineage. Without this gate a stale background
    # caller (e.g. retry loop) could keep spawning children after the
    # human / orchestrator decided the thread is exhausted.
    if parent_run_id:
        try:
            from ari.lineage import _resolve_ckpt_by_run_id  # type: ignore
            parent_ckpt_h = _resolve_ckpt_by_run_id(str(parent_run_id))
            if parent_ckpt_h is not None:
                meta_h = json.loads((parent_ckpt_h / "meta.json").read_text())
                if isinstance(meta_h, dict) and meta_h.get("parent_terminated"):
                    return {
                        "ok": False,
                        "error": (
                            "parent lineage was terminated by an upstream "
                            "lineage_decision; refusing to launch child"
                        ),
                        "parent_run_id": parent_run_id,
                        "parent_terminated_rationale": str(
                            meta_h.get("parent_terminated_rationale", "")
                        )[:300],
                    }
        except Exception:
            pass  # never block a launch on terminate-check failure

    # Phase 2: opt-in lineage materialisation.
    if inherit_idea_index is not None:
        if not parent_run_id:
            return {
                "ok": False,
                "error": "inherit_idea_index requires parent_run_id",
            }
        try:
            from ari.lineage import _resolve_ckpt_by_run_id  # type: ignore
            from ari.pipeline import _build_auto_append_block  # type: ignore
        except Exception as e:
            return {"ok": False, "error": f"lineage import failed: {e}"}
        parent_ckpt = _resolve_ckpt_by_run_id(str(parent_run_id))
        if parent_ckpt is None:
            return {
                "ok": False,
                "error": f"parent ckpt for run_id={parent_run_id!r} not found",
            }
        parent_idea_path = parent_ckpt / "idea.json"
        if not parent_idea_path.exists():
            return {
                "ok": False,
                "error": f"parent idea.json missing at {parent_idea_path}",
            }
        try:
            parent_idea = json.loads(parent_idea_path.read_text())
        except Exception as e:
            return {"ok": False, "error": f"parent idea.json malformed: {e}"}
        ideas = parent_idea.get("ideas") or []
        try:
            idx = int(inherit_idea_index)
        except (TypeError, ValueError):
            return {"ok": False, "error": "inherit_idea_index must be an int"}
        if idx < 0 or idx >= len(ideas):
            return {
                "ok": False,
                "error": (
                    f"inherit_idea_index={idx} out of range "
                    f"(parent has {len(ideas)} ideas)"
                ),
            }
        chosen = dict(ideas[idx])
        # Mark this idea so generate_ideas can preserve it at ideas[0] when
        # the child runs VirSci. Without this marker the child's
        # generate_ideas would overwrite the inherited choice with newly
        # generated ideas, and BFTS would silently drift away from the
        # idea the caller asked to inherit.
        chosen["_pinned"] = True
        chosen["_inherited_from"] = {
            "parent_run_id": str(parent_run_id),
            "index": idx,
        }
        synthetic_idea_data = {
            "ideas": [chosen],
            "gap_analysis": parent_idea.get("gap_analysis", ""),
            "primary_metric": parent_idea.get("primary_metric", ""),
            "higher_is_better": parent_idea.get("higher_is_better", True),
            "metric_rationale": parent_idea.get("metric_rationale", ""),
            "_inherited_from": {"parent_run_id": str(parent_run_id), "index": idx},
        }
        block = _build_auto_append_block({"ideas": [chosen]}, mode="full")
        if block:
            sep = "\n\n" if experiment_md else ""
            experiment_md = (experiment_md or "").rstrip() + sep + block + "\n"

    base = _logs_root()
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    first_line = ""
    for line in (experiment_md or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("<!--"):
            first_line = stripped[:60]
            break
    run_id = f"{ts}_{_slugify(first_line)}"
    ckpt_dir = base / run_id
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "recursion_depth": recursion_depth,
        "max_recursion_depth": max_recursion_depth,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint_dir": str(ckpt_dir),
        "inherit_idea_index": inherit_idea_index,
    }
    (ckpt_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    if experiment_md:
        (ckpt_dir / "experiment.md").write_text(experiment_md, encoding="utf-8")

    # Phase 2.5: when inherit_idea_index was honoured, also seed the child's
    # idea.json with the chosen parent idea (pinned). The child's
    # generate_ideas detects this and appends new ideas instead of
    # overwriting, preserving the inherit directive while still letting
    # VirSci explore alternatives.
    if synthetic_idea_data is not None:
        try:
            (ckpt_dir / "idea.json").write_text(
                json.dumps(synthetic_idea_data, ensure_ascii=False, indent=2)
            )
        except Exception:
            # Don't block launch on seed failure — generate_ideas will
            # still run, the child just won't have the pinned idea.
            pass

    _st.set_sub_experiment(run_id, meta)

    pid = None
    if not dry_run:
        cmd = [
            "python3", "-m", "ari.cli", "run",
            str(ckpt_dir / "experiment.md"),
        ]
        proc_env = os.environ.copy()
        proc_env["ARI_PARENT_RUN_ID"] = run_id
        proc_env["ARI_RECURSION_DEPTH"] = str(recursion_depth + 1)
        proc_env["ARI_MAX_RECURSION_DEPTH"] = str(max_recursion_depth)
        proc_env["ARI_CHECKPOINT_DIR"] = str(ckpt_dir)
        try:
            log_fh = open(ckpt_dir / "orchestrator.log", "w")
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd=str(_st._ari_root / "ari-core"),
                env=proc_env,
                start_new_session=True,
            )
            pid = proc.pid
        except Exception as e:
            # lineage decisions: clean up the orphan ckpt_dir so the lineage view
            # is not polluted by a checkpoint that never actually ran.
            try:
                import shutil as _sh_cleanup
                _sh_cleanup.rmtree(ckpt_dir, ignore_errors=True)
                _st._sub_experiments.pop(run_id, None)
            except Exception:
                pass  # best effort
            return {
                "ok": False,
                "error": str(e),
                "run_id": run_id,
                "checkpoint_dir": str(ckpt_dir),
                "cleaned_up": True,
            }

    return {
        "ok": True,
        "run_id": run_id,
        "pid": pid,
        "checkpoint_dir": str(ckpt_dir),
        "parent_run_id": parent_run_id,
        "recursion_depth": recursion_depth,
        "max_recursion_depth": max_recursion_depth,
    }
