"""Tests for ``GET /api/v1/runs/{run_id}/logs`` (gui_refresh task 07 tail —
plan 07 §Artifacts, logs, and diagnostics: cursor-based log explorer).

Byte-offset cursor pagination over the append-only plain-text
``{ckpt}/ari.log``.  Truth rules pinned here:

- the cursor is a RAW byte offset, so a 3-page chain has no gap and no
  duplicate, and the chain stays stable while the file is appended to;
- the case-insensitive ``grep`` filter selects RETURNED lines, never
  consumed bytes — cursors remain raw offsets under any filter, so a
  filtered chain also never gaps/duplicates (and matches the unfiltered
  byte positions);
- committed-only (plan 04): a trailing line without ``\\n`` is never
  emitted; ``next_cursor`` parks at its first byte and a later request
  serves the completed line;
- bounded reads (plan 07: no 5 MB whole-file primary UX): one request
  scans at most ``logs.SCAN_WINDOW_BYTES``; a window exhausted before
  ``limit`` matches returns early with ``eof=false`` and an advanced
  cursor;
- honest absence: run without ``ari.log`` => 200 ``present=false``
  (never 404); unknown run => typed 404 envelope; bad query => typed 400.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ari.viz import api_state
from ari.viz.v1 import logs as v1_logs
from ari.viz.v1.router import dispatch

RUN_ID = "20260726000000_logsfx"


@pytest.fixture
def ckpt_base(tmp_path, monkeypatch):
    """Empty search base with one bare run dir; tests write ari.log bytes."""
    base = tmp_path / "checkpoints"
    base.mkdir()
    (base / RUN_ID).mkdir()
    monkeypatch.setattr(api_state, "_checkpoint_search_bases", lambda: [base])
    return base


def _log_path(base: Path) -> Path:
    return base / RUN_ID / "ari.log"


def _get(query: str = "", run_id: str = RUN_ID) -> dict:
    path = f"/api/v1/runs/{run_id}/logs"
    if query:
        path += f"?{query}"
    return dispatch("GET", path)


# ── pagination: no gap, no duplicate over 3 pages ────────────────────────


def test_three_page_chain_has_no_gap_and_no_duplicate(ckpt_base):
    lines = [f"line {i:03d} payload" for i in range(25)]
    _log_path(ckpt_base).write_text("\n".join(lines) + "\n", encoding="utf-8")

    pages = []
    cursor = 0
    for _ in range(3):
        r = _get(f"cursor={cursor}&limit=10")
        assert r["schema_version"] == 1 and r["present"] is True
        pages.append(r)
        cursor = r["next_cursor"]

    assert [len(p["entries"]) for p in pages] == [10, 10, 5]
    assert pages[0]["eof"] is False and pages[1]["eof"] is False
    assert pages[2]["eof"] is True

    collected = [e["line"] for p in pages for e in p["entries"]]
    assert collected == lines  # exact coverage: no gap, no dup, in order

    offsets = [e["offset"] for p in pages for e in p["entries"]]
    assert offsets == sorted(set(offsets))  # strictly increasing
    # Offsets are raw byte positions: each line starts where the previous
    # one (plus its newline) ended.
    expected = 0
    for off, line in zip(offsets, lines):
        assert off == expected
        expected += len(line.encode()) + 1
    # The final page parks the cursor at the committed end of the file.
    assert pages[2]["next_cursor"] == pages[2]["file_size"]


def test_chain_is_stable_while_the_file_is_appended_to(ckpt_base):
    _log_path(ckpt_base).write_text("a\nb\n", encoding="utf-8")
    r1 = _get("limit=1")
    assert [e["line"] for e in r1["entries"]] == ["a"]
    # Append between pages: the byte cursor still resumes exactly at 'b'.
    with open(_log_path(ckpt_base), "ab") as fh:
        fh.write(b"c\n")
    r2 = _get(f"cursor={r1['next_cursor']}")
    assert [e["line"] for e in r2["entries"]] == ["b", "c"]
    assert r2["eof"] is True


# ── grep: stability across cursors ───────────────────────────────────────


def test_grep_is_case_insensitive_and_stable_across_cursors(ckpt_base):
    lines = ["alpha 0", "noise 1", "ALPHA 2", "noise 3", "Alpha 4", "noise 5"]
    _log_path(ckpt_base).write_text("\n".join(lines) + "\n", encoding="utf-8")

    r1 = _get("grep=alpha&limit=2")
    assert [e["line"] for e in r1["entries"]] == ["alpha 0", "ALPHA 2"]
    assert r1["eof"] is False
    r2 = _get(f"grep=alpha&limit=2&cursor={r1['next_cursor']}")
    assert [e["line"] for e in r2["entries"]] == ["Alpha 4"]
    assert r2["eof"] is True

    # Cursor = raw byte offset: the filtered entries carry the SAME offsets
    # an unfiltered scan reports for those lines, and the filtered
    # next_cursor is a plain line-start byte position (filter-independent).
    unfiltered = _get()
    by_line = {e["line"]: e["offset"] for e in unfiltered["entries"]}
    for page in (r1, r2):
        for e in page["entries"]:
            assert e["offset"] == by_line[e["line"]]
    assert r1["next_cursor"] == by_line["noise 3"]

    # A chain started with one filter can be continued with another —
    # no gap/duplicate because bytes, not matches, are consumed.
    r3 = _get(f"grep=noise&cursor={r1['next_cursor']}")
    assert [e["line"] for e in r3["entries"]] == ["noise 3", "noise 5"]


def test_grep_with_zero_matches_still_advances_the_cursor(ckpt_base):
    _log_path(ckpt_base).write_text("aaa\nbbb\n", encoding="utf-8")
    r = _get("grep=zzz")
    assert r["entries"] == []
    assert r["next_cursor"] == r["file_size"]  # scanned to the committed end
    assert r["eof"] is True


# ── committed-only: partial trailing line ────────────────────────────────


def test_partial_trailing_line_is_never_emitted_then_served_when_completed(
    ckpt_base,
):
    _log_path(ckpt_base).write_bytes(b"complete line\npart")
    r = _get()
    assert [e["line"] for e in r["entries"]] == ["complete line"]
    assert r["eof"] is True
    # The cursor parks at the first byte of the uncommitted tail.
    assert r["next_cursor"] == len(b"complete line\n")
    assert r["file_size"] == len(b"complete line\npart")

    # The line completes later: the SAME cursor now serves it whole.
    with open(_log_path(ckpt_base), "ab") as fh:
        fh.write(b"ial done\n")
    r2 = _get(f"cursor={r['next_cursor']}")
    assert [e["line"] for e in r2["entries"]] == ["partial done"]
    assert r2["eof"] is True


# ── honest absence / errors ──────────────────────────────────────────────


def test_missing_log_file_answers_present_false_not_404(ckpt_base):
    r = _get()
    assert r["schema_version"] == 1 and r["run_id"] == RUN_ID
    assert r["present"] is False
    assert r["entries"] == [] and r["file_size"] == 0
    assert r["next_cursor"] == 0 and r["eof"] is True
    assert "error" not in r


def test_unknown_run_answers_the_typed_404_envelope(ckpt_base):
    r = _get(run_id="20990101000000_missing")
    assert r["_status"] == 404
    assert r["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "query",
    ["cursor=-1", "cursor=abc", "limit=0", "limit=1001", "limit=x"],
)
def test_invalid_cursor_or_limit_answers_the_typed_400_envelope(
    ckpt_base, query
):
    _log_path(ckpt_base).write_text("a\n", encoding="utf-8")
    r = _get(query)
    assert r["_status"] == 400
    assert r["error"]["code"] == "invalid_request"


def test_default_limit_is_200_and_cap_is_1000(ckpt_base):
    _log_path(ckpt_base).write_text(
        "\n".join(f"l{i}" for i in range(250)) + "\n", encoding="utf-8"
    )
    r = _get()
    assert len(r["entries"]) == 200 and r["eof"] is False
    assert v1_logs.DEFAULT_LIMIT == 200 and v1_logs.MAX_LIMIT == 1000
    r2 = _get("limit=1000")
    assert len(r2["entries"]) == 250 and r2["eof"] is True


# ── bounded scan window ──────────────────────────────────────────────────


def test_scan_window_bounds_one_request_and_the_chain_still_completes(
    ckpt_base,
):
    # ~2.6 MiB of non-matching lines with one matching line at the end:
    # a single request must NOT scan the whole file (plan 07 bounded
    # reads) — it returns early with eof=false and an advanced cursor —
    # while a continued chain still finds the match.
    line = ("x" * 63) + "\n"  # 64 bytes per line
    n_lines = 40_000  # 2.44 MiB > 2 windows
    payload = line.encode() * n_lines + b"THE-NEEDLE appears\n"
    _log_path(ckpt_base).write_bytes(payload)
    assert len(payload) > 2 * v1_logs.SCAN_WINDOW_BYTES

    r = _get("grep=the-needle")
    assert r["entries"] == [] and r["eof"] is False
    assert 0 < r["next_cursor"] <= v1_logs.SCAN_WINDOW_BYTES

    pages = 1
    cursor = r["next_cursor"]
    found: list[dict] = []
    while pages < 10:
        r = _get(f"grep=the-needle&cursor={cursor}")
        # Every hop advances by at most one scan window.
        assert r["next_cursor"] - cursor <= v1_logs.SCAN_WINDOW_BYTES
        cursor = r["next_cursor"]
        found.extend(r["entries"])
        pages += 1
        if r["eof"]:
            break
    assert [e["line"] for e in found] == ["THE-NEEDLE appears"]
    # 3 requests total (~2.44 MiB / 1 MiB windows): bounded, not one giant read.
    assert r["eof"] is True and pages == 3


def test_unfiltered_request_never_reads_past_one_window(ckpt_base):
    line = ("y" * 99) + "\n"  # 100 bytes
    _log_path(ckpt_base).write_bytes(line.encode() * 15_000)  # ~1.43 MiB
    r = _get("limit=1000")
    assert len(r["entries"]) == 1000
    assert r["next_cursor"] <= v1_logs.SCAN_WINDOW_BYTES
    assert r["eof"] is False


# ── hygiene ──────────────────────────────────────────────────────────────


def test_get_is_side_effect_free_and_deterministic(ckpt_base):
    _log_path(ckpt_base).write_bytes(b"one\ntwo\npartial")
    before = _log_path(ckpt_base).read_bytes()
    r1 = _get("grep=o&limit=5")
    r2 = _get("grep=o&limit=5")
    assert _log_path(ckpt_base).read_bytes() == before
    r1.pop("request_id"), r2.pop("request_id")
    assert r1 == r2


def test_non_utf8_bytes_degrade_to_replacement_never_500(ckpt_base):
    _log_path(ckpt_base).write_bytes(b"ok line\n\xff\xfe broken\n")
    r = _get()
    assert r["present"] is True and len(r["entries"]) == 2
    assert r["entries"][0]["line"] == "ok line"
    assert "�" in r["entries"][1]["line"]
