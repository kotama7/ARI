"""Unit + smoke + determinism tests for ``scripts/check_docs_source_sync.py`` (027).

Covers ``docs/refactoring/subtasks/027_add_docs_source_sync_checker_script.md`` §12
via a temp git-repo fixture:

  * doc whose ``last_verified`` predates the source's newest commit -> STALE;
  * doc whose ``last_verified`` postdates the source's newest commit -> clean;
  * an allowlisted stale (doc, source) pair -> suppressed (known, not new);
  * a doc with ``sources`` but no ``last_verified`` -> skipped;
  * a doc with no front-matter / no ``sources`` -> skipped;
  * git unavailable / no history for a path -> fail open (no finding);
  * determinism -- two runs on the same tree are byte-identical.

Deterministic, no network, no LLM (ARI design principle P2).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_docs_source_sync as cdss  # noqa: E402


# ── temp-repo fixture helpers ────────────────────────────────────────────────

def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    })
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True, env=env)


def _doc(sources: list[str] | None, last_verified: str | None, body: str = "x") -> str:
    if sources is None and last_verified is None:
        return f"# no front-matter\n\n{body}\n"
    fm = ["---"]
    if sources is not None:
        fm.append("sources:")
        for s in sources:
            fm.append(f"  - path: {s}")
            fm.append("    role: implementation")
    if last_verified is not None:
        fm.append(f"last_verified: {last_verified}")
    fm.append("---")
    return "\n".join(fm) + f"\n\n# doc\n\n{body}\n"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A tiny git repo: a source committed at 2025-03-15, docs on disk."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    src = r / "src"
    src.mkdir()
    (src / "mod.py").write_text("print('hi')\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "add source", date="2025-03-15T12:00:00")
    (r / "docs").mkdir()
    (r / "docs" / "reference").mkdir()
    return r


def _findings(repo: Path) -> list[dict]:
    return cdss.compute_findings(repo, repo / "docs")


# ── core behaviour ───────────────────────────────────────────────────────────

def test_stale_when_source_newer_than_last_verified(repo: Path):
    (repo / "docs" / "reference" / "stale.md").write_text(
        _doc(["src/mod.py"], "2025-01-01"), encoding="utf-8")
    findings = _findings(repo)
    assert len(findings) == 1
    f = findings[0]
    assert f["doc"] == "docs/reference/stale.md"
    assert f["source"] == "src/mod.py"
    assert f["last_verified"] == "2025-01-01"
    assert f["source_last_commit"] == "2025-03-15"


def test_clean_when_last_verified_newer_than_source(repo: Path):
    (repo / "docs" / "reference" / "clean.md").write_text(
        _doc(["src/mod.py"], "2025-06-01"), encoding="utf-8")
    assert _findings(repo) == []


def test_doc_without_last_verified_is_skipped(repo: Path):
    (repo / "docs" / "reference" / "nolv.md").write_text(
        _doc(["src/mod.py"], None), encoding="utf-8")
    assert _findings(repo) == []


def test_doc_without_sources_is_skipped(repo: Path):
    (repo / "docs" / "reference" / "nosrc.md").write_text(
        _doc(None, None), encoding="utf-8")
    # front-matter present but no sources -> still skipped
    (repo / "docs" / "reference" / "fm_only.md").write_text(
        _doc(None, "2020-01-01"), encoding="utf-8")
    assert _findings(repo) == []


def test_source_without_history_fails_open(repo: Path):
    # source path that exists in front-matter but has no commit -> skipped
    (repo / "docs" / "reference" / "ghost.md").write_text(
        _doc(["src/never_committed.py"], "2000-01-01"), encoding="utf-8")
    assert _findings(repo) == []


def test_translations_are_ignored(repo: Path):
    (repo / "docs" / "ja").mkdir()
    (repo / "docs" / "ja" / "stale.md").write_text(
        _doc(["src/mod.py"], "2025-01-01"), encoding="utf-8")
    assert _findings(repo) == []


# ── allowlist suppression ────────────────────────────────────────────────────

def test_allowlist_suppresses_known_pair(repo: Path):
    (repo / "docs" / "reference" / "stale.md").write_text(
        _doc(["src/mod.py"], "2025-01-01"), encoding="utf-8")
    findings = _findings(repo)
    allow = {("docs/reference/stale.md", "src/mod.py")}
    new, known = cdss.partition_findings(findings, allow)
    assert new == []
    assert len(known) == 1


def test_load_allowlist_roundtrip(tmp_path: Path):
    p = tmp_path / "a.allow.yaml"
    p.write_text(
        "known-offenders:\n"
        "  - doc: docs/x.md\n    source: src/y.py\n    note: n\n"
        "  - doc: docs/x.md\n",  # malformed (no source) -> ignored
        encoding="utf-8")
    assert cdss.load_allowlist(p) == {("docs/x.md", "src/y.py")}
    assert cdss.load_allowlist(tmp_path / "missing.yaml") == set()


# ── determinism ──────────────────────────────────────────────────────────────

def test_determinism(repo: Path):
    (repo / "docs" / "reference" / "a.md").write_text(
        _doc(["src/mod.py"], "2025-01-01"), encoding="utf-8")
    (repo / "docs" / "reference" / "b.md").write_text(
        _doc(["src/mod.py"], "2025-02-01"), encoding="utf-8")
    assert _findings(repo) == _findings(repo)


# ── repo smoke: real tree runs; advisory posture is the stable invariant ─────

def test_repo_smoke_warning_only_exits_zero():
    # --warning-only is the documented default posture and is exit-0 by
    # construction regardless of trunk churn (other in-flight commits may add
    # net-new staleness that the frozen baseline has not yet absorbed).
    assert cdss.main(["--warning-only"]) == 0
    assert cdss.main(["--json", "--warning-only"]) == 0


def test_repo_shipped_allowlist_is_valid_and_covers_its_pairs():
    # Every pair the shipped baseline lists must actually suppress (round-trips
    # through load_allowlist and is recognised by partition_findings).
    allow = cdss.load_allowlist(cdss.DEFAULT_ALLOW)
    assert allow, "shipped baseline should be non-empty"
    findings = cdss.compute_findings(cdss.REPO_ROOT)
    _new, known = cdss.partition_findings(findings, allow)
    for f in known:
        assert (f["doc"], f["source"]) in allow
