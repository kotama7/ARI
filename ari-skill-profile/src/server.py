"""Read-only hardware performance counters over an already-running process.

This Provider profiles; it does not execute. It never creates a process, never
writes the workspace, and never asks for a credential, which is what lets it
declare the read-only side-effect class that `ari.profiling.hardware-counters/v1`
fixes. A tool that launched its target would be `ari.execution.run/v1` wearing
a profiler's name.

Counters are opened with `perf_event_open` directly: there is no libc wrapper,
`perf` is absent from some nodes that permit counters and present on some that
deny them, and vendor profilers live at site-dependent paths. Opening the
counter observes the policy that will actually apply.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import struct
import time
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool


server = Server("ari-profile-skill")

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
_EVENTS = {
    "cycles": 0,
    "instructions": 1,
    "cache-references": 2,
    "cache-misses": 3,
    "branch-instructions": 4,
    "branch-misses": 5,
}
_ATTR_SIZE = 128
# disabled | exclude_kernel | exclude_hv -- the least-privileged request there
# is, so a denial reflects policy rather than an over-broad ask.
_ATTR_FLAGS = (1 << 0) | (1 << 5) | (1 << 6)
_IOC_ENABLE = 0x2400
_IOC_DISABLE = 0x2401
_IOC_RESET = 0x2403
_MAX_WINDOW_MS = 60_000


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


def _support() -> dict[str, Any]:
    record: dict[str, Any] = {
        "architecture": platform.machine() or "unknown",
        "perf_event_paranoid": _paranoid(),
        "reviewed_events": sorted(_EVENTS),
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
    descriptor, code = _open_counter(number, _EVENTS["cycles"], 0)
    if descriptor < 0:
        record["status"] = (
            "denied" if code in (errno.EACCES, errno.EPERM) else "unsupported"
        )
        record["detail"] = f"self probe refused: {errno.errorcode.get(code, code)}"
        return record
    os.close(descriptor)
    record["status"] = "ready"
    return record


def _measure(pid: int, window_ms: int, events: tuple[str, ...]) -> dict[str, Any]:
    support = _support()
    if support["status"] != "ready":
        return {"status": support["status"], "support": support, "counters": {}}
    number = _PERF_EVENT_OPEN_SYSCALL[support["architecture"]]
    opened: dict[str, int] = {}
    try:
        for name in events:
            descriptor, code = _open_counter(number, _EVENTS[name], pid)
            if descriptor < 0:
                for handle in opened.values():
                    os.close(handle)
                return {
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
        "status": "measured",
        "support": support,
        "pid": pid,
        "window_seconds": round(elapsed, 6),
        "counters": counters,
        "excluded": ["kernel", "hypervisor"],
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="counter_support",
            description=(
                "Report whether this node grants hardware counters, by opening one."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="measure_counters",
            description=(
                "Count reviewed hardware events on an existing process for a bounded "
                "window. Creates no process and writes nothing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "minimum": 1},
                    "window_ms": {
                        "type": "integer", "minimum": 1, "maximum": _MAX_WINDOW_MS,
                        "default": 1000,
                    },
                    "events": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(_EVENTS)},
                        "minItems": 1,
                        "default": ["cycles", "instructions"],
                    },
                },
                "required": ["pid"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "counter_support":
            result = {
                "schema_version": "ari.counter-support/v1",
                **_support(),
            }
        elif name == "measure_counters":
            pid = int(arguments["pid"])
            window = int(arguments.get("window_ms", 1000))
            events = tuple(arguments.get("events") or ("cycles", "instructions"))
            if pid < 1:
                raise ValueError("pid must be a running process")
            if not 1 <= window <= _MAX_WINDOW_MS:
                raise ValueError("window_ms is outside the reviewed bound")
            unknown = sorted(set(events) - set(_EVENTS))
            if unknown:
                raise ValueError(f"events outside the reviewed set: {unknown}")
            result = {
                "schema_version": "ari.counter-measurement/v1",
                **_measure(pid, window, events),
            }
        else:
            raise ValueError(f"unknown profiling operation: {name}")
    except (KeyError, OSError, ValueError) as exc:
        result = {
            "schema_version": "ari.profile-error/v1",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, sort_keys=True))]


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
