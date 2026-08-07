#!/usr/bin/env python3
"""Run and retain the revision-bound Manuscript Complete release gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).with_name(
    "manuscript_complete_release_gates.json"
)
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True
    ).strip()


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "ari.manuscript-release-gates/v1":
        raise ValueError("unknown Manuscript Complete release-gate schema")
    topologies = value.get("required_topologies")
    if not isinstance(topologies, list) or len(topologies) != 4:
        raise ValueError("release manifest must name exactly four topologies")
    if len(set(topologies)) != len(topologies):
        raise ValueError("release topology IDs must be unique")
    injections = value.get("failure_injections")
    if not isinstance(injections, list) or len(injections) != 13:
        raise ValueError("release manifest must retain all 13 failure injections")
    injection_ids = [str(item.get("id") or "") for item in injections]
    if not all(injection_ids) or len(set(injection_ids)) != len(injection_ids):
        raise ValueError("release failure-injection IDs must be unique")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("release manifest must contain executable checks")
    check_ids = [str(item.get("id") or "") for item in checks]
    if not all(check_ids) or len(set(check_ids)) != len(check_ids):
        raise ValueError("release check IDs must be unique")
    for check in checks:
        if not isinstance(check.get("argv"), list) or not check["argv"]:
            raise ValueError("every release check requires argv")
    return value


def _test_function_exists(node_id: str) -> bool:
    path_text, separator, function = node_id.partition("::")
    if not separator or not function.startswith("test_"):
        return False
    path = REPO_ROOT / path_text
    if not path.is_file():
        return False
    pattern = re.compile(
        rf"^(?:async\s+)?def\s+{re.escape(function)}\s*\(", re.MULTILINE
    )
    return bool(pattern.search(path.read_text(encoding="utf-8")))


def _validate_test_ownership(manifest: dict[str, Any]) -> tuple[str, ...]:
    node_ids = [str(manifest["topology_test"])]
    for injection in manifest["failure_injections"]:
        node_ids.extend(str(item) for item in injection.get("tests") or ())
    node_ids.extend(str(item) for item in manifest.get("migration_tests") or ())
    missing = tuple(sorted({item for item in node_ids if not _test_function_exists(item)}))
    if missing:
        raise ValueError("release manifest names missing tests: " + ", ".join(missing))
    return tuple(dict.fromkeys(node_ids))


def _source_identity() -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    if not FULL_SHA.fullmatch(commit):
        raise RuntimeError("release source is not a full Git revision")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "commit": commit,
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "branch": _git("branch", "--show-current"),
        "clean": not bool(status),
        "dirty_paths": status.splitlines(),
    }


def _run_check(
    check: dict[str, Any],
    *,
    output_dir: Path,
    environment: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    check_id = str(check["id"])
    argv = [
        sys.executable if str(item) == "{python}" else str(item)
        for item in check["argv"]
    ]
    started_at = _utc_now()
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=environment,
        text=False,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    duration = time.monotonic() - started
    stdout_path = output_dir / "logs" / f"{check_id}.stdout.log"
    stderr_path = output_dir / "logs" / f"{check_id}.stderr.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    return {
        "id": check_id,
        "argv": argv,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_seconds": round(duration, 6),
        "exit_code": completed.returncode,
        "status": "passed" if completed.returncode == 0 else "failed",
        "stdout": {
            "path": stdout_path.relative_to(output_dir).as_posix(),
            "digest": _digest(completed.stdout),
            "size_bytes": len(completed.stdout),
        },
        "stderr": {
            "path": stderr_path.relative_to(output_dir).as_posix(),
            "digest": _digest(completed.stderr),
            "size_bytes": len(completed.stderr),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve(strict=True)
    manifest = _load_manifest(manifest_path)
    owned_tests = _validate_test_ownership(manifest)
    source = _source_identity()
    if args.require_clean and not source["clean"]:
        raise RuntimeError("release evidence requires a clean committed worktree")
    if args.require_ci and os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("release evidence requires the GitHub Actions environment")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    core_path = str(REPO_ROOT / "ari-core")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (core_path, environment.get("PYTHONPATH", "")) if item
    )
    environment.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    check_results = []
    for check in manifest["checks"]:
        result = _run_check(
            check,
            output_dir=output_dir,
            environment=environment,
            timeout_seconds=args.timeout_seconds,
        )
        check_results.append(result)
        if result["status"] != "passed" and not args.keep_going:
            break

    all_passed = (
        len(check_results) == len(manifest["checks"])
        and all(item["status"] == "passed" for item in check_results)
    )
    github = {
        "actions": os.environ.get("GITHUB_ACTIONS") == "true",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "ref": os.environ.get("GITHUB_REF", ""),
    }
    report: dict[str, Any] = {
        "schema_version": "ari.manuscript-release-evidence/v1",
        "generated_at": _utc_now(),
        "status": "passed" if all_passed else "failed",
        "source": source,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "github": github,
        "manifest": {
            "path": manifest_path.relative_to(REPO_ROOT).as_posix(),
            "digest": _digest(manifest_path.read_bytes()),
        },
        "required_topologies": manifest["required_topologies"],
        "topology_test": manifest["topology_test"],
        "failure_injections": manifest["failure_injections"],
        "migration_tests": manifest.get("migration_tests") or [],
        "owned_test_count": len(owned_tests),
        "checks": check_results,
        "release_eligible": bool(
            all_passed
            and source["clean"]
            and (not args.require_ci or github["actions"])
        ),
    }
    report["report_digest"] = _digest(_json_bytes(report))
    (output_dir / "release_evidence.json").write_bytes(_json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="release-gate manifest",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="directory for the JSON report and digest-bound logs",
    )
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--require-ci", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1_200)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    try:
        report = run(args)
    except Exception as exc:
        print(f"manuscript release evidence failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "passed" and report["release_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
