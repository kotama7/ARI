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


#: RFC 5737 TEST-NET-1, reserved for documentation and assigned to nobody. The
#: probe below aims a connect() at it, so on a host WITH a route the packet
#: leaves and is answered by no one; on a host without one the kernel refuses
#: before anything is sent. Nothing reachable is contacted either way.
_UNROUTABLE = ("192.0.2.1", 9)

#: Long enough that a refusal is a refusal and not a slow kernel, short enough
#: that a routed host is not held up. A routed host TIMES OUT here, and a
#: timeout is reported as "not proved" rather than as isolation: a probe that
#: read silence as absence would call a firewalled network an isolated one.
_PROBE_SECONDS = 0.25


def network_record() -> dict:
    """Whether THIS process can reach a network, observed rather than declared.

    WHY IT IS OBSERVED HERE. ``network_isolation`` in a registration bundle read
    "proved" whenever every execution's request had said ``network: deny``, and
    every layer under it restated the same declaration: ``execution.py`` computes
    ``network_report`` as "isolated" if the request denied, so the runner's check
    that the two agree compares a declaration with itself. The executor really
    does pass ``--network none``, and that flag really is enforced by the
    container runtime -- but nothing in the evidence was a record of the
    condition, only of the intent. This is the record.

    TWO INDEPENDENT FACTS, because either alone is weak. The namespace's
    interfaces answer "is there anything here but loopback", and a connect()
    answers "does the kernel have a route". A container started with
    ``--network none`` has exactly ``lo`` and refuses instantly with
    ENETUNREACH; a host with a default route has more interfaces and times out.

    NO HOST CONFIGURATION LEAVES THIS FUNCTION. Interface NAMES are site
    detail -- ``ib0`` and ``enp3s0f1`` say what hardware a node has -- so only
    the count beyond loopback is reported, alongside the errno the probe saw.
    """
    import errno as _errno
    import socket

    # ``/proc/self/net``, NOT ``/sys/class/net``. procfs's net directory is
    # per-namespace by construction and ``self`` resolves it for the calling
    # process; sysfs shows whatever sysfs was mounted, which in a namespace
    # entered without remounting it is still the HOST's interface list.
    # MEASURED: inside ``unshare -rn`` the connect probe answered ENETUNREACH
    # while /sys/class/net still listed all ten of the host's interfaces, so a
    # probe reading sysfs would have reported an isolated namespace as open.
    beyond_loopback = None
    try:
        with open("/proc/self/net/dev", encoding="utf-8") as handle:
            names = {line.split(":", 1)[0].strip()
                     for line in handle.read().splitlines()[2:] if ":" in line}
        beyond_loopback = len(names - {"lo"})
    except OSError:
        beyond_loopback = None

    probe = "unknown"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(_PROBE_SECONDS)
        sock.connect(_UNROUTABLE)
        probe = "connected"
    except socket.timeout:
        probe = "timeout"
    except OSError as exc:
        probe = _errno.errorcode.get(exc.errno, f"errno{exc.errno}")
    finally:
        sock.close()

    # FAIL CLOSED. Isolation is claimed only when both facts say so: the kernel
    # refused for want of a route AND nothing but loopback is present. Anything
    # else -- a timeout, a connection, an unreadable /sys -- is "not shown".
    unreachable = probe in {"ENETUNREACH", "EHOSTUNREACH", "ENETDOWN"}
    return {
        "network_isolation": bool(unreachable and beyond_loopback == 0),
        "network_mechanism": "network-namespace" if beyond_loopback == 0 else None,
        "interfaces_beyond_loopback": beyond_loopback,
        "network_probe": probe,
        # Named so a reader does not infer more than was done: an empty
        # namespace is not a promise about what a candidate may do inside it.
        "network_does_not_restrict": ["unix-sockets", "loopback", "shared-memory"],
    }


__all__ = ["SandboxUnavailable", "landlock_abi", "network_record", "restrict_to",
           "sandbox_record"]
