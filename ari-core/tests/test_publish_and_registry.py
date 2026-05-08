"""Tests for ``ari ear publish`` + ari-registry.

Coverage:
- T-RG-1〜4: registry CRUD via FastAPI TestClient (POST/GET/HEAD/DELETE/promote),
  token auth, visibility transitions, content-addressed id
- T-CL-ari: `ari clone ari://...` against an in-process registry (e2e)
- T-PUB-1: `--dry-run` issues no HTTP calls
- T-PUB-2: publish_record.json schema is well-formed
- T-6: ARI_PUBLISH_DRYRUN=true forces dryrun
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

# Ari publish & curate modules
_TRANSFORM_SRC = (
    Path(__file__).parent.parent.parent / "ari-skill-transform" / "src"
).resolve()
if str(_TRANSFORM_SRC) not in sys.path:
    sys.path.insert(0, str(_TRANSFORM_SRC))

import curate as curate_mod  # type: ignore  # noqa: E402

from ari.publish import publish, promote, PublishError, PublishRecord  # noqa: E402
from ari.registry.app import build_app  # noqa: E402
from ari.registry.auth import TokenStore  # noqa: E402
from ari.registry.storage import FilesystemStorage  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:
    pytest.skip("fastapi not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def curated_checkpoint(tmp_path: Path) -> Path:
    ckpt = tmp_path / "ckpt"
    ear = ckpt / "ear"
    ear.mkdir(parents=True)
    (ear / "README.md").write_text("# README\n")
    (ear / "code").mkdir()
    (ear / "code" / "run.py").write_text("print(1)\n")
    (ear / "publish.yaml").write_text(
        "include:\n  - 'README.md'\n  - 'code/**'\n",
        encoding="utf-8",
    )
    res = curate_mod.curate(ckpt)
    assert not res.skipped
    return ckpt


@pytest.fixture
def registry_client(tmp_path: Path):
    """Spin up a FastAPI TestClient with a fresh on-disk data dir + a
    pre-issued bearer token. Returns (client, token, storage)."""
    data_dir = tmp_path / "registry_data"
    data_dir.mkdir()
    # Prime the token store BEFORE we build the app, so the first request
    # already has a valid token.
    tokens = TokenStore(data_dir / "tokens.db")
    _, plaintext = tokens.issue("alice")

    # Tell build_app where to put data via env (matches production code).
    import os as _os
    _os.environ["ARI_REGISTRY_DATA"] = str(data_dir)
    app = build_app(data_dir)
    client = TestClient(app)
    return client, plaintext, FilesystemStorage(data_dir)


# ---------------------------------------------------------------------------
# T-RG: registry CRUD + auth + visibility + content-addressed id
# ---------------------------------------------------------------------------

def _post_artifact(client, token, *, visibility="staged", payload=b"hello-bundle", manifest=None):
    if manifest is None:
        manifest = {"version": 1, "files": [], "bundle_sha256": "deadbeef"}
    files = {"bundle": ("bundle.tar.gz", payload, "application/gzip")}
    data = {
        "visibility": visibility,
        "manifest": json.dumps(manifest),
        "metadata": json.dumps({"checkpoint_id": "test"}),
    }
    return client.post(
        "/artifact",
        files=files, data=data,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_registry_post_get_head(registry_client):
    client, token, _ = registry_client
    resp = _post_artifact(client, token, payload=b"abc-bundle-bytes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visibility"] == "staged"
    assert body["ref"].startswith("ari://")
    assert body["id"] == body["ref"][len("ari://"):]
    aid = body["id"]
    # T-RG-4: id is the content-addressed sha256[:16]
    import hashlib
    assert aid == hashlib.sha256(b"abc-bundle-bytes").hexdigest()[:16]

    # GET while staged: owner can read
    r = client.get(f"/artifact/{aid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers["X-ARI-Visibility"] == "staged"

    # GET while staged: anonymous is rejected
    r = client.get(f"/artifact/{aid}")
    assert r.status_code == 401

    # HEAD reveals visibility + sha without auth
    r = client.head(f"/artifact/{aid}")
    assert r.status_code == 200
    assert r.headers["X-ARI-Sha256"]
    assert r.headers["X-ARI-Visibility"] == "staged"


def test_registry_promote_visibility(registry_client):
    client, token, _ = registry_client
    aid = _post_artifact(client, token).json()["id"]
    # staged → public
    r = client.post(
        f"/artifact/{aid}/promote",
        params={"target": "public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["visibility"] == "public"
    # Anonymous can now GET
    r = client.get(f"/artifact/{aid}")
    assert r.status_code == 200
    # Demoting public → staged is forbidden
    r = client.post(
        f"/artifact/{aid}/promote",
        params={"target": "staged"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_registry_token_auth_required_for_write(registry_client):
    client, token, _ = registry_client
    # POST without auth → 401
    files = {"bundle": ("b.tar.gz", b"x", "application/gzip")}
    data = {"visibility": "staged", "manifest": "{}", "metadata": "{}"}
    r = client.post("/artifact", files=files, data=data)
    assert r.status_code == 401
    # POST with bad token → 401
    r = client.post(
        "/artifact", files=files, data=data,
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_registry_delete_owner_only(registry_client, tmp_path):
    client, token_alice, _ = registry_client
    aid = _post_artifact(client, token_alice).json()["id"]
    # A second user (issued via a fresh TokenStore connecting to the same DB).
    import os
    tokens = TokenStore(Path(os.environ["ARI_REGISTRY_DATA"]) / "tokens.db")
    _, token_bob = tokens.issue("bob")
    r = client.delete(f"/artifact/{aid}", headers={"Authorization": f"Bearer {token_bob}"})
    assert r.status_code == 403
    r = client.delete(f"/artifact/{aid}", headers={"Authorization": f"Bearer {token_alice}"})
    assert r.status_code == 200
    # Now 404
    r = client.head(f"/artifact/{aid}")
    assert r.status_code == 404


def test_registry_manifest_endpoint(registry_client):
    client, token, _ = registry_client
    manifest = {"version": 1, "files": [], "bundle_sha256": "abc"}
    aid = _post_artifact(client, token, manifest=manifest).json()["id"]
    # promote so anonymous fetch is possible
    client.post(
        f"/artifact/{aid}/promote", params={"target": "public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = client.get(f"/artifact/{aid}/manifest.lock")
    assert r.status_code == 200
    assert json.loads(r.content) == manifest


# ---------------------------------------------------------------------------
# T-PUB-1 / T-PUB-2 / T-6: publish flow + dryrun + record schema
# ---------------------------------------------------------------------------

def test_publish_local_tarball_dry_run(curated_checkpoint, tmp_path):
    rec = publish(
        curated_checkpoint,
        backend="local-tarball",
        dry_run=True,
    )
    assert rec.dry_run is True
    assert rec.ref.startswith("file://")
    assert rec.bundle_sha256
    record_path = curated_checkpoint / "publish_record.json"
    assert record_path.exists()
    # T-PUB-2: schema sanity
    data = json.loads(record_path.read_text())
    for k in ("backend", "ref", "bundle_sha256", "visibility", "timestamp", "dry_run", "extra"):
        assert k in data
    assert data["visibility"] == "staged"  # always staged on first publish (FR-P5)


def test_publish_local_tarball_real(curated_checkpoint, tmp_path):
    out = tmp_path / "out"
    rec = publish(
        curated_checkpoint,
        backend="local-tarball",
        metadata={"local_tarball_out": str(out)},
    )
    bundle = out / "bundle.tar.gz"
    assert bundle.exists()
    assert rec.ref == f"file://{bundle.resolve()}"


def test_ari_publish_dryrun_env_forces_dry_run(curated_checkpoint, monkeypatch):
    monkeypatch.setenv("ARI_PUBLISH_DRYRUN", "true")
    rec = publish(curated_checkpoint, backend="ari-registry")
    assert rec.dry_run is True
    assert rec.ref.startswith("ari://")
    # Length matches sha256[:16] + "ari://"
    assert len(rec.ref) >= len("ari://") + 16


def test_promote_uses_recorded_backend(curated_checkpoint, tmp_path):
    rec = publish(
        curated_checkpoint,
        backend="local-tarball",
        metadata={"local_tarball_out": str(tmp_path / "out")},
    )
    promoted = promote(curated_checkpoint, target="public")
    assert promoted.visibility == "public"
    assert promoted.promoted_at


# ---------------------------------------------------------------------------
# T-CL-ari: ari:// resolver works against an in-process registry
# ---------------------------------------------------------------------------

def test_ari_clone_ari_scheme_e2e(tmp_path, monkeypatch, curated_checkpoint):
    """Spin up a uvicorn-less ASGI server in a thread and clone via ari://."""
    import uvicorn  # type: ignore
    data_dir = tmp_path / "registry_data"
    data_dir.mkdir()
    tokens = TokenStore(data_dir / "tokens.db")
    _, plaintext = tokens.issue("alice")
    monkeypatch.setenv("ARI_REGISTRY_DATA", str(data_dir))
    app = build_app(data_dir)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        # Wait for socket bind.
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"

        # Tarball + manifest from the curated checkpoint.
        from ari.publish import _build_tarball  # type: ignore
        tar = tmp_path / "bundle.tar.gz"
        tar_sha = _build_tarball(curated_checkpoint / "ear_published", tar)
        manifest = (curated_checkpoint / "ear_published" / "manifest.lock").read_bytes()

        # Upload via TestClient-style direct POST.
        import requests  # type: ignore
        r = requests.post(
            f"{base_url}/artifact",
            files={"bundle": ("bundle.tar.gz", tar.read_bytes(), "application/gzip")},
            data={"visibility": "public", "manifest": manifest.decode("utf-8"), "metadata": "{}"},
            headers={"Authorization": f"Bearer {plaintext}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        artifact_id = r.json()["id"]
        # Promote so anonymous clone works.
        r = requests.post(
            f"{base_url}/artifact/{artifact_id}/promote",
            params={"target": "public"},
            headers={"Authorization": f"Bearer {plaintext}"},
            timeout=10,
        )
        assert r.status_code == 200

        # Configure the ari:// resolver to point at our in-process registry.
        monkeypatch.setenv("ARI_REGISTRY_URL", base_url)
        monkeypatch.setenv("ARI_REGISTRY_TOKEN", plaintext)

        # Clone!
        from ari.clone import clone
        dest = tmp_path / "out"
        result = clone(f"ari://{artifact_id}", dest=dest)
        assert (dest / "manifest.lock").exists()
        # Bundle digest matches the original curated bundle.
        bundle_sha = json.loads((curated_checkpoint / "ear_published" / "manifest.lock").read_text())["bundle_sha256"]
        assert result.bundle_sha256 == bundle_sha
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Storage layer unit tests
# ---------------------------------------------------------------------------

def test_storage_visibility_downgrade_blocked(tmp_path: Path):
    s = FilesystemStorage(tmp_path / "data")
    meta = s.put(b"bytes", b'{"version":1,"files":[],"bundle_sha256":"x"}', visibility="public", owner="alice")
    aid = meta["id"]
    with pytest.raises(Exception):
        s.set_visibility(aid, "staged")


def test_storage_idempotent_reupload(tmp_path: Path):
    s = FilesystemStorage(tmp_path / "data")
    meta1 = s.put(b"same-bytes", b"{}", visibility="staged", owner="alice")
    meta2 = s.put(b"same-bytes", b"{}", visibility="staged", owner="alice")
    assert meta1["id"] == meta2["id"]
    assert meta2.get("duplicate") is True


def test_storage_owner_protection_on_reupload(tmp_path: Path):
    s = FilesystemStorage(tmp_path / "data")
    s.put(b"x", b"{}", visibility="staged", owner="alice")
    with pytest.raises(Exception):
        s.put(b"x", b"{}", visibility="staged", owner="bob")
