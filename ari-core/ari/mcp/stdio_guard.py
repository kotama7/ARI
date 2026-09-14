"""Run an MCP entrypoint while dropping whitespace-only stdout records.

The MCP Python client currently tries to decode every newline-delimited stdout
record as JSON-RPC.  A dependency that emits one empty record therefore logs a
parse traceback even when the following response is valid.  This runner stays
in the provider process (so stdio EOF and shutdown semantics remain intact)
and filters only unambiguous whitespace-only records.
"""

from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path
from typing import BinaryIO, TextIO


class _BlankLineFilter(io.RawIOBase):
    def __init__(self, target: BinaryIO, diagnostics: BinaryIO) -> None:
        self._target = target
        self._diagnostics = diagnostics
        self._pending = bytearray()

    @staticmethod
    def _is_jsonrpc(record: bytes) -> bool:
        try:
            value = json.loads(record)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        messages = value if isinstance(value, list) else [value]
        return bool(messages) and all(
            isinstance(message, dict) and message.get("jsonrpc") == "2.0"
            for message in messages
        )

    def _emit(self, record: bytes) -> None:
        if not record.strip():
            return
        if self._is_jsonrpc(record):
            self._target.write(record)
        else:
            # Preserve provider diagnostics without contaminating the protocol
            # stream. The parent process already value-redacts this stderr pipe.
            self._diagnostics.write(record)

    def writable(self) -> bool:
        return True

    def write(self, value: bytes | bytearray | memoryview) -> int:
        data = bytes(value)
        self._pending.extend(data)
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                break
            record = bytes(self._pending[: newline + 1])
            del self._pending[: newline + 1]
            self._emit(record)
        return len(data)

    def flush(self) -> None:
        self._target.flush()

    def fileno(self) -> int:
        return self._target.fileno()

    def isatty(self) -> bool:
        return self._target.isatty()

    def close(self) -> None:
        if self._pending:
            self._emit(bytes(self._pending))
        self._pending.clear()
        self._target.flush()
        self._diagnostics.flush()


class _FilteredTextOutput:
    def __init__(self, target: TextIO) -> None:
        self.encoding = target.encoding
        self.errors = target.errors
        self.buffer = _BlankLineFilter(  # type: ignore[attr-defined]
            target.buffer, sys.stderr.buffer
        )

    def write(self, value: str) -> int:
        encoding = self.encoding or "utf-8"
        errors = self.errors or "strict"
        self.buffer.write(value.encode(encoding, errors))
        return len(value)

    def flush(self) -> None:
        self.buffer.flush()

    def fileno(self) -> int:
        return self.buffer.fileno()

    def isatty(self) -> bool:
        return self.buffer.isatty()


def _strip_interpreter(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    try:
        if Path(argv[0]).resolve() == Path(sys.executable).resolve():
            return argv[1:]
    except OSError:
        pass
    return argv


def run(argv: list[str]) -> int:
    argv = _strip_interpreter(argv)
    if not argv:
        raise ValueError("stdio guard requires a provider entrypoint")

    original_stdout = sys.stdout
    filtered = _FilteredTextOutput(original_stdout)
    sys.stdout = filtered  # type: ignore[assignment]
    try:
        if argv[0] == "-c":
            if len(argv) < 2:
                raise ValueError("-c requires Python source")
            sys.argv = ["-c", *argv[2:]]
            exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__"})
        else:
            entrypoint = Path(argv[0])
            if not entrypoint.is_file():
                raise ValueError(f"provider entrypoint does not exist: {entrypoint}")
            sys.argv = [str(entrypoint), *argv[1:]]
            # Match ``python /path/to/server.py`` import semantics: provider
            # entrypoints commonly import sibling modules by their bare name.
            sys.path.insert(0, str(entrypoint.resolve().parent))
            runpy.run_path(str(entrypoint), run_name="__main__")
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    finally:
        filtered.buffer.close()
        sys.stdout = original_stdout
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    try:
        return run(argv)
    except (OSError, ValueError) as exc:
        print(f"MCP stdio guard refused launch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    # A few MCP providers install a rich global exception hook.  Raising even
    # ``SystemExit(0)`` through that hook produced a full traceback on their
    # diagnostic stream after an otherwise clean JSON-RPC shutdown.  Returning
    # from the module is the normal zero-status path; reserve SystemExit for an
    # actual launch/provider failure.
    _status = main()
    if _status:
        raise SystemExit(_status)
