"""Tests for the publish_record.json auto-loading enhancement to
``fetch_code_bundle``.

This is the X-chain wiring: ``ear_publish`` writes
``publish_record.json::ref`` (file://...bundle.tar.gz from local-tarball),
and ``fetch_code_bundle(checkpoint_dir=..., dest=repro_sandbox)`` should
pick that up and seed the sandbox without the workflow having to thread
the ref string by hand.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load server.py under a unique name (other ari-skill-* server.py modules may
# be loaded too).
_spec = importlib.util.spec_from_file_location("paper_re_server_fcb", SRC / "server.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["paper_re_server_fcb"] = S
_spec.loader.exec_module(S)


def _build_local_bundle(tmp_path: Path) -> tuple[Path, str]:
    """Build a minimal valid bundle by running the real curate + publish pipeline
    (rather than hand-rolling manifest.lock + sha256s, which is duplicating
    code under test).

    Returns ``(bundle_path, bundle_sha256)``. Uses the local-tarball backend
    so the bundle ends up next to the checkpoint as ``bundle.tar.gz``.
    """
    # Add ari-skill-transform/src and ari-core to sys.path so curate / publish
    # are importable.
    repo_root = Path(__file__).resolve().parents[2]
    transform_src = repo_root / "ari-skill-transform" / "src"
    ari_core = repo_root / "ari-core"
    for p in (transform_src, ari_core):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import curate  # noqa: E402
    from ari.publish import publish as _publish  # noqa: E402

    ckpt = tmp_path / "_ckpt_for_bundle"
    ear = ckpt / "ear"
    (ear / "code").mkdir(parents=True)
    (ear / "reproduce.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"
    )
    (ear / "code" / "main.py").write_text("print('hi')\n")
    # Use the new default-publish.yaml fallback.
    res = curate.curate(ckpt)
    assert not res.skipped

    # Direct local tarball next to the checkpoint.
    import os
    os.environ["ARI_LOCAL_TARBALL_OUT"] = str(ckpt)
    rec = _publish(ckpt, backend="local-tarball", visibility="staged")
    bundle = ckpt / "bundle.tar.gz"
    assert bundle.is_file(), f"local-tarball backend did not produce {bundle}"
    return bundle, rec.bundle_sha256


# ── auto-load from publish_record.json ──────────────────────────────────

@pytest.mark.asyncio
async def test_loads_ref_from_publish_record(tmp_path):
    bundle, sha = _build_local_bundle(tmp_path)
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "publish_record.json").write_text(json.dumps({
        "backend": "local-tarball",
        "ref": f"file://{bundle.resolve()}",
        "bundle_sha256": sha,
        "visibility": "staged",
    }))
    dest = ckpt / "repro_sandbox"

    res = await S.fetch_code_bundle(
        ref="",
        checkpoint_dir=str(ckpt),
        dest=str(dest),
    )
    assert res["populated"] is True, res
    assert (dest / "reproduce.sh").is_file()
    assert (dest / "code" / "main.py").is_file()


@pytest.mark.asyncio
async def test_skipped_when_no_publish_record_and_no_ref(tmp_path):
    """When neither ref nor checkpoint_dir/publish_record.json is available,
    we skip cleanly so build_reproduce_sh's LLM fallback can take over."""
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()  # no publish_record.json
    dest = ckpt / "repro_sandbox"

    res = await S.fetch_code_bundle(
        ref="",
        checkpoint_dir=str(ckpt),
        dest=str(dest),
    )
    assert res["populated"] is False
    assert "no code_availability_ref" in res["skipped_reason"]


@pytest.mark.asyncio
async def test_skipped_when_reproduce_sh_already_present(tmp_path):
    bundle, _ = _build_local_bundle(tmp_path)
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "publish_record.json").write_text(json.dumps({
        "ref": f"file://{bundle.resolve()}",
    }))
    dest = ckpt / "repro_sandbox"
    dest.mkdir()
    (dest / "reproduce.sh").write_text("# pre-existing\n")

    res = await S.fetch_code_bundle(
        ref="",
        checkpoint_dir=str(ckpt),
        dest=str(dest),
    )
    assert res["populated"] is False
    assert "reproduce.sh already present" in res["skipped_reason"]
    # Pre-existing reproduce.sh untouched.
    assert (dest / "reproduce.sh").read_text() == "# pre-existing\n"


@pytest.mark.asyncio
async def test_explicit_ref_wins_over_publish_record(tmp_path):
    """If the caller passes an explicit ref, it must override
    publish_record.json (so workflow-side overrides remain possible)."""
    bundle, _ = _build_local_bundle(tmp_path)
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    # publish_record.json points at a non-existent bundle.
    (ckpt / "publish_record.json").write_text(json.dumps({
        "ref": "file:///nonexistent.tar.gz",
    }))
    dest = ckpt / "repro_sandbox"

    res = await S.fetch_code_bundle(
        ref=f"file://{bundle.resolve()}",
        checkpoint_dir=str(ckpt),
        dest=str(dest),
    )
    assert res["populated"] is True, res
    assert (dest / "reproduce.sh").is_file()


@pytest.mark.asyncio
async def test_overwrite_clears_non_empty_dest(tmp_path):
    bundle, _ = _build_local_bundle(tmp_path)
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "publish_record.json").write_text(json.dumps({
        "ref": f"file://{bundle.resolve()}",
    }))
    dest = ckpt / "repro_sandbox"
    dest.mkdir()
    (dest / "stale.txt").write_text("old")  # no reproduce.sh, just stale junk

    res_no = await S.fetch_code_bundle(
        ref="", checkpoint_dir=str(ckpt), dest=str(dest), overwrite=False,
    )
    # Without overwrite, refuses to clobber the non-empty dest.
    assert res_no["populated"] is False
    assert (dest / "stale.txt").exists()

    res_yes = await S.fetch_code_bundle(
        ref="", checkpoint_dir=str(ckpt), dest=str(dest), overwrite=True,
    )
    assert res_yes["populated"] is True
    assert not (dest / "stale.txt").exists()
    assert (dest / "reproduce.sh").is_file()
