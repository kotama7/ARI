"""Tests for ``ari clone``.

Coverage:
- T-2: sha256 mismatch → hard fail; atomic; behaviour with existing dest
- T-CL5: failure leaves no partial dest
- T-CL8: --no-extract leaves a tarball, doesn't extract

Bundles for the fixture are built by curating a sample EAR via curate.py
and tarring the result. This keeps the test loop tight and exercises the
full curate-then-clone round trip locally.
"""
from __future__ import annotations

import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

# Make ari-skill-transform/src importable for the curator.
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))

import curate as curate_mod  # type: ignore  # noqa: E402

from ari.clone import clone, CloneError  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _build_curated(tmp: Path) -> Path:
    """Build a curated EAR (ear_published/) and return its path + digest."""
    ckpt = tmp / "src_ckpt"
    ear = ckpt / "ear"
    ear.mkdir(parents=True)
    (ear / "README.md").write_text("# README\n")
    (ear / "RESULTS.md").write_text("# Results\n")
    code = ear / "code"
    code.mkdir()
    (code / "train.py").write_text("print('train')\n")
    (ear / "publish.yaml").write_text(
        "include:\n  - 'README.md'\n  - 'RESULTS.md'\n  - 'code/**'\n",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert not res.skipped
    return ckpt / "ear_published"


def _make_tarball(curated: Path, dest: Path) -> Path:
    """Pack ear_published/ into a .tar.gz so the file resolver can see it."""
    bundle = dest / "bundle.tar.gz"
    with tarfile.open(bundle, mode="w:gz") as tar:
        for item in sorted(curated.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=item.relative_to(curated))
    return bundle


@pytest.fixture
def bundle_setup(tmp_path: Path):
    curated = _build_curated(tmp_path)
    bundle = _make_tarball(curated, tmp_path)
    digest = json.loads((curated / "manifest.lock").read_text())["bundle_sha256"]
    return {"curated": curated, "bundle": bundle, "digest": digest, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# T-2 / T-CL5: digest verification, atomicity, dest semantics
# ---------------------------------------------------------------------------

def test_clone_file_url_extracts_and_verifies(bundle_setup):
    dest = bundle_setup["tmp"] / "out"
    res = clone(
        f"file://{bundle_setup['bundle']}",
        dest=dest,
        expect_sha256=bundle_setup["digest"],
    )
    assert res.dest == dest
    assert res.bundle_sha256 == bundle_setup["digest"]
    assert (dest / "manifest.lock").exists()
    assert (dest / "README.md").read_text() == "# README\n"
    assert (dest / "code" / "train.py").exists()
    assert res.extracted is True
    assert res.file_count == 3


def test_clone_sha256_mismatch_hard_fails(bundle_setup):
    dest = bundle_setup["tmp"] / "out_bad"
    bad = "0" * 64
    with pytest.raises(CloneError) as excinfo:
        clone(f"file://{bundle_setup['bundle']}", dest=dest, expect_sha256=bad)
    assert "bundle digest mismatch" in str(excinfo.value)
    # T-CL5: no partial dest left behind.
    assert not dest.exists()


def test_clone_corrupted_bundle_is_caught(bundle_setup):
    """Tampering with a file inside the tarball must fail digest re-derivation."""
    # Rebuild a tarball with a tampered file.
    tampered_dir = bundle_setup["tmp"] / "tampered"
    shutil.copytree(bundle_setup["curated"], tampered_dir)
    (tampered_dir / "README.md").write_text("# README TAMPERED\n")
    bad_bundle = bundle_setup["tmp"] / "bad_bundle.tar.gz"
    with tarfile.open(bad_bundle, mode="w:gz") as tar:
        for item in sorted(tampered_dir.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=item.relative_to(tampered_dir))

    dest = bundle_setup["tmp"] / "out_corrupt"
    with pytest.raises(CloneError) as excinfo:
        clone(f"file://{bad_bundle}", dest=dest)
    msg = str(excinfo.value)
    # We surface either a per-file mismatch or an aggregate manifest mismatch
    # depending on which check fires first; both indicate corruption.
    assert "sha256" in msg.lower()
    assert not dest.exists()


def test_clone_existing_nonempty_dest_refused(bundle_setup):
    dest = bundle_setup["tmp"] / "occupied"
    dest.mkdir()
    (dest / "stale.txt").write_text("old")
    with pytest.raises(CloneError) as excinfo:
        clone(f"file://{bundle_setup['bundle']}", dest=dest)
    assert "exists and is not empty" in str(excinfo.value)
    assert (dest / "stale.txt").exists()  # not clobbered


def test_clone_existing_empty_dest_ok(bundle_setup):
    dest = bundle_setup["tmp"] / "empty"
    dest.mkdir()
    res = clone(f"file://{bundle_setup['bundle']}", dest=dest)
    assert res.bundle_sha256 == bundle_setup["digest"]
    assert (dest / "manifest.lock").exists()


# ---------------------------------------------------------------------------
# T-CL8: --no-extract leaves the tarball, doesn't extract
# ---------------------------------------------------------------------------

def test_clone_no_extract(bundle_setup):
    dest = bundle_setup["tmp"] / "raw"
    res = clone(
        f"file://{bundle_setup['bundle']}",
        dest=dest,
        extract=False,
    )
    assert res.extracted is False
    # The tarball should be on disk under dest; manifest is not extracted.
    assert (dest / "bundle.tar.gz").exists()
    assert not (dest / "manifest.lock").exists()


# ---------------------------------------------------------------------------
# Default dest derivation
# ---------------------------------------------------------------------------

def test_clone_default_dest_uses_basename(bundle_setup, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = clone(f"file://{bundle_setup['bundle']}")
    # default dest is the bundle stem ("bundle")
    assert res.dest.name == "bundle"
    assert res.bundle_sha256 == bundle_setup["digest"]


# ---------------------------------------------------------------------------
# Unknown scheme
# ---------------------------------------------------------------------------

def test_clone_unknown_scheme_raises(tmp_path):
    with pytest.raises(CloneError):
        clone("weird-scheme://foo", dest=tmp_path / "x")


# ---------------------------------------------------------------------------
# ari:// resolver requires a configured registry
# ---------------------------------------------------------------------------

def test_clone_ari_scheme_requires_registry_config(tmp_path, monkeypatch):
    """ari:// is implemented, but only when a registry is configured.

    Without ``ARI_REGISTRY_URL`` or a discoverable ``registries.yaml``
    (``$ARI_REGISTRIES_FILE`` / ``{checkpoint}/.ari/registries.yaml`` /
    ``$(pwd)/.ari/registries.yaml`` — note: ``~/.ari/registries.yaml``
    is deprecated since v0.5.0), the resolver fails with a clear
    error instead of pretending to succeed.
    """
    monkeypatch.delenv("ARI_REGISTRY_URL", raising=False)
    monkeypatch.delenv("ARI_REGISTRY_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    monkeypatch.setenv("ARI_REGISTRIES_FILE", str(tmp_path / "missing-registries.yaml"))
    with pytest.raises(CloneError) as excinfo:
        clone("ari://abc123", dest=tmp_path / "x")
    assert "registry" in str(excinfo.value).lower() or "ari://" in str(excinfo.value)
