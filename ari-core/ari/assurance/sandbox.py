"""Landlock the process that runs untrusted code, so a check is not the only defence.

WHY. Every forgery demonstrated against the performance harness used the same
two primitives: ``fork()`` and reading ``/proc/self/cmdline`` to find the file
the credited time is written to. The harness now catches those after the fact --
a wall-clock bound, a cross-role overhead calibration, a process-group reap --
but each of those is a check, and a check only refuses what someone thought to
check for. A candidate that cannot READ the path cannot use it, and one that
cannot read the problem directory cannot find the frozen reference that is its
own denominator.

WHAT THIS IS NOT. Landlock is filesystem access control. It does not stop
``fork``, it does not stop a candidate spinning CPU, and it does not stop code
that never touches the filesystem. It removes one family of moves; the checks
stay because they cover a different family.

FAIL CLOSED, AND SAY SO. On a kernel without Landlock this raises. The caller
decides whether that is fatal -- a registered harness whose manifest demands
isolation must refuse, while a developer measuring on a laptop should be told
rather than silently unprotected. Either way the run records which it was, so
"this was sandboxed" is never inferred from its absence.

Extracted from ``drivers/native_candidate_host``, which has used it for the
correctness harness's candidate process; the perf path had no sandbox at all.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path

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
_FS_MAKE_REG = 1 << 8
_FS_REFER = 1 << 13
_FS_TRUNCATE = 1 << 14
_FS_IOCTL_DEV = 1 << 15

#: Read and execute: the loader, libc, libgomp.
READ_EXECUTE = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR
#: The run's own scratch: read its problem, write its answer and its timing.
READ_WRITE = (READ_EXECUTE | _FS_WRITE_FILE | _FS_MAKE_REG | _FS_TRUNCATE)

#: Where a dynamically linked binary's libraries live. Read-only.
SYSTEM_READ_PATHS = ("/usr", "/lib", "/lib64")
SYSTEM_READ_FILES = ("/etc/ld.so.cache", "/etc/ld.so.preload")


class SandboxUnavailable(RuntimeError):
    """This kernel cannot enforce the restriction, so nothing was enforced."""


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


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


def landlock_abi() -> int:
    """The kernel's Landlock ABI, or raise if it has none."""
    if os.uname().machine not in {"x86_64", "aarch64", "riscv64"}:
        raise SandboxUnavailable(
            f"no Landlock syscall numbers for {os.uname().machine}")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        return _syscall(libc, _SYS_LANDLOCK_CREATE_RULESET, ctypes.c_void_p(),
                        ctypes.c_size_t(0),
                        ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION))
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EOPNOTSUPP}:
            raise SandboxUnavailable("this kernel has no Landlock") from exc
        raise


def restrict_to(writable: Path | str) -> int:
    """Restrict THIS process to the system libraries and one writable directory.

    Applied between fork and exec, so it binds the child and everything the
    child starts -- Landlock is inherited and cannot be dropped.

    What it denies is the point: ``/proc`` is not in the ruleset, so a kernel
    can no longer read its own ``/proc/self/cmdline`` to find the file its
    credited time is written to; and the problem directory is not in it either,
    so a candidate cannot read the frozen reference that is its own denominator.

    Returns the ABI it enforced under, for the record.
    """
    abi = landlock_abi()
    libc = ctypes.CDLL(None, use_errno=True)
    attr = ctypes.c_uint64(_handled_access(abi))
    ruleset = _syscall(libc, _SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(attr),
                       ctypes.sizeof(attr), ctypes.c_uint(0))
    allowed: list[tuple[Path, int]] = [
        (Path(path), READ_EXECUTE) for path in SYSTEM_READ_PATHS
        if Path(path).exists()
    ]
    allowed += [(Path(path), _FS_EXECUTE | _FS_READ_FILE)
                for path in SYSTEM_READ_FILES
                if Path(path).is_file() and not Path(path).is_symlink()]
    allowed.append((Path(writable), READ_WRITE))
    flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_CLOEXEC
    try:
        for path, access in allowed:
            descriptor = os.open(path, flags)
            try:
                rule = _PathBeneathAttr(allowed_access=access,
                                        parent_fd=descriptor)
                _syscall(libc, _SYS_LANDLOCK_ADD_RULE, ruleset,
                         _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule),
                         ctypes.c_uint(0))
            finally:
                os.close(descriptor)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        _syscall(libc, _SYS_LANDLOCK_RESTRICT_SELF, ruleset, ctypes.c_uint(0))
    finally:
        os.close(ruleset)
    return abi


def sandbox_record(writable: Path | str | None = None) -> dict:
    """What isolation this host can enforce, recorded rather than assumed."""
    try:
        abi = landlock_abi()
    except SandboxUnavailable as exc:
        return {"filesystem_isolation": False, "mechanism": None,
                "reason": str(exc)}
    return {
        "filesystem_isolation": True,
        "mechanism": "landlock",
        "landlock_abi": abi,
        "writable_root": str(writable) if writable else None,
        # Named so a reader does not infer more than was done: this is
        # filesystem access control and nothing else.
        "does_not_restrict": ["fork", "cpu", "network-by-itself", "memory"],
    }


__all__ = ["SandboxUnavailable", "landlock_abi", "restrict_to", "sandbox_record"]
