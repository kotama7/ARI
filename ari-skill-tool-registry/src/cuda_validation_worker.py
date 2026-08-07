#!/usr/bin/python3
"""Compile and execute ARI's fixed CUDA self-test in a closed SLURM workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def _regular(path: Path, *, executable: bool = False) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("CUDA validation input is not a regular file")
    if executable and not os.access(resolved, os.X_OK):
        raise ValueError("CUDA validation executable is not executable")
    return resolved


def _output_path(value: str, work_dir: Path) -> Path:
    path = Path(value)
    parent = path.parent.resolve(strict=True)
    parent.relative_to(work_dir)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("CUDA validation output path is unsafe")
    return path


def _validate_result(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "verdict",
        "device_count",
        "devices",
    }:
        raise ValueError("CUDA self-test result shape is invalid")
    devices = value.get("devices")
    if (
        value.get("schema_version") != "ari.cuda-self-test/v1"
        or value.get("verdict") != "pass"
        or not isinstance(value.get("device_count"), int)
        or not isinstance(devices, list)
        or value["device_count"] != len(devices)
        or not devices
    ):
        raise ValueError("CUDA self-test did not pass")
    expected_keys = {
        "device_index",
        "name",
        "compute_capability",
        "memory_bytes",
        "case_count",
        "maximum_absolute_error",
        "checksum",
        "repeated_execution_equal",
        "negative_control_detected",
    }
    for index, item in enumerate(devices):
        if (
            not isinstance(item, dict)
            or set(item) != expected_keys
            or item.get("device_index") != index
            or item.get("case_count") != 4
            or item.get("maximum_absolute_error", 1) > 1e-6
            or item.get("repeated_execution_equal") is not True
            or item.get("negative_control_detected") is not True
        ):
            raise ValueError("CUDA device validation result is invalid")
    return value


_ARCHITECTURE = re.compile(r"\Asm_[0-9]{2,3}\Z")


def _architecture(value: str) -> str:
    if not _ARCHITECTURE.match(value):
        raise argparse.ArgumentTypeError(
            "CUDA architecture must be sm_<digits>"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-digest", required=True)
    parser.add_argument("--nvcc", required=True)
    parser.add_argument("--nvcc-digest", required=True)
    # An allowlist by shape, not by value. The point of constraining this is
    # that it reaches nvcc's command line, so it must not be arbitrary text; it
    # was never that only sm_70 is a real architecture. Pinning the single value
    # here made the self-test unrunnable on any device the site actually has,
    # which is not a safety property -- it is a validation that cannot run.
    parser.add_argument("--architecture", required=True, type=_architecture)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--build-log", required=True)
    args = parser.parse_args(argv)

    work_dir = Path(args.work_dir).resolve(strict=True)
    source = _regular(Path(args.source))
    nvcc = _regular(Path(args.nvcc), executable=True)
    if _digest(source) != args.source_digest or _digest(nvcc) != args.nvcc_digest:
        raise ValueError("CUDA source or compiler digest differs")
    result_path = _output_path(args.result, work_dir)
    build_log = _output_path(args.build_log, work_dir)
    binary = work_dir / "cuda-self-test"
    if binary.exists() and (binary.is_symlink() or not binary.is_file()):
        raise ValueError("CUDA self-test binary path is unsafe")

    # The compiler's own directory, taken from the compiler that was pinned and
    # digest-checked above, rather than a fixed toolkit path. The literal
    # /usr/local/cuda-12.9/bin named one machine's install; anywhere else it was
    # a PATH entry pointing at nothing, and the only reason that was survivable
    # is that nvcc is invoked by absolute path.
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": f"{nvcc.parent}:/usr/local/bin:/usr/bin:/bin",
    }
    compile_result = subprocess.run(
        [
            str(nvcc),
            "-std=c++17",
            "-O2",
            f"-arch={args.architecture}",
            str(source),
            "-o",
            str(binary),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env=environment,
    )
    build_text = (compile_result.stdout + compile_result.stderr)[-262_144:]
    build_log.write_text(build_text, encoding="utf-8")
    if compile_result.returncode:
        raise RuntimeError("fixed CUDA self-test compilation failed")
    run = subprocess.run(
        [str(binary)],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env=environment,
    )
    if run.returncode:
        raise RuntimeError("fixed CUDA self-test execution failed")
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or run.stderr.strip():
        raise ValueError("CUDA self-test emitted an unexpected transcript")
    result = _validate_result(json.loads(lines[0]))
    result.update(
        {
            "source_digest": args.source_digest,
            "compiler_digest": args.nvcc_digest,
            "architecture": args.architecture,
        }
    )
    temporary = result_path.with_name("." + result_path.name + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
