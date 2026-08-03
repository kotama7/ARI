"""Closed batch worker for one scheduler-backed OpenROAD experiment.

The registry adapter writes and digest-pins the worker specification and Tcl
program before submitting a C06 job.  This module deliberately uses only the
standard library so the same reviewed bytes can run inside a minimal pinned
OpenROAD container.  It accepts no command text from an MCP caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "ari.openroad-batch-spec/v1"
RESULT_VERSION = "ari.openroad-batch-result/v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_EXPECTED_KEYS = {
    "architecture",
    "executable_digest",
    "executable_path",
    "experiment_digest",
    "metrics_path",
    "result_path",
    "schema_version",
    "tcl_digest",
    "tcl_path",
    "work_dir",
}


class BatchSpecError(ValueError):
    """The immutable batch specification or runtime identity is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _regular_file(path: Path, *, label: str, max_bytes: int) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BatchSpecError(f"{label} is unavailable: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise BatchSpecError(f"{label} must be a regular non-symlink file")
    if info.st_size > max_bytes:
        raise BatchSpecError(f"{label} exceeds its size limit")
    return path


def _absolute_below(value: Any, root: Path, *, label: str) -> Path:
    if not isinstance(value, str) or not value or any(c in value for c in "\x00\n\r"):
        raise BatchSpecError(f"{label} must be an inert absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise BatchSpecError(f"{label} must be an inert absolute path")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BatchSpecError(f"{label} must remain below work_dir") from exc
    return path


def _load_spec(path: Path) -> dict[str, Any]:
    _regular_file(path, label="batch specification", max_bytes=2_000_000)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchSpecError(f"batch specification is invalid JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != _EXPECTED_KEYS:
        raise BatchSpecError("batch specification has an unexpected shape")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise BatchSpecError("batch specification version is unsupported")
    for key in ("executable_digest", "experiment_digest", "tcl_digest"):
        if not isinstance(value.get(key), str) or not _DIGEST_RE.fullmatch(value[key]):
            raise BatchSpecError(f"{key} must be a SHA-256 digest")
    return value


def run(spec_path: Path) -> int:
    """Validate the closed spec, execute OpenROAD without a shell, record result."""

    started_at = _now()
    return_code = 70
    error = ""
    result_path: Path | None = None
    try:
        spec = _load_spec(spec_path)
        work_dir = Path(spec["work_dir"])
        if (
            not work_dir.is_absolute()
            or work_dir.is_symlink()
            or not work_dir.is_dir()
            or work_dir.resolve(strict=True) != work_dir
        ):
            raise BatchSpecError("work_dir must be an existing canonical directory")
        if spec_path.resolve(strict=True).parent != work_dir:
            raise BatchSpecError("batch specification must be stored in work_dir")
        result_path = _absolute_below(spec["result_path"], work_dir, label="result_path")
        tcl_path = _absolute_below(spec["tcl_path"], work_dir, label="tcl_path")
        metrics_path = _absolute_below(
            spec["metrics_path"], work_dir, label="metrics_path"
        )
        executable = Path(spec["executable_path"])
        if not executable.is_absolute() or ".." in executable.parts:
            raise BatchSpecError("executable_path must be absolute")
        _regular_file(executable, label="OpenROAD executable", max_bytes=2_000_000_000)
        _regular_file(tcl_path, label="OpenROAD Tcl program", max_bytes=4_000_000)
        if _digest_file(executable) != spec["executable_digest"]:
            raise BatchSpecError("OpenROAD executable digest drifted")
        if _digest_file(tcl_path) != spec["tcl_digest"]:
            raise BatchSpecError("OpenROAD Tcl program digest drifted")
        if platform.machine() != spec["architecture"]:
            raise BatchSpecError(
                "OpenROAD execution architecture mismatch: "
                f"expected {spec['architecture']}, got {platform.machine()}"
            )
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                str(executable),
                "-no_init",
                "-metrics",
                str(metrics_path.relative_to(work_dir)),
                str(tcl_path.relative_to(work_dir)),
            ],
            cwd=work_dir,
            env={
                "HOME": str(work_dir),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "TMPDIR": str(work_dir),
            },
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return_code = int(completed.returncode)
        if return_code != 0:
            error = f"OpenROAD exited with status {return_code}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    result = {
        "schema_version": RESULT_VERSION,
        "experiment_digest": (
            spec.get("experiment_digest") if "spec" in locals() else None
        ),
        "started_at": started_at,
        "completed_at": _now(),
        "architecture": platform.machine(),
        "executable_digest": (
            spec.get("executable_digest") if "spec" in locals() else None
        ),
        "tcl_digest": spec.get("tcl_digest") if "spec" in locals() else None,
        "return_code": return_code,
        "error": error or None,
    }
    if result_path is None:
        # A malformed result path cannot be trusted.  Emit the report next to
        # the already-pinned spec so scheduler stderr still explains failure.
        result_path = spec_path.parent / "ari-openroad-batch-result.json"
    try:
        temporary = result_path.parent / f".{result_path.name}.tmp-{os.getpid()}"
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, result_path)
    except OSError as exc:
        print(f"cannot write OpenROAD batch result: {exc}", file=sys.stderr)
        return 74
    if error:
        print(error, file=sys.stderr)
    return return_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args(argv)
    return run(args.spec.resolve(strict=True))


if __name__ == "__main__":
    raise SystemExit(main())
