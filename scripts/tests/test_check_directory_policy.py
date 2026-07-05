#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_directory_policy.py.

Covers (subtask 028 §12/§13):
  * Rule A — a valid config trio produces no trio-* findings; a `sonfigs/` dir
    fires banned-dir; a config-family collision under a scan parent fires
    config-collision; a non-family sibling (`config2`) does NOT fire; a missing
    marker / wrong kind fires trio-marker / trio-kind;
  * Rule B — a new top-level `runs/` storage dir warns; allowlisted `checkpoints/`
    + `workspace/` do not;
  * Rule C — a synthetic TRACKED `node_modules/` + `*.pyc` fire (from_git=True);
    a clean file list fires nothing;
  * allowlist — a finding whose id is in `<name>.allow.yaml` reports as `known`;
  * repo smoke (real tree, subprocess): the checker is clean (0 findings, exit 0),
    `--strict` passes, and `sonfigs/` is confirmed absent (the phantom stays absent).

Unit tests import the checker by file path (it has no package); the repo smoke
runs it as a subprocess (matching the §12 acceptance runs and the sibling
test_check_import_boundaries.py / test_check_viz_api_schema.py convention).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
CHECKER = SCRIPTS_DIR / "check_directory_policy.py"
ALLOW = REPO_ROOT / "scripts" / "quality" / "check_directory_policy.allow.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("_dir_policy_checker", CHECKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def _write(base: Path, rel: str, text: str = "") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _valid_trio(base: Path) -> None:
    """Materialize a policy-legal config trio under ``base``."""
    _write(base, "ari-core/ari/config/finder.py", "x = 1\n")
    _write(base, "ari-core/ari/config/__init__.py", "y = 2\n")
    _write(base, "ari-core/ari/configs/_loader.py", "z = 3\n")
    _write(base, "ari-core/ari/configs/defaults.yaml", "a: 1\n")
    _write(base, "ari-core/ari/configs/model_prices.yaml", "b: 2\n")
    _write(base, "ari-core/config/default.yaml", "c: 3\n")
    _write(base, "ari-core/config/workflow.yaml", "d: 4\n")


def _raws_for(tree: Path):
    """Reproduce main()'s rule assembly against ``tree`` (returns RawFindings)."""
    rules = mod.load_config(mod.DEFAULT_CONFIG)
    files, from_git = mod.collect_files(tree, set(rules["walk_skip_dirs"]))
    dirs = mod.derive_dirs(files)
    raws = []
    raws += mod.check_config_trio(files, dirs, rules)
    raws += mod.check_storage_dirs(tree, rules)
    raws += mod.check_tracked_artifacts(files, from_git, rules)
    return raws


# ── Rule A — config trio + collisions ───────────────────────────────────────


def test_valid_trio_is_clean(tmp_path: Path) -> None:
    _valid_trio(tmp_path)
    raws = _raws_for(tmp_path)
    assert [r for r in raws if r.kind == "config-trio"] == []
    assert [r for r in raws if r.kind in ("banned-dir", "config-collision")] == []


def test_sonfigs_and_collision_fire_but_nonfamily_does_not(tmp_path: Path) -> None:
    _valid_trio(tmp_path)
    _write(tmp_path, "ari-core/sonfigs/x.yaml", "e: 1\n")       # banned-dir
    _write(tmp_path, "configs/y.yaml", "f: 2\n")                 # collision (root)
    (tmp_path / "ari-core" / "ari" / "config2").mkdir(parents=True)  # NOT family
    raws = _raws_for(tmp_path)
    banned = {r.file for r in raws if r.kind == "banned-dir"}
    collide = {r.file for r in raws if r.kind == "config-collision"}
    assert "ari-core/sonfigs" in banned
    assert "configs" in collide
    # config2 is not a config-family basename and must not be flagged.
    assert not any(r.file.endswith("config2") for r in raws)
    # The three canonical trio dirs are never a collision.
    assert "ari-core/ari/config" not in collide
    assert "ari-core/ari/configs" not in collide
    assert "ari-core/config" not in collide


def test_missing_marker_and_wrong_kind_fire(tmp_path: Path) -> None:
    # config dir with only a data file (no .py) -> trio-kind + trio-marker(s).
    _write(tmp_path, "ari-core/ari/config/default.yaml", "x: 1\n")
    _write(tmp_path, "ari-core/ari/configs/_loader.py", "z = 3\n")
    _write(tmp_path, "ari-core/ari/configs/defaults.yaml", "a: 1\n")
    _write(tmp_path, "ari-core/ari/configs/model_prices.yaml", "b: 2\n")
    _write(tmp_path, "ari-core/config/default.yaml", "c: 3\n")
    _write(tmp_path, "ari-core/config/workflow.yaml", "d: 4\n")
    raws = _raws_for(tmp_path)
    ids = {r.id for r in raws}
    assert "trio-kind:ari-core/ari/config" in ids           # wants .py, has none
    assert "trio-marker:ari-core/ari/config::finder.py" in ids
    assert "trio-marker:ari-core/ari/config::__init__.py" in ids


def test_missing_trio_dir_fires(tmp_path: Path) -> None:
    # Only two of three trio dirs present -> the third is trio-missing.
    _write(tmp_path, "ari-core/ari/config/finder.py", "x = 1\n")
    _write(tmp_path, "ari-core/ari/config/__init__.py", "y = 2\n")
    _write(tmp_path, "ari-core/ari/configs/_loader.py", "z = 3\n")
    _write(tmp_path, "ari-core/ari/configs/defaults.yaml", "a: 1\n")
    _write(tmp_path, "ari-core/ari/configs/model_prices.yaml", "b: 2\n")
    raws = _raws_for(tmp_path)
    assert "trio-missing:ari-core/config" in {r.id for r in raws}


# ── Rule B — storage-family top-level dirs ──────────────────────────────────


def test_new_storage_dir_warns_allowlisted_do_not(tmp_path: Path) -> None:
    _valid_trio(tmp_path)
    (tmp_path / "runs").mkdir()          # storage-family, NOT allowlisted -> warn
    (tmp_path / "checkpoints").mkdir()   # allowlisted -> no finding
    (tmp_path / "workspace").mkdir()     # allowlisted -> no finding
    (tmp_path / "containers").mkdir()    # not storage-family -> no finding
    raws = _raws_for(tmp_path)
    storage = {r.file: r.severity for r in raws if r.kind == "storage"}
    assert storage == {"runs": "warning"}


# ── Rule C — forbidden tracked artifacts (git-mode semantics) ───────────────


def test_tracked_artifacts_fire_via_git_universe() -> None:
    rules = mod.load_config(mod.DEFAULT_CONFIG)
    files = [
        "ari-core/ari/viz/frontend/node_modules/react/index.js",
        "ari-core/ari/foo.pyc",
        "ari-core/ari/real_code.py",       # clean
    ]
    raws = mod.check_tracked_artifacts(files, from_git=True, rules=rules)
    ids = {r.id for r in raws}
    # node_modules is collapsed to the dir root; the .pyc is a file-level hit.
    assert "artifact:ari-core/ari/viz/frontend/node_modules" in ids
    assert "artifact:ari-core/ari/foo.pyc" in ids
    assert all(r.severity == "error" for r in raws)
    # A clean tree yields nothing.
    assert mod.check_tracked_artifacts(["ari-core/ari/real_code.py"], True, rules) == []


# ── allowlist resolution ────────────────────────────────────────────────────


def test_allowlist_marks_known() -> None:
    raws = [
        mod.RawFinding("storage:runs", "warning", "runs", "storage", "msg"),
        mod.RawFinding("banned-dir:x/sonfigs", "error", "x/sonfigs", "banned-dir", "m"),
    ]
    findings = mod.to_findings(raws, allow_ids={"storage:runs"})
    by_id = {f.id: f for f in findings}
    assert by_id["storage:runs"].allowlisted is True
    assert by_id["banned-dir:x/sonfigs"].allowlisted is False


# ── repo smoke (real tree, subprocess) ──────────────────────────────────────


def _run(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_repo_smoke_is_clean() -> None:
    code, report = _run("--allow", str(ALLOW))
    assert report["summary"]["errors"] == 0, report["findings"]
    assert report["summary"]["new"] == 0, [
        f for f in report["findings"] if not f["allowlisted"]
    ]
    assert report["summary"]["total"] == 0
    assert code == 0


def test_repo_smoke_strict_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--strict", "--allow", str(ALLOW)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_repo_smoke_no_sonfigs_even_empty_allowlist() -> None:
    # The whole point of Rule A: `sonfigs/` stays absent. Empty allowlist, real tree.
    code, report = _run("--allow", "/dev/null")
    assert not any(f["kind"] == "banned-dir" for f in report["findings"])
    assert not any(f["kind"] == "config-collision" for f in report["findings"])
    assert report["summary"]["total"] == 0
    assert code == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
