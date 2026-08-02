"""EAR curator: turn `{checkpoint}/ear/` into a publish-ready
`{checkpoint}/ear_published/` subset, plus a manifest.lock with sha256
digests.

Design constraints (P1/P2):
- No LLM calls. Behaviour is fully deterministic given (ear/, publish.yaml).
- ari-core stays free of experiment-specific knowledge: the meaning of
  publish.yaml lives here, in the transform skill.
- Built-in deny patterns are applied unconditionally and outrank any
  user `include`. They prevent accidental publication of `.env*`,
  secrets, private keys, etc.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# yaml is a transitive dep of ari-core; importing lazily keeps the curator
# importable in environments where pyyaml is not yet installed (used by
# the schema-only tests).
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - import guard
    yaml = None  # noqa: N816


# ---------------------------------------------------------------------------
# Built-in deny: applied unconditionally, even if `include` matches.
# The list is small on purpose — anything more aggressive belongs in user
# `exclude`. Keep glob syntax compatible with fnmatch (pathlib-style **).
# ---------------------------------------------------------------------------
BUILTIN_DENY: tuple[str, ...] = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/secrets/**",
    "secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa",
    "**/id_ed25519",
)


class CurateError(RuntimeError):
    """Raised when curation hits a hard failure (e.g. file size cap)."""


@dataclass
class CurateResult:
    """Result of curating an EAR.

    Attributes:
        ear_published_dir: absolute path to the curated tree.
        manifest_path: absolute path to manifest.lock.
        bundle_sha256: sha256 of the canonical manifest (root digest).
        included_files: relative paths actually copied.
        excluded_count: number of files that matched include but were
            removed by built-in deny or user exclude. Paths are NOT
            recorded — only the count, by design (FR-C6).
        skipped: Compatibility field; always False because an absent
            publish.yaml uses the built-in reproducibility allowlist.
    """

    ear_published_dir: Path
    manifest_path: Path
    bundle_sha256: str
    included_files: list[str]
    excluded_count: int
    skipped: bool


# ---------------------------------------------------------------------------
# Glob matching
# ---------------------------------------------------------------------------


def _normalize_rel(path: Path) -> str:
    """POSIX-style relative path string for matching."""
    return path.as_posix()


def _match_any(rel: str, patterns: Iterable[str]) -> bool:
    """Match a relative POSIX path against fnmatch globs.

    pathlib-style ``**`` is converted into a recursive match by also
    trying every ancestor segment. We deliberately keep this simple —
    the alternative (pathlib.PurePath.match) does not handle leading
    ``**/`` reliably across Python versions.
    """
    for pat in patterns:
        if not pat:
            continue
        # Direct match
        if fnmatch.fnmatchcase(rel, pat):
            return True
        # Implicit prefix match for **/ patterns (`**/secrets/**` should
        # also match `secrets/foo.txt` at the tree root).
        if pat.startswith("**/") and fnmatch.fnmatchcase(rel, pat[3:]):
            return True
        # Trailing /** matches the directory itself (`secrets/**` should
        # also match anything below `secrets/`).
        if pat.endswith("/**"):
            head = pat[:-3]
            if rel == head or rel.startswith(head + "/"):
                return True
    return False


def _walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise CurateError(f"symbolic EAR path refused: {path.relative_to(root)}")
        if path.is_file():
            files.append(path)
    return files


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_role(relative: str) -> str:
    if relative == "locks/SKILLS.lock":
        return "skills-lock"
    if relative == "catalog/CATALOG.lock":
        return "catalog-lock"
    if relative.startswith("catalog/cassettes/") or relative.startswith(
        "catalog/raw-cassettes/"
    ):
        return "cassette"
    if relative.startswith("admission/"):
        return "admission"
    if relative.startswith("artifacts/mcp-results/"):
        return "result-envelope-artifact"
    if relative.startswith("contracts/"):
        return "science-contract"
    if relative == "evidence.index.json":
        return "evidence-index"
    return "ear-output"


def _verify_evidence_index(ear: Path) -> dict | None:
    path = ear / "evidence.index.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurateError(f"invalid evidence.index.json: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "ari.ear-evidence-index/v1":
        raise CurateError("unsupported evidence index schema")
    digest = value.get("index_digest")
    unsigned = dict(value)
    unsigned.pop("index_digest", None)
    encoded = (
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if digest != expected:
        raise CurateError("evidence index digest mismatch")
    records = value.get("records")
    if not isinstance(records, list):
        raise CurateError("evidence index records must be a list")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise CurateError("evidence index record must be an object")
        relative = str(record.get("path") or "")
        candidate = ear / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(ear.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise CurateError(f"evidence path escapes EAR: {relative}") from exc
        if relative in seen or candidate.is_symlink() or not candidate.is_file():
            raise CurateError(f"evidence path missing, duplicate, or symbolic: {relative}")
        seen.add(relative)
        if record.get("digest") != "sha256:" + _sha256_file(candidate):
            raise CurateError(f"evidence digest mismatch: {relative}")
        if record.get("size_bytes") != candidate.stat().st_size:
            raise CurateError(f"evidence size mismatch: {relative}")
    return value


# ---------------------------------------------------------------------------
# publish.yaml loading
# ---------------------------------------------------------------------------


def _load_publish_yaml(path: Path) -> dict:
    if yaml is None:  # pragma: no cover - import guard
        raise CurateError("pyyaml is required for curate but not installed")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise CurateError(f"{path} must be a YAML mapping at the top level")
    # Defaults
    raw.setdefault("include", [])
    raw.setdefault("exclude", [])
    raw.setdefault("max_file_mb", 100)
    raw.setdefault("visibility", "staged")
    raw.setdefault("required", False)
    raw.setdefault("auto_promote", False)
    if not isinstance(raw["include"], list) or not isinstance(raw["exclude"], list):
        raise CurateError("`include` and `exclude` must be lists of glob strings")
    return raw


# Default publish.yaml content used when the author hasn't supplied one.
# Tuned for the ORS reproducibility flow: include everything a re-runner
# needs to rebuild + execute (reproduce.sh + code/ + data/ + environment),
# include immutable federated-tool provenance under catalog/, and exclude
# human-only docs and the figures/ directory (figures are outputs).
_DEFAULT_PUBLISH_YAML: dict = {
    "include": [
        "reproduce.sh",
        "environment.json",
        "code/**",
        "data/**",
        "scripts/**",
        "configs/**",
        "catalog/**",
        "locks/**",
        "contracts/**",
        "admission/**",
        "artifacts/**",
        "evidence.index.json",
    ],
    "exclude": [],
    "max_file_mb": 100,
    "visibility": "staged",
    "required": False,
    "auto_promote": False,
    "_default_generated": True,
}


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


def curate(checkpoint_dir: str | Path) -> CurateResult:
    """Curate an EAR according to its publish.yaml.

    Layout assumed:
        <checkpoint>/ear/                   — populated by generate_ear
        <checkpoint>/ear/publish.yaml       — author-controlled allowlist (optional)
        <checkpoint>/ear_published/         — written by this function
        <checkpoint>/ear_published/manifest.lock — written by this function

    Returns:
        CurateResult. ``skipped`` is False for both authored and default policy.

    Raises:
        CurateError: on any hard failure (size cap, schema, missing ear/).
    """
    ckpt = Path(checkpoint_dir).resolve()
    ear = ckpt / "ear"
    if not ear.is_dir():
        raise CurateError(f"ear directory not found: {ear}")

    publish_yaml = ear / "publish.yaml"
    out_dir = ckpt / "ear_published"

    if publish_yaml.exists():
        cfg = _load_publish_yaml(publish_yaml)
    else:
        # No author-supplied publish.yaml — fall back to a built-in default
        # tuned for ORS reproducibility (include reproduce.sh + code/ + data/
        # + environment.json + federated catalog evidence). Without this fallback,
        # ear_curate skips and
        # the downstream ear_publish / ors_seed_sandbox chain has nothing
        # to ship to the sandbox.
        cfg = dict(_DEFAULT_PUBLISH_YAML)

    evidence_index = _verify_evidence_index(ear)

    # Decide which files survive each filter.
    all_files = _walk_files(ear)
    # publish.yaml itself is metadata, never copied into ear_published/.
    if publish_yaml.exists():
        all_files = [p for p in all_files if p.resolve() != publish_yaml.resolve()]

    include_globs: list[str] = list(cfg["include"])
    exclude_globs: list[str] = list(cfg["exclude"])
    max_bytes = int(float(cfg["max_file_mb"]) * 1024 * 1024)

    chosen: list[Path] = []
    excluded_count = 0
    for p in all_files:
        rel = _normalize_rel(p.relative_to(ear))
        if not _match_any(rel, include_globs):
            continue  # not in allowlist (silently dropped — matches "not requested")
        # Built-in deny outranks include (FR-C6).
        if _match_any(rel, BUILTIN_DENY):
            excluded_count += 1
            continue
        # User exclude.
        if _match_any(rel, exclude_globs):
            excluded_count += 1
            continue
        chosen.append(p)

    # FR-C4: explicit error on size violations (no silent drops).
    over = [p for p in chosen if p.stat().st_size > max_bytes]
    if over:
        names = ", ".join(_normalize_rel(p.relative_to(ear)) for p in over[:5])
        raise CurateError(
            f"max_file_mb={cfg['max_file_mb']} violated by {len(over)} file(s): {names}"
        )

    # ---- Atomic write ----
    # We build into a tmp dir first, then swap. If anything raises
    # mid-copy, the previous ear_published/ stays intact.
    tmp_dir = ckpt / "ear_published.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    file_records: list[dict] = []
    for p in sorted(chosen, key=lambda x: x.relative_to(ear).as_posix()):
        rel = p.relative_to(ear)
        dest = tmp_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        file_records.append(
            {
                "path": rel.as_posix(),
                "size": p.stat().st_size,
                "sha256": _sha256_file(p),
                "role": _file_role(rel.as_posix()),
            }
        )

    # Canonical bundle digest depends ONLY on file content + relative paths.
    # We deliberately exclude created_at, visibility and other metadata so
    # the digest is reproducible: re-curating an unchanged ear/ with the
    # same publish.yaml on a different machine yields the same value. This
    # is the property that lets the paper-baked digest be a permanent
    # source of truth.
    canonical_payload = {
        "version": 2,
        "files": [
            {
                "path": r["path"],
                "sha256": r["sha256"],
                "size": r["size"],
                "role": r["role"],
            }
            for r in file_records
        ],
    }
    canonical = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    bundle_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    policy_payload = {
        "include": include_globs,
        "exclude": exclude_globs,
        "builtin_deny": list(BUILTIN_DENY),
        "max_file_mb": cfg["max_file_mb"],
    }
    role_records = {
        role: [
            {"path": record["path"], "sha256": record["sha256"]}
            for record in file_records
            if record["role"] == role
        ]
        for role in (
            "skills-lock",
            "catalog-lock",
            "result-envelope-artifact",
            "cassette",
            "admission",
            "science-contract",
        )
    }
    admission_status = (
        "complete"
        if role_records["skills-lock"]
        and (
            role_records["catalog-lock"]
            or not role_records["cassette"]
        )
        else "incomplete"
    )
    deterministic_lock = {
        **canonical_payload,
        "bundle_sha256": bundle_digest,
        "policy_digest": _canonical_digest(policy_payload),
        "evidence_index_digest": (
            evidence_index.get("index_digest") if evidence_index else None
        ),
        "evidence": role_records,
        "admission_status": admission_status,
    }
    manifest = {
        "schema_version": "ari.ear-manifest/v2",
        "version": 2,
        "checkpoint_id": ckpt.name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "publish": {
            "visibility": cfg["visibility"],
            "required": bool(cfg["required"]),
            "auto_promote": bool(cfg["auto_promote"]),
            "max_file_mb": cfg["max_file_mb"],
            "license": cfg.get("license"),
            "backend": cfg.get("backend", "ari-registry"),
        },
        "files": file_records,
        "excluded_count": excluded_count,
        "bundle_sha256": bundle_digest,
        "policy_digest": deterministic_lock["policy_digest"],
        "evidence_index_digest": deterministic_lock["evidence_index_digest"],
        "evidence": role_records,
        "admission_status": admission_status,
        "lock_digest": _canonical_digest(deterministic_lock),
    }

    manifest_path = tmp_dir / "manifest.lock"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    # Recoverable two-phase directory swap.  A prior good curated bundle is
    # restored if the final rename fails; publish failures never touch either.
    backup_dir = ckpt / "ear_published.previous"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    moved_previous = False
    try:
        if out_dir.exists():
            os.replace(out_dir, backup_dir)
            moved_previous = True
        os.replace(tmp_dir, out_dir)
    except Exception:
        if moved_previous and backup_dir.exists() and not out_dir.exists():
            os.replace(backup_dir, out_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    return CurateResult(
        ear_published_dir=out_dir,
        manifest_path=out_dir / "manifest.lock",
        bundle_sha256=bundle_digest,
        included_files=[r["path"] for r in file_records],
        excluded_count=excluded_count,
        skipped=False,
    )


def curate_to_dict(checkpoint_dir: str | Path) -> dict:
    """Curate and return a JSON-friendly summary suitable for MCP tool returns."""
    res = curate(checkpoint_dir)
    out = asdict(res)
    out["ear_published_dir"] = str(res.ear_published_dir)
    out["manifest_path"] = str(res.manifest_path)
    return out


__all__ = [
    "BUILTIN_DENY",
    "CurateError",
    "CurateResult",
    "curate",
    "curate_to_dict",
]
