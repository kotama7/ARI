#!/usr/bin/python3
"""Execute exactly the reviewed NVIDIA inventory query on a compute node."""

from __future__ import annotations

import os
import sys


_QUERY = (
    "--query-gpu=uuid,name,driver_version,memory.total,compute_cap",
    "--format=csv,noheader,nounits",
)


def main() -> int:
    if tuple(sys.argv[1:]) != _QUERY:
        print("ARI: unsupported NVIDIA inventory query", file=sys.stderr)
        return 64
    executable = "/usr/bin/nvidia-smi"
    if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
        print("ARI: NVIDIA inventory executable is unavailable", file=sys.stderr)
        return 69
    os.execve(
        executable,
        (executable, *_QUERY),
        {"HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
