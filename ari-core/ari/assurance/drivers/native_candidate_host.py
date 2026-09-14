"""One-case child host for an untrusted native shared library.

The oracle never enters this process.  A crash, timeout, or malformed response
therefore becomes a candidate failure instead of corrupting verifier state.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import sys
from pathlib import Path

from ari.assurance.drivers.shared_library import (  # noqa: E402
    abi_adapter_kinds, run_shared_library)
# IMPORTED AT THE TOP, and it has to be. Landlock is applied inside ``main``
# before the candidate runs, and it excludes the verifier's own files -- so an
# import issued after the restriction is denied. MEASURED: importing this one
# lazily beside its first use produced
# "PermissionError: ... Permission denied: .../assurance/sandbox.py" and turned
# every case into a candidate failure. The restriction working is exactly why
# the module has to be resident before it is applied.
from ari.assurance.sandbox import observed_network  # noqa: E402


_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

_FS_EXECUTE = 1 << 0
_FS_WRITE_FILE = 1 << 1
_FS_READ_FILE = 1 << 2
_FS_READ_DIR = 1 << 3
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13
_FS_TRUNCATE = 1 << 14
_FS_IOCTL_DEV = 1 << 15


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _syscall(libc, number: int, *args) -> int:
    result = int(libc.syscall(number, *args))
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def _handled_access(abi: int) -> int:
    access = (1 << 13) - 1
    if abi >= 2:
        access |= _FS_REFER
    if abi >= 3:
        access |= _FS_TRUNCATE
    if abi >= 5:
        access |= _FS_IOCTL_DEV
    return access


def _restrict_candidate_filesystem(library: str) -> int:
    """Fail closed into a Landlock view that excludes verifier/oracle files."""

    if os.uname().machine not in {"x86_64", "aarch64", "riscv64"}:
        raise RuntimeError("native candidate isolation is unsupported on this architecture")
    target = Path(library)
    if target.is_symlink() or not target.is_file():
        raise RuntimeError("native candidate target is not a regular file")
    target = target.resolve(strict=True)
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        abi = _syscall(
            libc,
            _SYS_LANDLOCK_CREATE_RULESET,
            ctypes.c_void_p(),
            ctypes.c_size_t(0),
            ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION),
        )
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EOPNOTSUPP}:
            raise RuntimeError("Landlock is unavailable; candidate execution is refused") from exc
        raise
    handled = _handled_access(abi)
    ruleset_attr = ctypes.c_uint64(handled)
    ruleset_fd = _syscall(
        libc,
        _SYS_LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        ctypes.c_uint(0),
    )
    read_execute = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR
    read_file = _FS_EXECUTE | _FS_READ_FILE
    allowed = [
        (Path(path), read_execute)
        for path in ("/usr", "/lib", "/lib64")
        if Path(path).exists()
    ]
    for path in ("/etc/ld.so.cache", "/etc/ld.so.preload"):
        candidate = Path(path)
        if candidate.is_file() and not candidate.is_symlink():
            allowed.append((candidate, read_file))
    allowed.append((target, read_file))
    path_flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC
    try:
        for path, access in allowed:
            descriptor = os.open(path, path_flags)
            try:
                attr = _PathBeneathAttr(
                    allowed_access=access,
                    parent_fd=descriptor,
                )
                _syscall(
                    libc,
                    _SYS_LANDLOCK_ADD_RULE,
                    ruleset_fd,
                    _LANDLOCK_RULE_PATH_BENEATH,
                    ctypes.byref(attr),
                    ctypes.c_uint(0),
                )
            finally:
                os.close(descriptor)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        _syscall(libc, _SYS_LANDLOCK_RESTRICT_SELF, ruleset_fd, ctypes.c_uint(0))
    finally:
        os.close(ruleset_fd)
    # The ABI actually negotiated, handed back so the record says which
    # Landlock this kernel enforced rather than that some Landlock did.
    return abi


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    # The ACCEPTED set is the DISPATCHABLE set. Written out here it was a
    # fourth copy that could disagree with the other three: a kind this host
    # refused was one the driver could still ask for, and the refusal arrived
    # as a usage error rather than as anything a caller could act on.
    parser.add_argument("--kind", choices=abi_adapter_kinds(), required=True)
    parser.add_argument("--library", required=True)
    args = parser.parse_args(argv)
    try:
        case = json.loads(sys.stdin.read())
        # OBSERVED BEFORE THE RESTRICTION, and it has to be. The probe opens a
        # socket and reads /proc/self/net/dev, and Landlock excludes the
        # verifier's view -- MEASURED, taking it afterwards produced
        # "Permission denied: .../python3.13/socket.py" and turned every case
        # into a candidate failure. Landlock does not touch a network
        # namespace, so before and after are the same answer; only one of them
        # can be reached.
        network = observed_network()
        abi = _restrict_candidate_filesystem(args.library)
        # WHAT THIS CHILD RAN UNDER, observed in the process the candidate is
        # about to be called in. The filesystem half is a PRECONDITION here and
        # not a finding: the call above fails closed, so a candidate never runs
        # unrestricted and "True" is the only value that can reach this line.
        # It is recorded anyway so a reader does not have to know that.
        #
        # The network half is a genuine observation and was missing entirely.
        # This family's registration evidence declared network_isolation from
        # the REQUEST, like the others did, and had nothing to derive it from.
        sandbox = {"filesystem_isolation": True, "mechanism": "landlock",
                   "landlock_abi": abi,
                   "does_not_restrict": ["fork", "cpu", "network-by-itself",
                                         "memory"]}
        sandbox.update(network)
        result = run_shared_library(args.kind, args.library, case)
        sys.stdout.write(json.dumps({"ok": True, "result": result,
                                     "sandbox": sandbox}, allow_nan=True))
        return 0
    except Exception as exc:
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                allow_nan=True,
            )
        )
        return 2


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    raise SystemExit(main())
