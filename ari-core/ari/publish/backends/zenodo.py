r"""Zenodo backend.

Uses the REST API directly (no zenodo SDK) to keep the dependency surface
minimal. Authentication via ``ZENODO_TOKEN`` env var; ``ZENODO_SANDBOX=true``
points the client at sandbox.zenodo.org for integration testing.

Initial publish creates a *draft* deposition (no DOI yet); ``promote()``
calls the publish API to mint the DOI. ``\codeavailability{<doi>}`` is
filled in by paper-skill's finalize stage post-promote.

Embargoes are honoured via ``publish.yaml.visibility = embargoed-until:<date>``.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


def _api_base() -> str:
    if os.environ.get("ZENODO_SANDBOX", "").lower() in ("1", "true", "yes"):
        return "https://sandbox.zenodo.org/api"
    return "https://zenodo.org/api"


def _token() -> str:
    tok = os.environ.get("ZENODO_TOKEN", "")
    if not tok:
        raise RuntimeError("ZENODO_TOKEN env var is required for the zenodo backend")
    return tok


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"zenodo {method} {url} → {e.code}: {body_str[:300]}") from e


def _build_metadata(metadata: dict, manifest: dict) -> dict:
    pub = manifest.get("publish") or {}
    license_id = pub.get("license") or metadata.get("license") or "MIT"
    visibility = pub.get("visibility", "public")
    creators = metadata.get("creators") or [{"name": metadata.get("author", "ARI Author")}]
    desc = metadata.get("description") or "Curated experimental artefact repository for the accompanying paper."

    md: dict = {
        "title": metadata.get("title") or f"ARI artefact {metadata.get('checkpoint_id', '')}",
        "upload_type": "software",
        "description": desc,
        "creators": creators,
        "license": license_id,
        "keywords": metadata.get("keywords") or ["ari", "reproducibility"],
    }
    # Embargo: visibility="embargoed-until:YYYY-MM-DD"
    if isinstance(visibility, str) and visibility.startswith("embargoed-until:"):
        date_str = visibility[len("embargoed-until:"):].strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            md["access_right"] = "embargoed"
            md["embargo_date"] = date_str
        except ValueError:
            md["access_right"] = "open"
    elif visibility == "public":
        md["access_right"] = "open"
    else:
        md["access_right"] = "restricted"
    return {"metadata": md}


def publish(
    *,
    tar_path: Path,
    manifest: dict,
    metadata: dict,
    visibility: str,
    dry_run: bool,
    tarball_sha256: str,
) -> dict:
    if dry_run:
        return {
            "ref": f"doi:(dryrun)/{tarball_sha256[:16]}",
            "tarball_sha256": tarball_sha256,
            "deposition_id": "dryrun",
            "dryrun": True,
            "doi": "",
        }
    base = _api_base()
    md = _build_metadata(metadata, manifest)

    # 1) create draft deposition
    dep = _http(
        "POST",
        f"{base}/deposit/depositions",
        body=json.dumps(md).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    deposition_id = dep["id"]
    bucket = dep["links"]["bucket"]

    # 2) upload bundle.tar.gz to the deposition's bucket
    with tar_path.open("rb") as f:
        body = f.read()
    _http("PUT", f"{bucket}/bundle.tar.gz", body=body, headers={"Content-Type": "application/octet-stream"})

    # 3) upload manifest.lock for transparency
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    _http("PUT", f"{bucket}/manifest.lock", body=manifest_bytes, headers={"Content-Type": "application/json"})

    return {
        "ref": f"doi:zenodo/draft/{deposition_id}",  # final doi minted on promote
        "tarball_sha256": tarball_sha256,
        "deposition_id": str(deposition_id),
        "doi": "",   # not minted until promote()
        "dryrun": False,
        "sandbox": _api_base().startswith("https://sandbox"),
    }


def promote(
    *, ref: str, target: str, extra: dict, dry_run: bool,
) -> dict:
    if dry_run:
        return {"visibility": target, "doi": f"10.5281/zenodo.dryrun.{(extra or {}).get('deposition_id','x')}", "dryrun": True}
    deposition_id = (extra or {}).get("deposition_id") or ref.split("/")[-1]
    base = _api_base()
    out = _http("POST", f"{base}/deposit/depositions/{deposition_id}/actions/publish", body=b"")
    doi = out.get("doi") or out.get("metadata", {}).get("doi") or ""
    return {"visibility": target, "doi": doi, "deposition_id": str(deposition_id)}
