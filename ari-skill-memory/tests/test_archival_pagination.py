"""Phase 4 — _SdkLettaAdapter.archival_list cursor pagination.

The real SDK adapter (not the fake) previously fetched a single
passages.list(limit=200) page, silently truncating checkpoints with >200
passages. These tests drive the cursor loop with a mock SDK to prove it
sweeps every page, dedups, and degrades to a single page when the SDK has
no cursor support.
"""
from __future__ import annotations

from types import SimpleNamespace

from ari_skill_memory.backends.letta_client import _SdkLettaAdapter


class _P:
    def __init__(self, pid: str, text: str):
        self.id = pid
        self.text = text


def _passage(pid: str, collection: str = "c"):
    # encode the metadata footer the adapter decodes (needs `collection`)
    return _P(pid, _SdkLettaAdapter._encode(f"body-{pid}", {"collection": collection}))


class _CursorPassages:
    """Mock agents.passages — id-cursor pagination via `after`."""

    def __init__(self, items):
        self.items = items
        self.calls = 0

    def list(self, *, agent_id, limit, after=None):
        self.calls += 1
        start = 0
        if after is not None:
            start = next((i + 1 for i, p in enumerate(self.items) if p.id == after), len(self.items))
        return self.items[start:start + limit]


class _NoCursorPassages:
    """Mock that rejects `after` (older SDK) — forces single-page fallback."""

    def __init__(self, items):
        self.items = items

    def list(self, *, agent_id, limit, **kw):
        if "after" in kw:
            raise TypeError("unexpected keyword argument 'after'")
        return self.items[:limit]


def _adapter(passages):
    ad = _SdkLettaAdapter.__new__(_SdkLettaAdapter)
    ad.cfg = SimpleNamespace(letta_overfetch=200)
    ad._letta = SimpleNamespace(agents=SimpleNamespace(passages=passages))
    return ad


def test_paginates_across_multiple_pages():
    items = [_passage(f"p{i:04d}") for i in range(450)]  # 3 pages @ 200
    pg = _CursorPassages(items)
    rows = _adapter(pg).archival_list(agent_id="a", collection="c")
    assert len(rows) == 450               # nothing truncated at 200
    assert pg.calls == 3                  # 200 + 200 + 50 (last < page_size → stop)
    assert {r["id"] for r in rows} == {f"p{i:04d}" for i in range(450)}


def test_limit_caps_filtered_result_not_fetch():
    items = [_passage(f"p{i:04d}") for i in range(450)]
    rows = _adapter(_CursorPassages(items)).archival_list(
        agent_id="a", collection="c", limit=5,
    )
    assert len(rows) == 5                 # final cap applied AFTER full sweep


def test_collection_filter_applies_across_pages():
    items = [_passage(f"p{i:04d}", collection="c" if i % 2 == 0 else "other")
             for i in range(400)]
    rows = _adapter(_CursorPassages(items)).archival_list(agent_id="a", collection="c")
    assert len(rows) == 200               # only collection==c, but from ALL pages
    assert all(r["id"][-1] in "02468" for r in rows)


def test_single_page_fallback_when_no_cursor_support():
    items = [_passage(f"p{i:04d}") for i in range(450)]
    rows = _adapter(_NoCursorPassages(items)).archival_list(agent_id="a", collection="c")
    assert len(rows) == 200               # legacy single-page behavior, no crash


def test_looping_cursor_does_not_hang():
    # a cursor that always returns the same full page would loop forever without
    # the dedup/no-progress guard; assert it terminates.
    items = [_passage(f"p{i:04d}") for i in range(200)]

    class _StuckPassages:
        def list(self, *, agent_id, limit, after=None):
            return items[:limit]  # ignores `after` → same page every call

    rows = _adapter(_StuckPassages()).archival_list(agent_id="a", collection="c")
    assert len(rows) == 200               # deduped; loop broke on no-progress
