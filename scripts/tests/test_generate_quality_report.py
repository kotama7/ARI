#!/usr/bin/env python3
"""Unit + smoke tests for scripts/generate_quality_report.py.

Covers subtask 031 §8 item 5 / §13 acceptance criteria:
  * zero-checker run yields a valid, well-formed report (graceful degradation);
  * --target ingestion of synthetic per-checker JSON — valid merges, a missing
    file becomes ``unavailable``, malformed JSON and an unknown schema version
    become ``error``, and nothing ever raises;
  * --format json round-trips the stable roll-up schema and it is re-ingestible
    as a --baseline;
  * --baseline produces a correct "new since baseline" delta; --fail-on-regression
    exits 1 only on net-new findings; --warning-only forces exit 0;
  * --run-checkers subprocess mode: a fixture checker -> ok, a missing script ->
    unavailable, a crashing script -> error;
  * per-area LOC reproduces docs/refactoring/reports/001_complexity_baseline.md
    (viz 8131, public 148) and findings attribute to their area.

Unit tests import the checker module by file path (it has no package), matching
the sibling test_check_viz_api_schema.py convention.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
SCRIPT = SCRIPTS_DIR / "generate_quality_report.py"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "quality" / "generate_quality_report.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("_quality_report_agg", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def _envelope(checker, findings, *, version=1, summary=None):
    return {
        "checker": checker,
        "version": version,
        "target": "ari-core/ari",
        "summary": summary or {"total": len(findings)},
        "findings": findings,
    }


def _finding(fid, *, file="ari-core/ari/x.py", allowlisted=False, severity="error"):
    return {
        "id": fid,
        "severity": severity,
        "file": file,
        "line": 1,
        "kind": "demo",
        "message": f"demo finding {fid}",
        "allowlisted": allowlisted,
    }


def _write_config(tmp_path, checkers):
    cfg = tmp_path / "cfg.yaml"
    import yaml

    cfg.write_text(yaml.safe_dump({"checkers": checkers}), encoding="utf-8")
    return cfg


def _run(argv):
    """Run main() in-process, returning (exit_code, parsed-or-text)."""
    return mod.main(argv)


# ── zero-checker graceful path ───────────────────────────────────────────────


def test_zero_checkers_yields_valid_report(tmp_path):
    cfg = _write_config(tmp_path, [])
    out = tmp_path / "r.json"
    code = _run(["--config", str(cfg), "--format", "json", "--output", str(out)])
    assert code == 0
    model = json.loads(out.read_text(encoding="utf-8"))
    assert model["report"] == "quality"
    assert model["version"] == 1
    assert isinstance(model["generated_at"], str) and model["generated_at"].endswith("Z")
    assert model["checkers"] == []
    assert model["totals"] == {
        "checkers_run": 0,
        "checkers_unavailable": 0,
        "findings": 0,
        "new_vs_baseline": 0,
    }
    # areas are still computed (self-walk) even with zero checkers.
    assert any(a["area"] == "ari-core/ari/viz" for a in model["areas"])


def test_bare_run_default_config_is_graceful(tmp_path):
    # No --target and no --run-checkers => every configured checker is unavailable,
    # but the run still succeeds and emits a valid markdown report (AC#2).
    out = tmp_path / "r.md"
    code = _run(["--format", "markdown", "--output", str(out)])
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Quality Report")
    assert "## Checkers" in text and "## Areas" in text
    # default config lists checkers; with no input all are unavailable.
    assert "unavailable" in text


# ── --target ingestion + degradation ─────────────────────────────────────────


def test_target_mode_valid_missing_malformed_unknown_version(tmp_path):
    td = tmp_path / "jsons"
    td.mkdir()
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("f1"), _finding("f2", allowlisted=True)])),
        encoding="utf-8",
    )
    (td / "check_bad.json").write_text("{not json", encoding="utf-8")
    (td / "check_old.json").write_text(
        json.dumps(_envelope("check_old", [_finding("z")], version=99)), encoding="utf-8"
    )
    # check_missing has no file at all.
    cfg = _write_config(
        tmp_path,
        [
            {"name": "check_ok", "module_or_path": "x"},
            {"name": "check_bad", "module_or_path": "x"},
            {"name": "check_old", "module_or_path": "x"},
            {"name": "check_missing", "module_or_path": "x"},
        ],
    )
    out = tmp_path / "r.json"
    code = _run(["--config", str(cfg), "--target", str(td), "--json", "--output", str(out)])
    assert code == 0
    model = json.loads(out.read_text(encoding="utf-8"))
    by = {c["checker"]: c for c in model["checkers"]}
    assert by["check_ok"]["status"] == "ok"
    assert by["check_ok"]["finding_count"] == 2
    assert by["check_ok"]["allowlisted_count"] == 1
    assert by["check_bad"]["status"] == "error"
    assert by["check_old"]["status"] == "error" and "v99" in by["check_old"]["reason"]
    assert by["check_missing"]["status"] == "unavailable"
    assert model["totals"]["checkers_run"] == 1
    assert model["totals"]["checkers_unavailable"] == 3
    assert model["totals"]["findings"] == 2


def test_target_not_a_dir_is_exit_2(tmp_path):
    cfg = _write_config(tmp_path, [])
    with pytest.raises(SystemExit) as exc:
        _run(["--config", str(cfg), "--target", str(tmp_path / "nope")])
    assert exc.value.code == 2


def test_explicit_missing_config_is_exit_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _run(["--config", str(tmp_path / "absent.yaml"), "--json"])
    assert exc.value.code == 2


# ── round-trip + regression / baseline ───────────────────────────────────────


def test_json_roundtrip_and_baseline_delta(tmp_path):
    td = tmp_path / "jsons"
    td.mkdir()
    # baseline snapshot: one finding.
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("f1")])), encoding="utf-8"
    )
    cfg = _write_config(tmp_path, [{"name": "check_ok", "module_or_path": "x"}])
    base = tmp_path / "base.json"
    assert _run(["--config", str(cfg), "--target", str(td), "--json", "--output", str(base)]) == 0
    base_model = json.loads(base.read_text(encoding="utf-8"))
    # roll-up is itself a valid baseline input (embeds findings).
    assert base_model["checkers"][0]["findings"][0]["id"] == "f1"

    # now the checker reports f1 (known) + f2 (new).
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("f1"), _finding("f2")])), encoding="utf-8"
    )
    cur = tmp_path / "cur.json"
    code = _run(
        ["--config", str(cfg), "--target", str(td), "--baseline", str(base),
         "--json", "--output", str(cur)]
    )
    assert code == 0  # default posture never blocks
    cur_model = json.loads(cur.read_text(encoding="utf-8"))
    assert cur_model["totals"]["new_vs_baseline"] == 1
    nf = cur_model["regression"]["new_findings"]
    assert len(nf) == 1 and nf[0]["id"] == "f2" and nf[0]["checker"] == "check_ok"
    assert cur_model["regression"]["baseline"] == str(base)


def test_fail_on_regression_and_warning_only(tmp_path):
    td = tmp_path / "jsons"
    td.mkdir()
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("f1")])), encoding="utf-8"
    )
    cfg = _write_config(tmp_path, [{"name": "check_ok", "module_or_path": "x"}])
    base = tmp_path / "base.json"
    _run(["--config", str(cfg), "--target", str(td), "--json", "--output", str(base)])

    # add a net-new finding -> regression.
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("f1"), _finding("f2")])), encoding="utf-8"
    )
    out = tmp_path / "o.json"
    assert _run(
        ["--config", str(cfg), "--target", str(td), "--baseline", str(base),
         "--fail-on-regression", "--json", "--output", str(out)]
    ) == 1
    # --warning-only overrides fail-on-regression.
    assert _run(
        ["--config", str(cfg), "--target", str(td), "--baseline", str(base),
         "--fail-on-regression", "--warning-only", "--json", "--output", str(out)]
    ) == 0
    # no baseline => nothing to regress against => exit 0.
    assert _run(
        ["--config", str(cfg), "--target", str(td), "--fail-on-regression",
         "--json", "--output", str(out)]
    ) == 0


def test_allowlisted_finding_is_not_net_new(tmp_path):
    td = tmp_path / "jsons"
    td.mkdir()
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [])), encoding="utf-8"
    )
    cfg = _write_config(tmp_path, [{"name": "check_ok", "module_or_path": "x"}])
    base = tmp_path / "base.json"
    _run(["--config", str(cfg), "--target", str(td), "--json", "--output", str(base)])
    # a new BUT allowlisted finding must not count as regression.
    (td / "check_ok.json").write_text(
        json.dumps(_envelope("check_ok", [_finding("k", allowlisted=True)])), encoding="utf-8"
    )
    out = tmp_path / "o.json"
    code = _run(
        ["--config", str(cfg), "--target", str(td), "--baseline", str(base),
         "--fail-on-regression", "--json", "--output", str(out)]
    )
    assert code == 0
    model = json.loads(out.read_text(encoding="utf-8"))
    assert model["totals"]["new_vs_baseline"] == 0


# ── --run-checkers subprocess mode ────────────────────────────────────────────


def test_run_checkers_mode_ok_missing_and_crash(tmp_path):
    good = tmp_path / "good_checker.py"
    good.write_text(
        "import json,sys\n"
        "print(json.dumps({'checker':'good','version':1,'target':'.',"
        "'summary':{'total':1},'findings':[{'id':'g1','severity':'warning',"
        "'file':'ari-core/ari/llm/client.py','line':2,'kind':'k','message':'m',"
        "'allowlisted':False}]}))\n",
        encoding="utf-8",
    )
    crash = tmp_path / "crash_checker.py"
    crash.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    # paths in config are repo-relative; use paths relative to REPO_ROOT.
    good_rel = good.relative_to(REPO_ROOT).as_posix() if good.is_relative_to(REPO_ROOT) \
        else str(good)
    crash_rel = crash.relative_to(REPO_ROOT).as_posix() if crash.is_relative_to(REPO_ROOT) \
        else str(crash)
    cfg = _write_config(
        tmp_path,
        [
            {"name": "good", "module_or_path": good_rel},
            {"name": "gone", "module_or_path": "scripts/does_not_exist_zzz.py"},
            {"name": "crash", "module_or_path": crash_rel},
        ],
    )
    out = tmp_path / "r.json"
    code = _run(["--config", str(cfg), "--run-checkers", "--json", "--output", str(out)])
    assert code == 0
    by = {c["checker"]: c for c in json.loads(out.read_text(encoding="utf-8"))["checkers"]}
    assert by["good"]["status"] == "ok" and by["good"]["finding_count"] == 1
    assert by["gone"]["status"] == "unavailable"
    assert by["crash"]["status"] == "error"


# tmp_path under /tmp is not relative to REPO_ROOT; collect_by_running resolves
# REPO_ROOT / path. Guard: if the fixture path is absolute the join still works
# because Path(abs) wins in a / join, so the above test is robust either way.


# ── per-area LOC (matches 001) + attribution ─────────────────────────────────


def test_compute_areas_matches_001_baseline():
    rows = mod.compute_areas(REPO_ROOT, None, [])
    by = {r["area"]: r for r in rows}
    assert by["ari-core/ari/viz"]["loc"] == 8131
    assert by["ari-core/ari/public"]["loc"] == 148
    # every discovered area carries a finding_count key (0 with no results).
    assert all(r["finding_count"] == 0 for r in rows)


def test_finding_attributes_to_area():
    res = mod.CheckerResult(
        "c", "ok",
        findings=[_finding("v", file="ari-core/ari/viz/routes.py")],
    )
    rows = mod.compute_areas(REPO_ROOT, None, [res])
    by = {r["area"]: r for r in rows}
    assert by["ari-core/ari/viz"]["finding_count"] == 1
    assert by["ari-core/ari/public"]["finding_count"] == 0


def test_finding_attribution_prefers_longest_area():
    # a finding under ari-core/ari/viz must not be attributed to ari-core/ari.
    res = mod.CheckerResult(
        "c", "ok", findings=[_finding("v", file="ari-core/ari/viz/api_state.py")]
    )
    rows = mod.compute_areas(REPO_ROOT, ["ari-core/ari", "ari-core/ari/viz"], [res])
    by = {r["area"]: r for r in rows}
    assert by["ari-core/ari/viz"]["finding_count"] == 1
    assert by["ari-core/ari"]["finding_count"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
