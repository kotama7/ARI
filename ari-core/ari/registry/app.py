"""ari-registry FastAPI app builder.

Kept import-light: ``fastapi`` is only required at server-run time.
``build_app(data_dir)`` returns a FastAPI application; tests use it via
``starlette.testclient``.

Note: do NOT add ``from __future__ import annotations`` here — FastAPI's
parameter introspection needs live type objects (``UploadFile`` etc.) to
build the request schema, and PEP 563 stringification breaks it on some
versions of pydantic + fastapi.
"""

import json
import os
from pathlib import Path
from typing import Optional

from .auth import TokenStore
from .storage import FilesystemStorage, StorageError


def build_app(data_dir=None):
    try:
        from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Response
        from fastapi.responses import FileResponse
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("fastapi is required to run the registry; pip install fastapi uvicorn") from e

    from ari.registry import resolve_data_dir
    data_dir = resolve_data_dir(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    storage = FilesystemStorage(data_dir)
    tokens = TokenStore(data_dir / "tokens.db")

    app = FastAPI(title="ari-registry", version="0.7.0")

    def _auth(authorization):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="bearer token required")
        token = authorization[7:].strip()
        user = tokens.authenticate(token)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid token")
        return user

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/version")
    def version():
        return {"version": "0.7.0", "service": "ari-registry"}

    @app.post("/artifact")
    async def post_artifact(
        bundle: UploadFile = File(...),
        manifest: str = Form(...),
        metadata: str = Form("{}"),
        visibility: str = Form("staged"),
        authorization: Optional[str] = Header(default=None),
    ):
        user = _auth(authorization)
        bundle_bytes = await bundle.read()
        manifest_bytes = manifest.encode("utf-8")
        try:
            meta = storage.put(
                bundle_bytes, manifest_bytes,
                visibility=visibility, owner=user,
            )
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e))
        artifact_id = meta["id"]
        return {
            "id": artifact_id,
            "ref": f"ari://{artifact_id}",
            "visibility": meta["visibility"],
            "duplicate": meta.get("duplicate", False),
        }

    @app.get("/artifact/{artifact_id}")
    def get_artifact(artifact_id: str, authorization: Optional[str] = Header(default=None)):
        meta = storage.get_meta(artifact_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="not found")
        if meta["visibility"] in ("staged", "private-token"):
            user = _auth(authorization)
            if meta["visibility"] == "staged" and user != meta.get("owner"):
                raise HTTPException(status_code=403, detail="staged artifact: owner only")
        bundle = storage.get_bundle_path(artifact_id)
        return FileResponse(
            str(bundle),
            media_type="application/gzip",
            filename=f"{artifact_id}.tar.gz",
            headers={
                "X-ARI-Sha256": meta.get("sha256", ""),
                "X-ARI-Visibility": meta.get("visibility", ""),
            },
        )

    @app.head("/artifact/{artifact_id}")
    def head_artifact(artifact_id: str):
        meta = storage.get_meta(artifact_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="not found")
        return Response(
            status_code=200,
            headers={
                "X-ARI-Sha256": meta.get("sha256", ""),
                "X-ARI-Visibility": meta.get("visibility", ""),
                "Content-Length": str(meta.get("length", 0)),
            },
        )

    @app.get("/artifact/{artifact_id}/manifest.lock")
    def get_manifest(artifact_id: str):
        body = storage.get_manifest_bytes(artifact_id)
        if body is None:
            raise HTTPException(status_code=404, detail="not found")
        return Response(content=body, media_type="application/json")

    @app.post("/artifact/{artifact_id}/promote")
    async def promote(
        artifact_id: str,
        target: str = "public",
        authorization: Optional[str] = Header(default=None),
    ):
        user = _auth(authorization)
        meta = storage.get_meta(artifact_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="not found")
        if user != meta.get("owner"):
            raise HTTPException(status_code=403, detail="owner only")
        try:
            new_meta = storage.set_visibility(artifact_id, target)
        except StorageError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"id": artifact_id, "visibility": new_meta["visibility"]}

    @app.delete("/artifact/{artifact_id}")
    def delete_artifact(artifact_id: str, authorization: Optional[str] = Header(default=None)):
        user = _auth(authorization)
        try:
            ok = storage.delete(artifact_id, owner=user)
        except StorageError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        return {"deleted": artifact_id}

    return app
