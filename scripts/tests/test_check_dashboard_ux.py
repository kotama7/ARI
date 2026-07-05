#!/usr/bin/env python3
"""Unit + smoke tests for scripts/check_dashboard_ux.py.

Covers (subtask 073 §8 item 8 / §13):
  * i18n key extraction over the UNQUOTED-identifier React syntax
    (``nav_home: 'Home'``): keys captured, ``//``/header/brace/keyword lines
    ignored, duplicates caught — the gap ``check_i18n_js.py`` cannot cover
    (§13.6);
  * i18n parity union-diff: a synthetic locale missing a key -> finding; a
    locale in full parity -> none; a duplicate key -> finding;
  * raw-dump inventory: a synthetic ``dangerouslySetInnerHTML`` -> finding;
    ``JSON.stringify`` under ``components/`` -> finding but a benign
    ``JSON.stringify`` in ``services/`` (outside the json_dump scope) -> none;
  * route<->nav parity: synthetic PAGE_MAP / NAV_ITEMS extraction + hidden-route
    allowlist;
  * allowlist application: a baselined id reports ``allowlisted=True``;
  * repo smoke (§13.5): against the real tree the checker is clean-or-warning —
    with the seeded allowlist ZERO net-new findings (exit 0 under
    ``--fail-on-regression``) and i18n parity holds (0 i18n findings); with an
    empty allowlist the raw-dump baseline surfaces as ``new`` but the default
    posture still exits 0 (warning-mode-first).

Unit tests import the checker module by file path (it has no package); the repo
smoke runs it as a subprocess (matching the §12 manual acceptance runs and the
sibling test_check_viz_api_schema.py convention).
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
CHECKER = SCRIPTS_DIR / "check_dashboard_ux.py"
ALLOW = REPO_ROOT / "scripts" / "quality" / "check_dashboard_ux.allow.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("_dashboard_ux_checker", CHECKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ── (A) i18n key extraction ──────────────────────────────────────────────────


I18N_FIXTURE = """const en: Record<string, string> = {
  // Nav section comment
  nav_home: 'Home',
  nav_tree: 'Tree',
  /* block comment */
  * lingering star line
  settings_llm: "LLM Backend",
  'experiments.lineage': 'Lineage',
  wrapped_value:
    'a value that spilled onto the next line',
};

export default en;
"""


def test_i18n_keys_of_reads_unquoted_and_quoted_keys_and_skips_scaffolding() -> None:
    keys = mod.i18n_keys_of(I18N_FIXTURE)
    assert keys == ["nav_home", "nav_tree", "settings_llm",
                    "experiments.lineage", "wrapped_value"]
    # The header (const en:), comment lines, closing brace, and `export default`
    # must NOT be mistaken for keys.
    assert "const" not in keys
    assert "export" not in keys
    # Both a double-quoted VALUE (settings_llm) and a QUOTED KEY
    # ('experiments.lineage') are captured — the value-sensitive landing-JS probe
    # misses both classes, which is exactly the gap this checker fills.
    assert "settings_llm" in keys
    assert "experiments.lineage" in keys


def test_duplicates_detects_repeats_in_order() -> None:
    assert mod.duplicates(["a", "b", "a", "c", "b"]) == ["a", "b"]
    assert mod.duplicates(["a", "b", "c"]) == []


def _write_i18n(tmp_path: Path, contents: dict[str, str]) -> Path:
    d = tmp_path / "i18n"
    d.mkdir()
    for lang, body in contents.items():
        (d / f"{lang}.ts").write_text(body, encoding="utf-8")
    return d


def test_i18n_parity_clean_when_key_sets_match(tmp_path: Path) -> None:
    body = "const d: Record<string, string> = {\n  a: 'x',\n  b: 'y',\n};\n"
    d = _write_i18n(tmp_path, {"en": body, "ja": body, "zh": body})
    findings = mod.i18n_parity_findings(d, ("en", "ja", "zh"))
    assert findings == []


def test_i18n_parity_flags_missing_key(tmp_path: Path) -> None:
    full = "const d: Record<string, string> = {\n  a: 'x',\n  b: 'y',\n};\n"
    short = "const d: Record<string, string> = {\n  a: 'x',\n};\n"
    d = _write_i18n(tmp_path, {"en": full, "ja": short, "zh": full})
    findings = mod.i18n_parity_findings(d, ("en", "ja", "zh"))
    ids = {f.id for f in findings}
    assert "i18n:ja.ts:missing:b" in ids
    miss = next(f for f in findings if f.id == "i18n:ja.ts:missing:b")
    assert miss.kind == "i18n-missing-key"


def test_i18n_parity_flags_duplicate_key(tmp_path: Path) -> None:
    dup = "const d: Record<string, string> = {\n  a: 'x',\n  a: 'y',\n};\n"
    d = _write_i18n(tmp_path, {"en": dup, "ja": dup, "zh": dup})
    findings = mod.i18n_parity_findings(d, ("en", "ja", "zh"))
    assert any(f.kind == "i18n-duplicate" and f.id.endswith("duplicate:a")
               for f in findings)


# ── (B) raw-dump inventory ────────────────────────────────────────────────────


def _build_frontend(tmp_path: Path) -> Path:
    fe = tmp_path / "src"
    (fe / "components" / "Tree").mkdir(parents=True)
    (fe / "services").mkdir(parents=True)
    (fe / "components" / "Tree" / "DetailPanel.tsx").write_text(
        "export function P() {\n"
        "  return <div dangerouslySetInnerHTML={{ __html: h }} />;\n"
        "}\n"
        "const raw = JSON.stringify(node, null, 2);\n",
        encoding="utf-8",
    )
    # services/api.ts has a benign JSON.stringify (request body) that must NOT be
    # a json_dump finding (json_dump is scoped to components/).
    (fe / "services" / "api.ts").write_text(
        "export async function save(d) {\n"
        "  return post('/x', JSON.stringify(d));\n"
        "}\n",
        encoding="utf-8",
    )
    return fe


def test_raw_dump_flags_component_dumps_and_scopes_json_dump(tmp_path: Path) -> None:
    fe = _build_frontend(tmp_path)
    findings = mod.raw_dump_findings(fe, mod.DEFAULT_RAW_PATTERNS)
    ids = {f.id for f in findings}
    assert any("dangerous_html" in i and "DetailPanel.tsx" in i for i in ids)
    assert any("json_dump" in i and "DetailPanel.tsx" in i for i in ids)
    # The services/api.ts JSON.stringify is OUTSIDE the components/ json_dump
    # scope, so it must not appear as a json_dump finding.
    assert not any("json_dump" in i and "api.ts" in i for i in ids)


def test_raw_dump_ids_are_line_independent(tmp_path: Path) -> None:
    fe = _build_frontend(tmp_path)
    findings = mod.raw_dump_findings(fe, mod.DEFAULT_RAW_PATTERNS)
    for f in findings:
        assert f.id.count("::") == 1
        assert ":" not in f.id.split("::", 1)[1]  # no ":line" suffix in the id


# ── (C) route <-> nav parity ──────────────────────────────────────────────────


APP_FIXTURE = """const PAGE_MAP: Record<string, X> = {
  home: HomePage,
  tree: TreePage,
  new: WizardPage,
  wizard: WizardPage,
  'paperbench/import': PaperImportDialog,
  orphan_route: OrphanPage,
};
"""

SIDEBAR_FIXTURE = """const NAV_ITEMS: NavEntry[] = [
  { key: 'home', icon: 'H', labelKey: 'nav_home' },
  { key: 'tree', icon: 'T', labelKey: 'nav_tree' },
  { key: 'new', icon: 'N', labelKey: 'nav_new' },
];
"""


def test_page_map_and_nav_key_extraction() -> None:
    routes = mod.page_map_keys(APP_FIXTURE)
    assert routes == ["home", "tree", "new", "wizard", "paperbench/import",
                      "orphan_route"]
    nav = mod.nav_item_keys(SIDEBAR_FIXTURE)
    # labelKey values must NOT be captured as nav keys.
    assert nav == ["home", "tree", "new"]


def test_route_nav_flags_orphan_but_respects_hidden(tmp_path: Path) -> None:
    fe = tmp_path / "src"
    (fe / "components" / "Layout").mkdir(parents=True)
    (fe / "App.tsx").write_text(APP_FIXTURE, encoding="utf-8")
    (fe / "components" / "Layout" / "Sidebar.tsx").write_text(
        SIDEBAR_FIXTURE, encoding="utf-8")
    cfg = {
        "app_file": "App.tsx",
        "sidebar_file": "components/Layout/Sidebar.tsx",
        "hidden_routes": ["wizard", "paperbench/import"],
    }
    findings = mod.route_nav_findings(fe, cfg)
    ids = {f.id for f in findings}
    # orphan_route has no nav entry and is not hidden -> flagged.
    assert "route-nav:orphan_route" in ids
    # wizard + paperbench/import are hidden; home/tree/new have nav -> not flagged.
    assert "route-nav:wizard" not in ids
    assert "route-nav:paperbench/import" not in ids
    assert "route-nav:home" not in ids


# ── allowlist application ─────────────────────────────────────────────────────


def test_apply_allowlist_marks_known(tmp_path: Path) -> None:
    Finding = mod.Finding
    a = Finding(id="k1", severity="warning", file="f", line=1, kind="json_dump",
                message="m")
    b = Finding(id="k2", severity="warning", file="f", line=2, kind="json_dump",
                message="m")
    out = mod.apply_allowlist([a, b], {"k1"})
    by_id = {f.id: f for f in out}
    assert by_id["k1"].allowlisted is True
    assert by_id["k2"].allowlisted is False


# ── repo smoke (real tree) ────────────────────────────────────────────────────


def _run(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_repo_smoke_seeded_allowlist_is_clean() -> None:
    code, report = _run("--allow", str(ALLOW))
    s = report["summary"]
    assert s["new"] == 0, [f for f in report["findings"] if not f["allowlisted"]]
    # i18n key sets are in parity today -> zero i18n findings of any kind.
    assert not any(f["kind"].startswith("i18n") for f in report["findings"])
    # route<->nav is clean today (all routes covered or hidden).
    assert not any(f["kind"] == "route-nav-orphan" for f in report["findings"])
    # The known raw-dump baseline is present and fully allowlisted.
    assert s["total"] == s["known"] >= 11
    assert code == 0


def test_repo_smoke_fail_on_regression_passes_with_seed() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--fail-on-regression", "--allow", str(ALLOW)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_repo_smoke_empty_allowlist_surfaces_raw_baseline_but_exits_zero() -> None:
    code, report = _run("--allow", "/dev/null")
    raw_kinds = {"dangerous_html", "raw_json_tab", "env_secret_readback",
                 "confirm_bypass", "json_dump"}
    raw = [f for f in report["findings"] if f["kind"] in raw_kinds]
    assert len(raw) >= 11
    assert all(not f["allowlisted"] for f in raw)
    # i18n parity still clean even with no allowlist (nothing to baseline).
    assert not any(f["kind"].startswith("i18n") for f in report["findings"])
    assert code == 0  # default posture is warning-mode-first


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
