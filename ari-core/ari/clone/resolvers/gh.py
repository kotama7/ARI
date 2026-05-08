"""gh: resolver — fetch a curated bundle from a GitHub repo or release.

Tries the simplest path first: a raw download of bundle.tar.gz from the
default branch. Falls back to ``git clone --depth 1`` if that 404s.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


def resolve(
    ref: str,
    workdir: Path,
    *,
    registry: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    if not ref.startswith("gh:"):
        raise ValueError(f"gh resolver: not a gh: ref: {ref}")
    repo = ref[len("gh:"):]

    # Direct raw download (covers the common 'commit mode' bundle layout).
    raw_urls = [
        f"https://raw.githubusercontent.com/{repo}/main/bundle.tar.gz",
        f"https://raw.githubusercontent.com/{repo}/master/bundle.tar.gz",
    ]
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "bundle.tar.gz"
    for url in raw_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ari-clone/0.7.0"})
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=60) as resp, target.open("wb") as out:
                shutil.copyfileobj(resp, out)
            return target
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        except Exception:
            continue

    # Fallback: git clone --depth 1 and pull bundle.tar.gz from the working tree.
    git = shutil.which("git")
    if not git:
        raise RuntimeError(f"gh resolver: bundle.tar.gz not found at raw URLs and git not on PATH")
    repo_dir = workdir / "repo"
    subprocess.run(
        [git, "clone", "--depth", "1", f"https://github.com/{repo}.git", str(repo_dir)],
        check=True, capture_output=True,
    )
    src = repo_dir / "bundle.tar.gz"
    if not src.exists():
        raise RuntimeError(f"gh resolver: {repo} default branch has no bundle.tar.gz")
    shutil.copy2(src, target)
    shutil.rmtree(repo_dir, ignore_errors=True)
    return target
