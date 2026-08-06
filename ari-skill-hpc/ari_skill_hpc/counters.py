"""Read-only hardware performance counters over an already-running process.

This profiles; it does not execute. It creates no process, writes nothing, and
asks for no credential, which is what lets the tool declare the read-only
side-effect class that ``ari.profiling.hardware-counters/v1`` fixes. A tool
that launched its own target would be ``ari.execution.run/v1`` wearing a
profiler's name and would need a different contract.

Counters are opened through ``perf_event_open`` directly. A profiler binary
proves nothing: ``perf`` is absent from some nodes that permit counters and
present on some that deny them, and vendor profilers live at site-dependent
paths. Opening the counter observes the kernel policy that will actually
apply, inside whatever container the node runs in.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import struct
import time
from typing import Any

# aarch64 and riscv64 share the asm-generic table.
_PERF_EVENT_OPEN_SYSCALL = {
    "aarch64": 241,
    "armv7l": 364,
    "i386": 336,
    "i686": 336,
    "ppc64": 319,
    "ppc64le": 319,
    "riscv64": 241,
    "s390x": 331,
    "x86_64": 298,
}
_PERF_TYPE_HARDWARE = 0
# The reviewed event set. Anything outside it is refused rather than passed
# through, so a caller cannot reach an arbitrary raw event encoding.
REVIEWED_EVENTS = {
    "cycles": 0,
    "instructions": 1,
    "cache-references": 2,
    "cache-misses": 3,
    "branch-instructions": 4,
    "branch-misses": 5,
}
DEFAULT_EVENTS = ("cycles", "instructions")
MAX_WINDOW_MS = 60_000
_ATTR_SIZE = 128
# disabled | exclude_kernel | exclude_hv -- the least-privileged request there
# is, so a denial reflects policy rather than an over-broad ask.
_ATTR_FLAGS = (1 << 0) | (1 << 5) | (1 << 6)
_IOC_ENABLE = 0x2400
_IOC_DISABLE = 0x2401
_IOC_RESET = 0x2403


def _paranoid() -> int | None:
    try:
        with open("/proc/sys/kernel/perf_event_paranoid", encoding="ascii") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _libc() -> ctypes.CDLL:
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    return library


def _open_counter(number: int, config: int, pid: int) -> tuple[int, int]:
    attr = bytearray(_ATTR_SIZE)
    struct.pack_into(
        "=IIQQQQQ", attr, 0, _PERF_TYPE_HARDWARE, _ATTR_SIZE, config, 0, 0, 0,
        _ATTR_FLAGS,
    )
    buffer = ctypes.create_string_buffer(bytes(attr), _ATTR_SIZE)
    library = _libc()
    ctypes.set_errno(0)
    descriptor = library.syscall(
        ctypes.c_long(number),
        ctypes.byref(buffer),
        ctypes.c_int(pid),
        ctypes.c_int(-1),  # cpu: any
        ctypes.c_int(-1),  # group_fd: none
        ctypes.c_ulong(0),
    )
    if descriptor < 0:
        return -1, ctypes.get_errno()
    return descriptor, 0


def counter_support() -> dict[str, Any]:
    """Decide the counter capability by opening one, not by naming a tool."""

    record: dict[str, Any] = {
        "schema_version": "ari.hpc.counter-support/v1",
        "architecture": platform.machine() or "unknown",
        "perf_event_paranoid": _paranoid(),
        "reviewed_events": sorted(REVIEWED_EVENTS),
        "status": "unavailable",
        "detail": None,
    }
    if platform.system().lower() != "linux":
        record["detail"] = "hardware counters require Linux perf_event_open"
        return record
    number = _PERF_EVENT_OPEN_SYSCALL.get(record["architecture"])
    if number is None:
        record["status"] = "unsupported"
        record["detail"] = "no reviewed perf_event_open syscall for this architecture"
        return record
    descriptor, code = _open_counter(number, REVIEWED_EVENTS["cycles"], 0)
    if descriptor < 0:
        record["status"] = (
            "denied" if code in (errno.EACCES, errno.EPERM) else "unsupported"
        )
        record["detail"] = f"self probe refused: {errno.errorcode.get(code, code)}"
        return record
    os.close(descriptor)
    record["status"] = "ready"
    return record


def measure_counters(
    pid: int, window_ms: int = 1000, events: tuple[str, ...] = DEFAULT_EVENTS
) -> dict[str, Any]:
    """Count reviewed events on an existing process over a bounded window."""

    if pid < 1:
        raise ValueError("pid must name a running process")
    if not 1 <= window_ms <= MAX_WINDOW_MS:
        raise ValueError("window_ms is outside the reviewed bound")
    unknown = sorted(set(events) - set(REVIEWED_EVENTS))
    if unknown:
        raise ValueError(f"events outside the reviewed set: {unknown}")

    support = counter_support()
    if support["status"] != "ready":
        return {
            "schema_version": "ari.hpc.counter-measurement/v1",
            "status": support["status"],
            "support": support,
            "counters": {},
        }
    number = _PERF_EVENT_OPEN_SYSCALL[support["architecture"]]
    opened: dict[str, int] = {}
    try:
        for name in events:
            descriptor, code = _open_counter(number, REVIEWED_EVENTS[name], pid)
            if descriptor < 0:
                return {
                    "schema_version": "ari.hpc.counter-measurement/v1",
                    "status": "denied"
                    if code in (errno.EACCES, errno.EPERM)
                    else "unavailable",
                    "support": support,
                    "counters": {},
                    "detail": (
                        f"{name} refused for pid {pid}: "
                        f"{errno.errorcode.get(code, code)}"
                    ),
                }
            opened[name] = descriptor
        library = _libc()
        for handle in opened.values():
            library.ioctl(ctypes.c_int(handle), ctypes.c_ulong(_IOC_RESET), 0)
            library.ioctl(ctypes.c_int(handle), ctypes.c_ulong(_IOC_ENABLE), 0)
        started = time.monotonic()
        time.sleep(window_ms / 1000.0)
        elapsed = time.monotonic() - started
        for handle in opened.values():
            library.ioctl(ctypes.c_int(handle), ctypes.c_ulong(_IOC_DISABLE), 0)
        counters: dict[str, int] = {}
        for name, handle in opened.items():
            raw = os.read(handle, 8)
            counters[name] = int.from_bytes(raw, "little") if len(raw) == 8 else -1
    finally:
        for handle in opened.values():
            try:
                os.close(handle)
            except OSError:
                pass
    return {
        "schema_version": "ari.hpc.counter-measurement/v1",
        "status": "measured",
        "support": support,
        "pid": pid,
        "window_seconds": round(elapsed, 6),
        "counters": counters,
        "excluded": ["kernel", "hypervisor"],
    }


__all__ = [
    "DEFAULT_EVENTS",
    "MAX_WINDOW_MS",
    "REVIEWED_EVENTS",
    "counter_support",
    "measure_counters",
]
