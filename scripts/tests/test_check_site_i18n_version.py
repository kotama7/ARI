"""Tests for the public-version-pin half of ``scripts/docs/check_site_i18n.py``.

The rest of that checker (surface parity, orphan t-ids, en->ja/zh co-change,
report-PDF sync) had no unit test either, but the version block is the part that
was just extended from "version.json equals report/en's \\date" to a rule
spanning six files plus an ordering constraint against the package version --
89 lines whose only enforcement was one CI step. A gate nothing exercises is
indistinguishable from a gate that cannot fail, so these tests construct the
drift each assertion exists to catch and check that it is actually caught.

Every case repoints the module's ``REPO_ROOT`` / ``DOCS`` at a temp tree; the
real repository is never written. Deterministic, no network, no LLM (P2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DOCS = Path(__file__).resolve().parents[1] / "docs"
if str(SCRIPTS_DOCS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DOCS))

import check_site_i18n as csi  # noqa: E402


# ── pure helpers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("v0.9.0", (0, 9, 0)),
    ("0.9.1", (0, 9, 1)),
    ("  v1.2.3  ", (1, 2, 3)),
    ("0.10.0rc1", None),      # pin must be a bare vX.Y.Z
    ("0.9", None),
    ("garbage", None),
])
def test_semver_is_strict(value, expected):
    assert csi.semver(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("v0.9.0", (0, 9, 0, 1)),
    ("0.9.1", (0, 9, 1, 1)),
    ("0.10.0rc1", (0, 10, 0, 0)),     # pre-release: sorts before its final
    ("0.9.1.dev0", (0, 9, 1, 0)),
    ("0.9", None),
    ("garbage", None),
])
def test_release_order_tolerates_prerelease(value, expected):
    assert csi.release_order(value) == expected


def test_prerelease_sorts_before_its_own_final():
    # The point of the fourth tuple element: a pin of v0.10.0 against a packaged
    # 0.10.0rc1 IS the pin leading the package -- the final was never packaged.
    assert csi.release_order("v0.10.0") > csi.release_order("0.10.0rc1")
    assert csi.release_order("v0.9.0") < csi.release_order("0.9.1")


# ── fixture tree ─────────────────────────────────────────────────────────────

def _tree(root: Path, *, pin: str, pkg: str,
          badges: dict[str, str] | None = None,
          dates: dict[str, str] | None = None) -> None:
    """Minimal repo shape: version.json, three READMEs, three report main.tex."""
    badges = badges if badges is not None else {r: pin for r in csi.README_FILES}
    dates = dates if dates is not None else {lang: pin for lang in csi.REPORT_LANGS}

    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "version.json").write_text(
        json.dumps({"version": pin}), encoding="utf-8")

    (root / "ari-core").mkdir(parents=True, exist_ok=True)
    (root / "ari-core" / "pyproject.toml").write_text(
        f'[project]\nname = "ari-core"\nversion = "{pkg}"\n', encoding="utf-8")

    for readme, badge in badges.items():
        body = "" if badge is None else (
            f"[![Version](https://img.shields.io/badge/version-{badge}-orange)]"
            "(https://example.invalid/releases)\n")
        (root / readme).write_text(f"# t\n\n{body}", encoding="utf-8")

    for lang, date in dates.items():
        d = root / "report" / lang
        d.mkdir(parents=True, exist_ok=True)
        body = "" if date is None else (
            "\\date{" + date + ", edition, 2026-01-01}\n")
        (d / "main.tex").write_text("\\documentclass{article}\n" + body,
                                    encoding="utf-8")


def _version_errors(monkeypatch, tmp_path: Path, **kw) -> list[str]:
    """Run ONLY the version block against a scratch tree; return its errors."""
    _tree(tmp_path, **kw)
    monkeypatch.setattr(csi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(csi, "DOCS", tmp_path / "docs")
    errors: list[str] = []
    warnings: list[str] = []
    csi.check_version_pin(errors, warnings)
    return [e for e in errors if e.startswith("[version]")]


# ── the rule each assertion exists to enforce ────────────────────────────────

def test_consistent_surface_is_clean(monkeypatch, tmp_path):
    assert _version_errors(monkeypatch, tmp_path, pin="v0.9.0", pkg="0.9.0") == []


def test_pin_may_lag_the_package(monkeypatch, tmp_path):
    # The live state: a package-only bump ships no public-surface change.
    assert _version_errors(monkeypatch, tmp_path, pin="v0.9.0", pkg="0.9.1") == []


def test_pin_may_not_lead_the_package(monkeypatch, tmp_path):
    errs = _version_errors(monkeypatch, tmp_path, pin="v0.9.9", pkg="0.9.1")
    assert len(errs) == 1 and "leads" in errs[0]


def test_pin_leading_a_prerelease_package_is_caught(monkeypatch, tmp_path):
    errs = _version_errors(monkeypatch, tmp_path, pin="v0.10.0", pkg="0.10.0rc1")
    assert len(errs) == 1 and "leads" in errs[0]


def test_prerelease_package_behind_the_pin_is_not_an_error(monkeypatch, tmp_path):
    # Regression guard: requiring a bare X.Y.Z from pyproject failed the whole
    # gate on any release candidate, which would have blocked every PR during
    # an rc. Lagging is legal, and an rc is legal.
    assert _version_errors(monkeypatch, tmp_path, pin="v0.9.0", pkg="0.10.0rc1") == []


def test_unparseable_package_version_warns_rather_than_errors(monkeypatch, tmp_path):
    _tree(tmp_path, pin="v0.9.0", pkg="not-a-version")
    monkeypatch.setattr(csi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(csi, "DOCS", tmp_path / "docs")
    errors: list[str] = []
    warnings: list[str] = []
    csi.check_version_pin(errors, warnings)
    assert [e for e in errors if e.startswith("[version]")] == []
    assert any("pin ordering not checked" in w for w in warnings)


@pytest.mark.parametrize("readme", ["README.md", "README.ja.md", "README.zh.md"])
def test_each_readme_badge_is_bound(monkeypatch, tmp_path, readme):
    badges = {r: "v0.9.0" for r in csi.README_FILES}
    badges[readme] = "v0.8.1"
    errs = _version_errors(monkeypatch, tmp_path,
                           pin="v0.9.0", pkg="0.9.1", badges=badges)
    assert len(errs) == 1 and readme in errs[0]


@pytest.mark.parametrize("readme", ["README.md", "README.ja.md", "README.zh.md"])
def test_missing_readme_badge_is_an_error(monkeypatch, tmp_path, readme):
    badges = {r: "v0.9.0" for r in csi.README_FILES}
    badges[readme] = None
    errs = _version_errors(monkeypatch, tmp_path,
                           pin="v0.9.0", pkg="0.9.1", badges=badges)
    assert len(errs) == 1 and readme in errs[0] and "no shields.io" in errs[0]


@pytest.mark.parametrize("lang", ["en", "ja", "zh"])
def test_each_report_date_is_bound(monkeypatch, tmp_path, lang):
    # ja and zh used to be bound by nothing: check_site_i18n read report/en only.
    dates = {x: "v0.9.0" for x in csi.REPORT_LANGS}
    dates[lang] = "v0.8.1"
    errs = _version_errors(monkeypatch, tmp_path,
                           pin="v0.9.0", pkg="0.9.1", dates=dates)
    assert len(errs) == 1 and f"report/{lang}" in errs[0]


@pytest.mark.parametrize("lang", ["en", "ja", "zh"])
def test_missing_report_date_is_an_error(monkeypatch, tmp_path, lang):
    dates = {x: "v0.9.0" for x in csi.REPORT_LANGS}
    dates[lang] = None
    errs = _version_errors(monkeypatch, tmp_path,
                           pin="v0.9.0", pkg="0.9.1", dates=dates)
    assert len(errs) == 1 and f"report/{lang}" in errs[0]


def test_missing_version_json_is_an_error(monkeypatch, tmp_path):
    _tree(tmp_path, pin="v0.9.0", pkg="0.9.1")
    (tmp_path / "docs" / "version.json").unlink()
    monkeypatch.setattr(csi, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(csi, "DOCS", tmp_path / "docs")
    errors: list[str] = []
    csi.check_version_pin(errors, [])
    assert any("version.json missing" in e for e in errors)


def test_non_semver_pin_is_an_error(monkeypatch, tmp_path):
    # The badge and \date regexes require a bare vX.Y.Z, so a pin that is not one
    # cannot match them either -- strict here is right.
    errs = _version_errors(monkeypatch, tmp_path, pin="0.9.0rc1", pkg="0.9.1")
    assert any("not a vX.Y.Z" in e for e in errs)


# ── the real repository ──────────────────────────────────────────────────────

def test_repo_version_surface_is_consistent():
    errors: list[str] = []
    csi.check_version_pin(errors, [])
    assert [e for e in errors if e.startswith("[version]")] == []
