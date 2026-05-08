"""GitHub backend.

Wraps the ``gh`` CLI via subprocess. Two modes:

- ``commit``: ``gh repo create`` + commit ``bundle.tar.gz`` + ``manifest.lock`` +
  auto-generated README into the new repo.
- ``releases``: ``gh release create`` and attach the bundle as an asset.
  Useful for large bundles (>50 MB) where committing a binary is awkward.

Refuses to publish when ``visibility != public`` (FR-GH5) — the GitHub
backend's whole point is open access; a "private gh" bundle is a smell.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _have_gh() -> bool:
    return shutil.which("gh") is not None


def _run(cmd: list[str], *, cwd: Path | None = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def _make_readme(metadata: dict, manifest: dict, ref: str) -> str:
    digest = manifest.get("bundle_sha256", "")
    files = manifest.get("files") or []
    return (
        f"# {metadata.get('title', metadata.get('checkpoint_id', 'ARI artefact'))}\n\n"
        f"Curated experimental artefact repository — {len(files)} file(s).\n\n"
        f"## Reproduce\n\n"
        f"```bash\n"
        f"pip install ari\n"
        f"ari clone {ref} ./reproduce --expect-sha256 {digest}\n"
        f"```\n\n"
        f"## Bundle digest\n\n"
        f"`{digest}` (sha256 of canonical files-only manifest)\n\n"
        f"## Manifest\n\n"
        f"See `manifest.lock` for per-file sha256 entries.\n"
    )


def publish(
    *,
    tar_path: Path,
    manifest: dict,
    metadata: dict,
    visibility: str,
    dry_run: bool,
    tarball_sha256: str,
) -> dict:
    # FR-GH5: gh backend is for public artifacts. We check the *intended*
    # visibility (from publish.yaml, surfaced via manifest['publish']['visibility'])
    # rather than the orchestrator-passed `visibility` (which is always
    # 'staged' on first publish per FR-P5).
    intended = (manifest.get("publish") or {}).get("visibility") or visibility
    if intended not in ("public", "staged") and not (isinstance(intended, str) and intended.startswith("embargoed-until:")):
        raise RuntimeError(
            f"gh backend only supports public visibility (got {intended!r}). "
            "Use ari-registry or zenodo for unlisted/private-token."
        )
    repo = metadata.get("gh_repo") or os.environ.get("ARI_GH_REPO") or ""
    if not repo:
        raise RuntimeError("gh backend: --gh-repo or ARI_GH_REPO is required")
    mode = metadata.get("gh_mode") or os.environ.get("ARI_GH_MODE") or "commit"

    if dry_run:
        return {
            "ref": f"gh:{repo}",
            "tarball_sha256": tarball_sha256,
            "gh_mode": mode,
            "dryrun": True,
        }
    if not _have_gh():
        raise RuntimeError("gh CLI not on PATH. Install gh (https://cli.github.com) and re-run.")

    workdir = Path(metadata.get("gh_workdir") or tar_path.parent / "gh_pub")
    workdir.mkdir(parents=True, exist_ok=True)

    if mode == "releases":
        tag = "v" + (manifest.get("bundle_sha256", "")[:8] or "0.0.1")
        # Repo create is idempotent — ignore already-exists errors.
        try:
            _run(["gh", "repo", "create", repo, "--public", "--clone=false"])
        except Exception:
            pass
        # Create release + attach asset.
        _run(["gh", "release", "create", tag, str(tar_path), "--repo", repo, "--title", tag, "--notes", _make_readme(metadata, manifest, f"gh:{repo}")])
        return {"ref": f"gh:{repo}", "tarball_sha256": tarball_sha256, "gh_mode": "releases", "tag": tag}

    # commit mode: clone (or init), drop bundle + manifest + README, push.
    repo_dir = workdir / "repo"
    if not repo_dir.exists():
        try:
            _run(["gh", "repo", "create", repo, "--public", "--clone=false"])
        except Exception:
            pass
        _run(["gh", "repo", "clone", repo, str(repo_dir)])
    # Copy artefacts.
    shutil.copy2(tar_path, repo_dir / "bundle.tar.gz")
    (repo_dir / "manifest.lock").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (repo_dir / "README.md").write_text(_make_readme(metadata, manifest, f"gh:{repo}"), encoding="utf-8")
    _run(["git", "add", "-A"], cwd=repo_dir)
    try:
        _run(["git", "commit", "-m", f"ari: publish curated bundle {manifest.get('bundle_sha256','')[:16]}"], cwd=repo_dir)
    except Exception:
        pass  # nothing to commit on re-publish of identical content
    _run(["git", "push"], cwd=repo_dir)
    return {"ref": f"gh:{repo}", "tarball_sha256": tarball_sha256, "gh_mode": "commit"}


def promote(
    *, ref: str, target: str, extra: dict, dry_run: bool,
) -> dict:
    if dry_run:
        return {"visibility": target, "dryrun": True}
    if target == "public":
        repo = ref[len("gh:"):] if ref.startswith("gh:") else ref
        if _have_gh():
            try:
                _run(["gh", "repo", "edit", repo, "--visibility", "public"])
            except Exception as e:
                # Already public is fine; surface real errors.
                if "already" not in str(e).lower():
                    raise
    return {"visibility": target}
