"""Tests for the EAR curator.

Coverage:
- T-1: include / exclude / max_file_mb behaviour
- T-built-in-deny: .env*, secrets/**, **/*.pem, **/*.key are filtered even
  when allowlisted
- T-8: publish.yaml absent → curation is skipped, no ear_published/ left
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the ari-skill-transform src dir importable. Same pattern used by
# tests/test_ear.py — the skill is laid out as src/{server,curate}.py.
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))

import curate as curate_mod  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write(p: Path, content: bytes | str = b"") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)


def _make_ear(tmp_path: Path) -> Path:
    """Build a representative EAR with code, data, secrets, and large files."""
    ckpt = tmp_path / "ckpt_xyz"
    ear = ckpt / "ear"
    _write(ear / "README.md", "# README\n")
    _write(ear / "RESULTS.md", "# Results\n")
    _write(ear / "code" / "node_a" / "train.py", "print('train')\n")
    _write(ear / "code" / "node_a" / "utils.py", "X = 1\n")
    _write(ear / "data" / "raw_metrics.json", '{"a":1}')
    _write(ear / "data" / "secrets" / "api.key", "supersecret")
    _write(ear / "logs" / "run.log", "log entry\n")
    _write(ear / ".env", "TOKEN=hunter2\n")
    _write(ear / "code" / "node_a" / ".env.local", "DB=localhost\n")
    _write(ear / "code" / "node_a" / "id_rsa", "PRIVATE KEY")
    _write(ear / "data" / "key.pem", "-----BEGIN-----")
    return ckpt


# ---------------------------------------------------------------------------
# T-1: allowlist / exclude / max_file_mb
# ---------------------------------------------------------------------------

def test_curate_allowlist_and_exclude(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
  - "code/**"
  - "data/raw_metrics.json"
exclude:
  - "code/**/utils.py"
""",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert res.skipped is False
    assert "README.md" in res.included_files
    assert "code/node_a/train.py" in res.included_files
    assert "data/raw_metrics.json" in res.included_files
    # excluded by user rule
    assert "code/node_a/utils.py" not in res.included_files
    # not in include allowlist
    assert "RESULTS.md" not in res.included_files
    assert "logs/run.log" not in res.included_files
    # ear_published/ is on disk and matches included list
    out = ckpt / "ear_published"
    assert out.is_dir()
    assert (out / "README.md").read_text() == "# README\n"
    assert not (out / "code" / "node_a" / "utils.py").exists()
    # manifest.lock exists, sha256 are populated, bundle digest is hex
    manifest = json.loads((out / "manifest.lock").read_text())
    assert manifest["bundle_sha256"] == res.bundle_sha256
    assert len(res.bundle_sha256) == 64
    paths = {f["path"] for f in manifest["files"]}
    assert "README.md" in paths
    for f in manifest["files"]:
        assert len(f["sha256"]) == 64


def test_curate_max_file_mb_hard_fails(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    big = ckpt / "ear" / "data" / "big.bin"
    big.write_bytes(b"\x00" * (3 * 1024 * 1024))  # 3 MB
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "data/big.bin"
max_file_mb: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(curate_mod.CurateError) as excinfo:
        curate_mod.curate(ckpt)
    assert "max_file_mb" in str(excinfo.value)
    # ear_published/ should NOT have been left behind from a partial copy.
    assert not (ckpt / "ear_published").exists()


def test_curate_max_file_mb_passes_when_under_cap(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
max_file_mb: 100
""",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert "README.md" in res.included_files
    assert res.excluded_count == 0


# ---------------------------------------------------------------------------
# T-built-in-deny: built-in deny outranks include
# ---------------------------------------------------------------------------

def test_builtin_deny_outranks_include(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "**/*"
""",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    # Authored allowlist is "everything", but built-in deny still bites.
    assert ".env" not in res.included_files
    assert "code/node_a/.env.local" not in res.included_files
    assert "data/secrets/api.key" not in res.included_files
    assert "data/key.pem" not in res.included_files
    assert "code/node_a/id_rsa" not in res.included_files
    # excluded_count should reflect at least the 5 sensitive files we placed
    assert res.excluded_count >= 5
    # And of course harmless files survive
    assert "README.md" in res.included_files
    assert "code/node_a/train.py" in res.included_files


# ---------------------------------------------------------------------------
# T-8: publish.yaml absent → fall back to ORS-tuned built-in default. Without
# this fallback, the ear → ear_published → ear_publish → ors_seed_sandbox
# chain has no curated bundle to ship and reproducibility verification falls
# back to LLM-only (paper → reproduce.sh) instead of using ARI's own code.
# ---------------------------------------------------------------------------

def test_missing_publish_yaml_uses_default(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    # No publish.yaml written
    res = curate_mod.curate(ckpt)
    assert res.skipped is False
    # Default include = reproduce.sh + environment.json + code/** + data/** + ...
    # _make_ear writes code/node_a/{train.py,utils.py} → both included.
    paths = set(res.included_files)
    assert "code/node_a/train.py" in paths
    assert "code/node_a/utils.py" in paths
    assert "data/raw_metrics.json" in paths
    # README.md / RESULTS.md / logs/* are NOT in the default include list.
    assert "README.md" not in paths
    assert "RESULTS.md" not in paths
    # BUILTIN_DENY still wins: secrets / .env / *.pem / id_rsa stay out.
    assert "code/node_a/id_rsa" not in paths
    assert "data/key.pem" not in paths
    assert "data/secrets/api.key" not in paths
    # ear_published/ created with manifest.lock.
    assert (ckpt / "ear_published" / "manifest.lock").is_file()
    assert res.bundle_sha256


def test_missing_publish_yaml_overwrites_stale_dir(tmp_path: Path):
    """When curate now runs unconditionally (default fallback), an existing
    ear_published/ from a previous publish must be replaced atomically by
    the new curate output, not appended to or left stale."""
    ckpt = _make_ear(tmp_path)
    stale = ckpt / "ear_published"
    stale.mkdir()
    (stale / "stale.txt").write_text("old")
    res = curate_mod.curate(ckpt)
    assert res.skipped is False
    # Stale file from the previous bundle is gone; only the new curated
    # files + manifest.lock remain.
    assert not (stale / "stale.txt").exists()
    assert (stale / "manifest.lock").is_file()


# ---------------------------------------------------------------------------
# Atomicity: a failing curate must not corrupt a previously good ear_published/
# ---------------------------------------------------------------------------

def test_curate_atomic_on_size_failure(tmp_path: Path):
    ckpt = _make_ear(tmp_path)
    # First, a successful curate with a small allowlist.
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
""",
        encoding="utf-8",
    )
    good = curate_mod.curate(ckpt)
    good_digest = good.bundle_sha256
    assert (ckpt / "ear_published" / "README.md").exists()

    # Then introduce a too-large file and re-curate; this must hard-fail.
    big = ckpt / "ear" / "data" / "big.bin"
    big.write_bytes(b"\x00" * (5 * 1024 * 1024))
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
  - "data/big.bin"
max_file_mb: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(curate_mod.CurateError):
        curate_mod.curate(ckpt)
    # ear_published/ from the good run should still be intact
    out = ckpt / "ear_published"
    assert out.is_dir()
    assert (out / "README.md").exists()
    manifest = json.loads((out / "manifest.lock").read_text())
    assert manifest["bundle_sha256"] == good_digest


# ---------------------------------------------------------------------------
# bundle_sha256 stability: same inputs → same digest
# ---------------------------------------------------------------------------

def test_bundle_sha256_is_stable(tmp_path: Path):
    """Re-curating an unchanged ear/ with the same publish.yaml must produce
    the same bundle digest. This is the property that lets the
    paper-baked digest be a permanent source of truth."""
    ckpt = _make_ear(tmp_path)
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
  - "code/**"
""",
        encoding="utf-8",
    )
    a = curate_mod.curate(ckpt)
    b = curate_mod.curate(ckpt)
    assert a.bundle_sha256 == b.bundle_sha256
    assert len(a.bundle_sha256) == 64


def test_bundle_sha256_changes_with_content(tmp_path: Path):
    """Mutating an included file must change the bundle digest."""
    ckpt = _make_ear(tmp_path)
    (ckpt / "ear" / "publish.yaml").write_text(
        """
include:
  - "README.md"
""",
        encoding="utf-8",
    )
    a = curate_mod.curate(ckpt)
    (ckpt / "ear" / "README.md").write_text("# README v2\n")
    b = curate_mod.curate(ckpt)
    assert a.bundle_sha256 != b.bundle_sha256
