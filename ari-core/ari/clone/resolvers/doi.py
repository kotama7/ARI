"""doi: resolver — fetch a Zenodo deposition's bundle.

Only Zenodo DOIs are supported in this version. The DOI is resolved to a
deposition id via Zenodo's REST API, then the first ``bundle.tar.gz``
file in the deposition is downloaded.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


def _zenodo_api_base() -> str:
    if os.environ.get("ZENODO_SANDBOX", "").lower() in ("1", "true", "yes"):
        return "https://sandbox.zenodo.org/api"
    return "https://zenodo.org/api"


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    if not ref.startswith("doi:"):
        raise ValueError(f"doi resolver: not a doi: ref: {ref}")
    doi = ref[len("doi:"):]
    # Accept either "10.5281/zenodo.<id>" or "zenodo/<id>" shorthand.
    if doi.startswith("10.5281/zenodo."):
        record_id = doi.split(".", 2)[-1]
    elif doi.startswith("zenodo/"):
        record_id = doi.split("/", 1)[-1]
    else:
        raise ValueError(f"doi resolver: only Zenodo DOIs are supported (got {doi!r})")

    api_base = _zenodo_api_base()
    record_url = f"{api_base}/records/{record_id}"
    req = urllib.request.Request(record_url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        record = json.loads(resp.read().decode("utf-8"))

    files = record.get("files") or []
    bundle_entry = next((f for f in files if (f.get("key") or f.get("filename") or "").endswith("bundle.tar.gz")), None)
    if not bundle_entry:
        raise RuntimeError(f"zenodo record {record_id} has no bundle.tar.gz")
    download_url = bundle_entry.get("links", {}).get("download") or bundle_entry.get("links", {}).get("self")
    if not download_url:
        raise RuntimeError(f"zenodo record {record_id} bundle entry has no download link")

    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "bundle.tar.gz"
    dl_req = urllib.request.Request(download_url, headers={"User-Agent": "ari-clone/0.7.0"})
    if token:
        dl_req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(dl_req, timeout=300) as dl, target.open("wb") as out:
        shutil.copyfileobj(dl, out)
    return target
