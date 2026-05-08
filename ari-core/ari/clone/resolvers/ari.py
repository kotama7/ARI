"""ari:// resolver — fetch a curated bundle from a configured ari-registry.

Config (FR-RG7):
    ~/.ari/registries.yaml:
        registries:
          - name: default
            url: https://registry.example.com
            token: ${ARI_REGISTRY_TOKEN}

Refs:
    ari://<id>                   — try each configured registry in order
    ari://<registry-name>/<id>   — pin to a named registry
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .https import resolve as _https_resolve  # reuse the streaming download


def _load_registries(name_filter: Optional[str] = None) -> list[dict]:
    paths = []
    if os.environ.get("ARI_REGISTRIES_FILE"):
        paths.append(Path(os.environ["ARI_REGISTRIES_FILE"]))
    paths.append(Path.home() / ".ari" / "registries.yaml")
    for p in paths:
        if p.exists():
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                regs = data.get("registries") or []
                if name_filter:
                    regs = [r for r in regs if r.get("name") == name_filter]
                if regs:
                    return regs
            except Exception:
                continue
    url = os.environ.get("ARI_REGISTRY_URL")
    if url:
        return [{"name": "default", "url": url, "token": os.environ.get("ARI_REGISTRY_TOKEN", "")}]
    return []


def _expand_token(token: str) -> str:
    if not token:
        return ""
    if token.startswith("$"):
        return os.environ.get(token[1:], "") or ""
    if token.startswith("${") and token.endswith("}"):
        return os.environ.get(token[2:-1], "") or ""
    return token


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    if not ref.startswith("ari://"):
        raise ValueError(f"ari resolver: not an ari:// ref: {ref}")

    rest = ref[len("ari://"):]
    if "/" in rest:
        reg_pin, artifact_id = rest.split("/", 1)
        registries = _load_registries(reg_pin)
    else:
        artifact_id = rest
        registries = _load_registries(registry)

    if not registries:
        raise RuntimeError(
            "no ari-registry configured. Set ARI_REGISTRY_URL or write ~/.ari/registries.yaml"
        )

    last_err: Optional[Exception] = None
    for reg in registries:
        url = str(reg.get("url", "")).rstrip("/")
        if not url:
            continue
        # HEAD first to confirm existence + visibility before downloading.
        head_url = f"{url}/artifact/{artifact_id}"
        head_req = urllib.request.Request(head_url, method="HEAD")
        eff_token = token or _expand_token(str(reg.get("token", "")))
        if eff_token:
            head_req.add_header("Authorization", f"Bearer {eff_token}")
        try:
            urllib.request.urlopen(head_req, timeout=20)
        except Exception as e:
            last_err = e
            continue
        # GET — reuse the https resolver so streaming/timeout/auth all match.
        return _https_resolve(head_url, workdir, registry=None, token=eff_token)

    raise RuntimeError(
        f"ari:// could not resolve {ref!r}: tried {len(registries)} registries; last error: {last_err}"
    )
