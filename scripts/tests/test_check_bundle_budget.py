#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_bundle_budget.py (gui_refresh Wave 5b).

Covers:
  * chunk-stem extraction over Vite's ``<stem>-<8-char hash>.js`` naming,
    including hashes that themselves contain ``-`` (StatusBadge-D-8zhWMR.js);
  * entry identification from ``dist/index.html`` module-script references and
    entry/route/shared classification (route = ``<Name>Page`` stems);
  * budget evaluation against a tmp fake dist: an oversized route chunk under
    a tiny budget config -> ``route-over-budget`` finding + exit 1 under
    ``--fail-on-regression``; within-budget -> zero findings + exit 0; the
    per-route override (SettingsPage/WizardPage 50 KiB) tighter than the
    generic route budget; total aggregate -> ``total-over-budget``;
  * gzip determinism (mtime=0): identical content measures identical bytes
    across calls;
  * missing dist -> exit 2 (environment error, not a budget regression);
  * real-dist smoke (skipped with a clear message when the frontend build is
    absent): the committed build passes every plan-09 budget — exit 0 under
    ``--fail-on-regression``, entry <= 100 KiB gzip, total <= 600 KiB gzip.

Unit tests import the checker module by file path (it has no package); smoke
runs it as a subprocess (sibling test_check_dashboard_ux.py convention).
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
CHECKER = SCRIPTS_DIR / "check_bundle_budget.py"
REAL_DIST = REPO_ROOT / "ari-core" / "ari" / "viz" / "static" / "dist"


def _load_module():
    spec = importlib.util.spec_from_file_location("_bundle_budget_checker", CHECKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ── stem extraction / classification ─────────────────────────────────────────


def test_chunk_stem_strips_vite_hash_even_with_dash_in_hash() -> None:
    assert mod.chunk_stem("index-XMaqroN9.js") == "index"
    assert mod.chunk_stem("WorkflowPage-Dtyb4rJS.js") == "WorkflowPage"
    # The 8-char hash may contain '-' — the stem must not be truncated to
    # "StatusBadge-D" nor extended past the real stem.
    assert mod.chunk_stem("StatusBadge-D-8zhWMR.js") == "StatusBadge"
    assert mod.chunk_stem("treeNodes-D2HIDY-T.js") == "treeNodes"
    # Unhashed name falls back to basename sans .js.
    assert mod.chunk_stem("vendor.js") == "vendor"


def test_classify_entry_route_shared() -> None:
    import re
    route_re = re.compile(mod.DEFAULT_ROUTE_RE)
    entries = {"index-XMaqroN9.js"}
    assert mod.classify("index-XMaqroN9.js", entries, route_re) == "entry"
    assert mod.classify("SettingsPage-BTUoy9ST.js", entries, route_re) == "route"
    # zoom/locale/component splits are shared, not routes.
    assert mod.classify("zoom-CF9eoj1R.js", entries, route_re) == "shared"
    assert mod.classify("ja-D0gEtz8g.js", entries, route_re) == "shared"


def test_budget_for_route_override_beats_generic_route_budget() -> None:
    budgets = {"entry_kib": 100, "route_kib": 150, "shared_kib": 150,
               "route_overrides": {"SettingsPage": 50}}
    assert mod.budget_kib_for("route", "SettingsPage", budgets) == 50
    assert mod.budget_kib_for("route", "HomePage", budgets) == 150
    assert mod.budget_kib_for("entry", "index", budgets) == 100
    assert mod.budget_kib_for("shared", "zoom", budgets) == 150


# ── fake dist fixtures ───────────────────────────────────────────────────────


def _make_dist(tmp_path: Path, chunks: dict[str, bytes],
               entry: str = "index-AAAA1111.js") -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    dist.joinpath("index.html").write_text(
        "<!DOCTYPE html><html><head>\n"
        f'<script type="module" crossorigin '
        f'src="/static/dist/assets/{entry}"></script>\n'
        "</head><body></body></html>\n", encoding="utf-8")
    for name, body in chunks.items():
        (dist / "assets" / name).write_bytes(body)
    return dist


def _incompressible(n: int) -> bytes:
    """Seeded pseudo-random payload: incompressible (gzip ~= n) yet reproducible."""
    import random
    rng = random.Random(42)  # seeded -> reproducible test data
    return bytes(rng.getrandbits(8) for _ in range(n))


def _write_cfg(tmp_path: Path, dist: Path, budgets: dict) -> Path:
    import yaml
    cfg = tmp_path / "budget.yaml"
    cfg.write_text(yaml.safe_dump({"dist": str(dist), "budgets": budgets}),
                   encoding="utf-8")
    return cfg


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT))


# ── budget evaluation (fake dist) ────────────────────────────────────────────


def test_fake_dist_within_budget_is_clean(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path, {
        "index-AAAA1111.js": b"console.log('entry');" * 10,
        "HomePage-BBBB2222.js": b"export default 1;" * 10,
        "zoom-CCCC3333.js": b"export const z = 1;" * 10,
    })
    cfg = _write_cfg(tmp_path, dist, {"entry_kib": 100, "route_kib": 150,
                                      "shared_kib": 150, "total_kib": 600})
    proc = _run("--config", str(cfg), "--fail-on-regression")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["checker"] == "check_bundle_budget"
    assert report["summary"]["new"] == 0
    assert report["summary"]["chunk_count"] == 3
    classes = {c["name"]: c["class"] for c in report["summary"]["chunks"]}
    assert classes["index-AAAA1111.js"] == "entry"
    assert classes["HomePage-BBBB2222.js"] == "route"
    assert classes["zoom-CCCC3333.js"] == "shared"


def test_fake_dist_oversized_route_chunk_fails_regression(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path, {
        "index-AAAA1111.js": b"console.log('entry');",
        # ~3 KiB incompressible -> over a 1 KiB route budget.
        "HomePage-BBBB2222.js": _incompressible(3 * 1024),
    })
    cfg = _write_cfg(tmp_path, dist, {"entry_kib": 100, "route_kib": 1,
                                      "shared_kib": 150, "total_kib": 600})
    proc = _run("--config", str(cfg), "--fail-on-regression")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    ids = {f["id"]: f for f in report["findings"]}
    # Hash-independent finding id (survives rebuilds).
    assert "bundle:route:HomePage" in ids
    assert ids["bundle:route:HomePage"]["kind"] == "route-over-budget"
    assert not ids["bundle:route:HomePage"]["allowlisted"]


def test_fake_dist_route_override_tighter_than_generic(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path, {
        "index-AAAA1111.js": b"console.log('entry');",
        # ~3 KiB: within the generic 150 KiB route budget but over a 2 KiB
        # SettingsPage override.
        "SettingsPage-BBBB2222.js": _incompressible(3 * 1024),
        "HomePage-CCCC3333.js": _incompressible(3 * 1024),
    })
    cfg = _write_cfg(tmp_path, dist, {
        "entry_kib": 100, "route_kib": 150, "shared_kib": 150, "total_kib": 600,
        "route_overrides": {"SettingsPage": 2}})
    proc = _run("--config", str(cfg), "--fail-on-regression")
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    ids = {f["id"] for f in report["findings"]}
    assert "bundle:route:SettingsPage" in ids
    assert "bundle:route:HomePage" not in ids  # generic budget still passes


def test_fake_dist_total_budget_aggregate(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path, {
        "index-AAAA1111.js": _incompressible(3 * 1024),
        "HomePage-BBBB2222.js": _incompressible(3 * 1024),
    })
    # Each chunk within its per-chunk budget (100/150) but the ~6 KiB total
    # exceeds a 4 KiB aggregate ceiling.
    cfg = _write_cfg(tmp_path, dist, {"entry_kib": 100, "route_kib": 150,
                                      "shared_kib": 150, "total_kib": 4})
    proc = _run("--config", str(cfg), "--fail-on-regression")
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    ids = {f["id"]: f for f in report["findings"]}
    assert set(ids) == {"bundle:total:js"}
    assert ids["bundle:total:js"]["kind"] == "total-over-budget"


def test_gzip_measurement_is_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "a.js"
    p.write_bytes(b"const x = 1;\n" * 100)
    first = mod.gzip_size(p)
    # mtime=0 in gzip.compress -> byte-identical header across calls/clock.
    assert mod.gzip_size(p) == first
    assert first > 0


def test_missing_dist_exits_2(tmp_path: Path) -> None:
    proc = _run("--dist", str(tmp_path / "nope"))
    assert proc.returncode == 2
    assert "assets dir not found" in proc.stderr


# ── real dist smoke ──────────────────────────────────────────────────────────


needs_dist = pytest.mark.skipif(
    not (REAL_DIST / "assets").is_dir(),
    reason=("frontend dist not built at ari-core/ari/viz/static/dist — run "
            "`npm run build` in ari-core/ari/viz/frontend to enable the "
            "bundle-budget smoke"))


@needs_dist
def test_repo_smoke_real_dist_within_all_budgets() -> None:
    proc = _run("--fail-on-regression")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    s = report["summary"]
    assert s["new"] == 0 and s["total"] == 0
    assert s["chunk_count"] > 0
    # Plan-09 hard budgets hold on the committed build.
    entry = [c for c in s["chunks"] if c["class"] == "entry"]
    assert entry, "index.html must reference a module entry chunk"
    assert all(c["gzip_bytes"] <= 100 * 1024 for c in entry)
    assert s["total_js_gzip_bytes"] <= 600 * 1024
    # Settings/Wizard tightened rows hold too.
    for c in s["chunks"]:
        if c["stem"] in ("SettingsPage", "WizardPage"):
            assert c["gzip_bytes"] <= 50 * 1024


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
