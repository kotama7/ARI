"""https:// (and http://) resolver — fetch a remote tarball.

Uses ``urllib.request`` for the HTTP GET to avoid a hard dependency on
``httpx`` (httpx is only required when the registry client is used).
The download is streamed to disk to keep memory bounded.
"""
from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


_CHUNK = 1024 * 1024  # 1 MiB
_DEFAULT_TIMEOUT = float(os.environ.get("ARI_CLONE_HTTP_TIMEOUT", "60"))


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(ref)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"https resolver: not an http(s) URL: {ref}")
    name = Path(parsed.path).name or "bundle.tar.gz"
    target = workdir / name
    req = urllib.request.Request(ref, headers={"User-Agent": "ari-clone/0.7.0"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp, target.open("wb") as out:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            out.write(chunk)
    return target


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
