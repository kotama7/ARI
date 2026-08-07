#!/usr/bin/env python3
"""Build a machine-readable local Constitutional ARI-RQGM test artifact.

This script is intentionally offline and deterministic apart from runtime
metadata and pytest duration.  It never claims that a dirty worktree is a
published artifact: the manifest records both the Git revision and a
content hash over every selected source/test/prompt file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "ari-core"
DEFAULT_OUTPUT = ROOT / "report" / "shared" / "artifact"

_FOCUSED_TESTS = sorted(
    {
        *CORE.glob("tests/test_rqgm_*.py"),
        *CORE.glob("tests/test_claim_gate_*.py"),
    }
)

SELECTORS = {
    "focused": [
        sys.executable,
        "-m",
        "pytest",
        *(str(path.relative_to(CORE)) for path in _FOCUSED_TESTS),
        "-q",
    ],
    "full": [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "-q",
        "-rxX",
        "--ignore=tests/skills",
    ],
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=False,
    )


def _git(*args: str) -> str:
    result = _run(["git", *args])
    return result.stdout.strip() if result.returncode == 0 else ""


def _selected_files() -> list[Path]:
    roots = [
        CORE / "ari",
        CORE / "tests",
    ]
    out: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            out.append(path)
    out.extend([
        ROOT / "requirements.lock",
        CORE / "pyproject.toml",
        Path(__file__).resolve(),
    ])
    return sorted({p.resolve() for p in out if p.is_file()})


def _source_manifest() -> tuple[list[dict], str]:
    entries = [
        {
            "path": str(path.relative_to(ROOT)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in _selected_files()
    ]
    encoded = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return entries, hashlib.sha256(encoded).hexdigest()


def _collect(selector: str, out_dir: Path) -> dict:
    command = [
        *(arg for arg in SELECTORS[selector] if arg != "-q"),
        "--collect-only",
        "-q",
    ]
    result = _run(command, cwd=CORE)
    log_path = out_dir / f"{selector}-collect.log"
    log_path.write_text(result.stdout, encoding="utf-8")
    test_ids = sorted({
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("<", "="))
    })
    list_path = out_dir / f"{selector}-tests.txt"
    list_path.write_text(
        "".join(f"{test_id}\n" for test_id in test_ids),
        encoding="utf-8",
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "collected_test_ids": len(test_ids),
        "list_sha256": _sha256(list_path),
        "log_sha256": _sha256(log_path),
    }


def _execute(selector: str, out_dir: Path) -> dict:
    command = SELECTORS[selector]
    result = _run(command, cwd=CORE)
    log_path = out_dir / f"{selector}-run.log"
    log_path.write_text(result.stdout, encoding="utf-8")
    return {
        "command": command,
        "returncode": result.returncode,
        "log_sha256": _sha256(log_path),
        "summary_tail": result.stdout.splitlines()[-8:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="artifact directory (default: report/shared/artifact)",
    )
    parser.add_argument(
        "--run",
        choices=("none", "focused", "full", "all"),
        default="none",
        help="also execute tests after collecting their exact IDs",
    )
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    files, source_digest = _source_manifest()
    (out_dir / "source-files.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    freeze = _run([sys.executable, "-m", "pip", "freeze"])
    (out_dir / "python-packages.txt").write_text(
        freeze.stdout, encoding="utf-8"
    )
    authority = _run(
        [sys.executable, "-m", "ari.rqgm.authority_manifest"], cwd=CORE
    )
    authority_path = out_dir / "authority-matrix.json"
    authority_path.write_text(authority.stdout, encoding="utf-8")

    collection = {
        name: _collect(name, out_dir) for name in ("focused", "full")
    }
    execution = {}
    selected = (
        ("focused", "full")
        if args.run == "all"
        else ((args.run,) if args.run != "none" else ())
    )
    for name in selected:
        execution[name] = _execute(name, out_dir)

    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    manifest = {
        "artifact": "constitutional-ari-rqgm-local-reproduction",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "publication_status": "local-unpublished",
        "git": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "working_tree_dirty": bool(status),
        },
        "source_manifest_sha256": source_digest,
        "source_file_count": len(files),
        "requirements_lock_sha256": _sha256(ROOT / "requirements.lock"),
        "runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "pythonhashseed": "0",
            "pip_freeze_returncode": freeze.returncode,
            "python_packages_sha256": _sha256(
                out_dir / "python-packages.txt"
            ),
        },
        "authority_matrix": {
            "command": [
                sys.executable,
                "-m",
                "ari.rqgm.authority_manifest",
            ],
            "returncode": authority.returncode,
            "sha256": _sha256(authority_path),
        },
        "collection": collection,
        "execution": execution,
        "limitations": [
            "This directory is not an immutable public tag or DOI archive.",
            "A dirty tree is identified by content hashes, not by Git SHA alone.",
            "No model calls or scientific-quality experiments are run here.",
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "manifest": str(manifest_path),
        "source_manifest_sha256": source_digest,
        "collection": collection,
        "execution_returncodes": {
            name: result["returncode"] for name, result in execution.items()
        },
    }, ensure_ascii=False, indent=2))
    return max(
        [authority.returncode]
        + [result["returncode"] for result in execution.values()]
    )


if __name__ == "__main__":
    raise SystemExit(main())
