"""Tests for the Zenodo + gh publish backends and the GUI publish API.

Network calls are mocked. We do not hit real Zenodo / GitHub.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Curate module sys-path bootstrap (so we can build a fixture EAR).
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))

import curate as curate_mod  # type: ignore  # noqa: E402

from ari.publish import publish, promote, _build_tarball  # noqa: E402
from ari.publish.backends import zenodo as zenodo_backend  # noqa: E402
from ari.publish.backends import gh as gh_backend  # noqa: E402


@pytest.fixture
def curated_checkpoint(tmp_path: Path) -> Path:
    ckpt = tmp_path / "ckpt"
    ear = ckpt / "ear"
    ear.mkdir(parents=True)
    (ear / "README.md").write_text("# README\n")
    (ear / "code").mkdir()
    (ear / "code" / "run.py").write_text("print(1)\n")
    (ear / "publish.yaml").write_text(
        "include:\n  - 'README.md'\n  - 'code/**'\n"
        "license: MIT\n"
        "visibility: public\n",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert not res.skipped
    return ckpt


# ---------------------------------------------------------------------------
# T-Z: Zenodo backend (mocked HTTP)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._payload


def test_zenodo_dry_run_makes_no_http(curated_checkpoint, monkeypatch):
    monkeypatch.setenv("ARI_PUBLISH_DRYRUN", "true")
    monkeypatch.setenv("ZENODO_TOKEN", "fake")
    called = []
    def _fake_urlopen(*a, **kw):  # pragma: no cover - should not be called
        called.append(a)
        raise AssertionError("dryrun should not hit the network")
    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        rec = publish(curated_checkpoint, backend="zenodo")
    assert rec.dry_run is True
    assert rec.ref.startswith("doi:")
    assert called == []


def test_zenodo_publish_creates_deposition(curated_checkpoint, monkeypatch):
    monkeypatch.setenv("ZENODO_TOKEN", "fake-token")
    monkeypatch.setenv("ZENODO_SANDBOX", "true")
    state = {"step": 0}

    def _fake_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        if state["step"] == 0:
            state["step"] = 1
            return _FakeResponse({
                "id": 99999,
                "links": {"bucket": "https://sandbox.zenodo.org/api/files/abc"},
                "metadata": {},
            })
        # Subsequent PUTs to /files/abc/<filename>
        return _FakeResponse({"ok": True})

    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        rec = publish(curated_checkpoint, backend="zenodo", visibility="public")
    assert rec.dry_run is False
    assert "draft" in rec.ref
    assert rec.extra.get("deposition_id") == "99999"


def test_zenodo_promote_mints_doi(curated_checkpoint, monkeypatch):
    monkeypatch.setenv("ZENODO_TOKEN", "fake-token")
    # Step 1: publish (mocked)
    state = {"calls": 0}
    def _fake_publish_urlopen(req, *a, **kw):
        state["calls"] += 1
        if state["calls"] == 1:
            return _FakeResponse({
                "id": 12345,
                "links": {"bucket": "https://sandbox.zenodo.org/api/files/x"},
            })
        return _FakeResponse({"ok": True})
    with patch.object(urllib.request, "urlopen", _fake_publish_urlopen):
        publish(curated_checkpoint, backend="zenodo", visibility="public")
    # Step 2: promote
    def _fake_promote_urlopen(req, *a, **kw):
        return _FakeResponse({"doi": "10.5281/zenodo.12345"})
    with patch.object(urllib.request, "urlopen", _fake_promote_urlopen):
        rec = promote(curated_checkpoint, target="public")
    assert rec.visibility == "public"
    assert rec.extra.get("doi") == "10.5281/zenodo.12345"


def test_zenodo_metadata_handles_embargo(monkeypatch):
    md = zenodo_backend._build_metadata(
        {"checkpoint_id": "x"},
        {"publish": {"visibility": "embargoed-until:2026-12-31", "license": "Apache-2.0"}},
    )
    assert md["metadata"]["access_right"] == "embargoed"
    assert md["metadata"]["embargo_date"] == "2026-12-31"
    assert md["metadata"]["license"] == "Apache-2.0"


# ---------------------------------------------------------------------------
# T-GH: gh backend (mocked subprocess + gh on PATH)
# ---------------------------------------------------------------------------

def test_gh_refuses_non_public_visibility(tmp_path, monkeypatch):
    """publish.yaml.visibility=unlisted → gh backend refuses with a clear message."""
    monkeypatch.setenv("ARI_GH_REPO", "user/repo")
    ckpt = tmp_path / "ckpt"
    ear = ckpt / "ear"
    ear.mkdir(parents=True)
    (ear / "README.md").write_text("# README\n")
    (ear / "publish.yaml").write_text(
        "include:\n  - 'README.md'\nvisibility: unlisted\n",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert not res.skipped
    with pytest.raises(Exception) as excinfo:
        publish(ckpt, backend="gh", visibility="unlisted")
    assert "public" in str(excinfo.value).lower()


def test_gh_dry_run_skips_subprocess(curated_checkpoint, monkeypatch):
    monkeypatch.setenv("ARI_GH_REPO", "user/repo")
    monkeypatch.setenv("ARI_PUBLISH_DRYRUN", "true")
    rec = publish(curated_checkpoint, backend="gh", visibility="public")
    assert rec.dry_run is True
    assert rec.ref == "gh:user/repo"


def test_gh_publish_release_mode(curated_checkpoint, monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_GH_REPO", "user/repo")
    monkeypatch.setenv("ARI_GH_MODE", "releases")
    # Pretend gh is on PATH.
    monkeypatch.setattr(gh_backend, "_have_gh", lambda: True)
    invocations = []
    def _fake_run(cmd, cwd=None):
        invocations.append({"cmd": cmd, "cwd": str(cwd) if cwd else None})
        return ""
    monkeypatch.setattr(gh_backend, "_run", _fake_run)

    rec = publish(curated_checkpoint, backend="gh", visibility="public")
    assert rec.ref == "gh:user/repo"
    assert rec.extra.get("gh_mode") == "releases"
    # The release create call must include the bundle path and a tag.
    rel = next((i for i in invocations if i["cmd"][:3] == ["gh", "release", "create"]), None)
    assert rel is not None
    assert any(arg.endswith("bundle.tar.gz") for arg in rel["cmd"])


def test_gh_resolver_falls_back_to_git_clone(monkeypatch, tmp_path):
    """If the raw URL 404s, the resolver should `git clone --depth 1` and
    pull bundle.tar.gz from the working tree."""
    from ari.clone.resolvers import gh as gh_resolver

    def _fake_urlopen(req, *a, **kw):
        raise urllib.error.HTTPError(req.full_url if hasattr(req, "full_url") else "x", 404, "nf", {}, io.BytesIO())
    def _fake_subprocess_run(cmd, **kw):
        # Simulate a git clone: drop a fake bundle.tar.gz into the cloned dir.
        for i, arg in enumerate(cmd):
            if arg.startswith("/") or (len(cmd) > i + 1 and arg == "--depth"):
                continue
        clone_target = Path(cmd[-1])
        clone_target.mkdir(parents=True, exist_ok=True)
        (clone_target / "bundle.tar.gz").write_bytes(b"\x1f\x8b\x08fake-bundle")
        rv = MagicMock()
        rv.returncode = 0
        return rv
    with patch.object(urllib.request, "urlopen", _fake_urlopen), \
         patch("ari.clone.resolvers.gh.subprocess.run", _fake_subprocess_run):
        target = gh_resolver.resolve("gh:user/repo", tmp_path)
    assert target.read_bytes() == b"\x1f\x8b\x08fake-bundle"


# ---------------------------------------------------------------------------
# T-G: GUI publish API
# ---------------------------------------------------------------------------

def _patch_checkpoint_resolver(monkeypatch, ckpt: Path) -> None:
    """Make _resolve_checkpoint_dir(ckpt_id) find ``ckpt`` by name."""
    from ari.viz import api_state as _api_state
    monkeypatch.setattr(_api_state, "_checkpoint_search_bases", lambda: [ckpt.parent])


def test_publish_run_requires_consent(curated_checkpoint, monkeypatch):
    """FR-G3: real publishes must be opt-in even if backend is local."""
    from ari.viz.api_publish import _api_publish_run
    _patch_checkpoint_resolver(monkeypatch, curated_checkpoint)
    monkeypatch.setenv("ARI_PUBLISH_DRYRUN", "false")
    body = json.dumps({"backend": "local-tarball", "consent": False, "dry_run": False}).encode("utf-8")
    r = _api_publish_run(curated_checkpoint.name, body)
    assert r.get("_status") == 400
    assert "consent" in r["error"].lower()


def test_publish_run_dry_run_works_without_consent(curated_checkpoint, monkeypatch):
    from ari.viz.api_publish import _api_publish_run
    _patch_checkpoint_resolver(monkeypatch, curated_checkpoint)
    body = json.dumps({"backend": "local-tarball", "consent": False, "dry_run": True}).encode("utf-8")
    r = _api_publish_run(curated_checkpoint.name, body)
    assert r.get("error") is None
    assert r["dry_run"] is True


def test_publish_preview_returns_files(curated_checkpoint, monkeypatch):
    from ari.viz.api_publish import _api_publish_preview
    _patch_checkpoint_resolver(monkeypatch, curated_checkpoint)
    r = _api_publish_preview(curated_checkpoint.name)
    assert "files" in r
    assert r["bundle_sha256"]
    assert r["file_count"] > 0


def test_publish_record_endpoint(curated_checkpoint, monkeypatch):
    from ari.viz.api_publish import _api_publish_record
    _patch_checkpoint_resolver(monkeypatch, curated_checkpoint)
    # Before publish: published=False.
    r = _api_publish_record(curated_checkpoint.name)
    assert r.get("published") is False
    # After a (dryrun) publish, the record exists.
    publish(curated_checkpoint, backend="local-tarball", dry_run=True)
    r = _api_publish_record(curated_checkpoint.name)
    assert r.get("published") is True
    assert r.get("backend") == "local-tarball"
