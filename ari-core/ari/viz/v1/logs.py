"""Cursor-based run-log read model for ``/api/v1`` (gui_refresh task 07
tail): the log is a bounded, cursor-paged diagnostic read, never a
whole-file dump.

``GET /api/v1/runs/{run_id}/logs?cursor=&limit=&grep=`` pages over the
append-only plain-text ``{ckpt}/ari.log`` (the FileHandler ``ari.cli.run``
attaches; canonical path ``ari.paths.Paths.log_file``).  Same posture as
:mod:`ari.viz.v1.queries`: pure filesystem reads (no ``viz.state`` mutation,
no env writes, nothing ever written), run resolution through
``checkpoint_finder._resolve_checkpoint_dir`` (the ``api_state`` facade
deferral, so test monkeypatches are honored).

Contract (documented here because it is deliberate, not incidental):

- **cursor = raw byte offset** into ``ari.log``.  The ``grep`` filter
  (case-insensitive substring) selects which scanned lines are *returned*,
  never which bytes are *consumed* — the cursor advances over non-matching
  lines too, so pagination is stable regardless of the filter and a page
  chain never gaps or duplicates when the filter changes between requests.
  The filter is applied while scanning forward up to ``limit`` matches, not
  to a pre-sliced page.
- **committed-only**: a line is served only once its newline has landed, so
  a trailing line without ``\\n`` is never emitted; ``next_cursor`` parks at
  its first byte and a later request serves the line when it completes.
- **bounded**: each request scans at most :data:`SCAN_WINDOW_BYTES` (1 MiB)
  from the cursor — never the whole file (a multi-megabyte whole-file read
  must not be the primary UX).  If the window ends before ``limit`` matches
  were found, the page returns what was found with ``eof=false`` and the
  advanced ``next_cursor`` so the client continues; no request ever scans
  unboundedly.
- **honest absence**: a run without ``ari.log`` answers 200
  ``present=false`` (the log may simply not exist yet) — only an unknown
  run answers the typed 404 envelope.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..checkpoint_finder import _resolve_checkpoint_dir
from .dto import LogEntryV1, RunLogsV1
from .errors import error_response

log = logging.getLogger(__name__)

#: The served log file inside the checkpoint dir (ari.paths log_file name).
LOG_FILENAME = "ari.log"

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

#: Per-request scan bound: at most this many bytes are read from the cursor,
#: so no request ever scans unboundedly. 1 MiB comfortably holds thousands
#: of log lines.
SCAN_WINDOW_BYTES = 1 << 20

#: Sanity cap on the grep needle (it is a substring, not a regex).
MAX_GREP_LEN = 256


def _parse_query(query: dict[str, str]) -> tuple[int, int, str, dict | None]:
    """Parse ``cursor``/``limit``/``grep`` → ``(cursor, limit, grep, err)``.

    Same envelope style as ``rqgm._parse_cursor_limit``: the fourth element
    is the typed 400 envelope (or ``None``)."""
    cursor_raw = query.get("cursor", "0") or "0"
    limit_raw = query.get("limit", str(DEFAULT_LIMIT)) or str(DEFAULT_LIMIT)
    grep = query.get("grep", "")
    if not cursor_raw.lstrip("-").isdigit() or int(cursor_raw) < 0:
        return 0, 0, "", error_response(
            "invalid_request",
            f"cursor must be a non-negative integer (got {cursor_raw!r})",
            request_id="",
            status=400,
        )
    if not limit_raw.lstrip("-").isdigit() or not (
        1 <= int(limit_raw) <= MAX_LIMIT
    ):
        return 0, 0, "", error_response(
            "invalid_request",
            f"limit must be an integer in [1, {MAX_LIMIT}] "
            f"(got {limit_raw!r})",
            request_id="",
            status=400,
        )
    if len(grep) > MAX_GREP_LEN:
        return 0, 0, "", error_response(
            "invalid_request",
            f"grep must be at most {MAX_GREP_LEN} characters "
            f"(got {len(grep)})",
            request_id="",
            status=400,
        )
    return int(cursor_raw), int(limit_raw), grep, None


def _scan_page(
    path: Path, cursor: int, limit: int, grep: str, run_id: str
) -> RunLogsV1:
    """One bounded page: scan forward from *cursor*, emit up to *limit*
    grep-matching committed lines, and advance the cursor over every
    consumed line (matching or not)."""
    degraded: list[str] = []
    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        fh.seek(cursor)
        chunk = fh.read(SCAN_WINDOW_BYTES)
    window_end = cursor + len(chunk)
    # The file may grow between fstat and read; trust the bytes we hold.
    size = max(size, window_end)

    if cursor > size:
        # Append-only in theory; a shrunk file means rotation/truncation.
        degraded.append(
            f"cursor {cursor} is beyond file_size {size} "
            "(log truncated?); resuming from the end"
        )
        return RunLogsV1(
            run_id=run_id,
            present=True,
            entries=[],
            next_cursor=size,
            eof=True,
            file_size=size,
            degraded_reasons=degraded,
        )

    entries: list[LogEntryV1] = []
    needle = grep.lower()
    pos = 0
    while len(entries) < limit:
        nl = chunk.find(b"\n", pos)
        if nl == -1:
            # No complete line left in this window.  Normally the remainder
            # is either a window-boundary cut (the next request re-reads the
            # line from its start) or the uncommitted partial tail (never
            # emitted).  The one stall case — a single line larger than the
            # whole scan window — skips ahead one window with an explicit
            # degraded reason so the cursor always makes bounded progress.
            if (
                pos == 0
                and len(chunk) == SCAN_WINDOW_BYTES
                and window_end < size
            ):
                degraded.append(
                    f"line at byte {cursor} exceeds the "
                    f"{SCAN_WINDOW_BYTES}-byte scan window; skipped ahead"
                )
                pos = len(chunk)
            break
        raw = chunk[pos:nl]
        offset = cursor + pos
        pos = nl + 1
        text = raw.decode("utf-8", errors="replace")
        if text.endswith("\r"):
            text = text[:-1]
        if needle and needle not in text.lower():
            continue
        entries.append(LogEntryV1(offset=offset, line=text))

    next_cursor = cursor + pos
    remaining = chunk[pos:]
    if b"\n" in remaining:
        eof = False  # at least one more committed line is already visible
    elif window_end < size:
        eof = False  # bytes beyond this window may hold committed lines
    else:
        eof = True  # only the uncommitted partial tail (or nothing) remains
    return RunLogsV1(
        run_id=run_id,
        present=True,
        entries=entries,
        next_cursor=next_cursor,
        eof=eof,
        file_size=size,
        degraded_reasons=degraded,
    )


def get_run_logs(run_id: str, query: dict[str, str]) -> RunLogsV1 | dict:
    """GET /api/v1/runs/{run_id}/logs?cursor=&limit=&grep=."""
    d = _resolve_checkpoint_dir(run_id)
    if d is None:
        return error_response(
            "not_found", f"unknown run: {run_id}", request_id="", status=404
        )
    cursor, limit, grep, err = _parse_query(query)
    if err is not None:
        return err
    p = d / LOG_FILENAME
    if not p.is_file():
        # Honest absence: the log may not have been written yet — 200 with
        # present=false, never a 404 (the run itself exists).
        return RunLogsV1(run_id=run_id, present=False)
    try:
        return _scan_page(p, cursor, limit, grep, run_id)
    except OSError as e:
        log.debug("v1 ari.log read error: %s", p, exc_info=True)
        return RunLogsV1(
            run_id=run_id,
            present=False,
            degraded_reasons=[f"{LOG_FILENAME} unreadable: {e}"],
        )
