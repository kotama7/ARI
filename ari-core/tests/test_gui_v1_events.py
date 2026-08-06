"""Tests for the ``/api/v1`` realtime event bus + SSE stream (gui_refresh
Wave 2b, ADR-03 + plan 04 §Realtime event contract).

Covers ``ari.viz.v1.events``: publish shape (frozen plan-04 event contract,
monotonic ``event_id``, per-``(topic, run_id)`` ``revision``), ring-buffer
overflow, ``Last-Event-ID`` replay, run/topic filtering, the Condition-based
``subscribe`` iterator (heartbeat ``None`` ticks), SSE framing via a fake
``wfile`` (initial ``: connected``/``retry`` preamble, replay frames,
heartbeat comments with a patched clock, ``BrokenPipeError`` disconnect
cleanup), the ``routes.py`` endpoint branch driven through a socketless
``_Handler``, and the two publication hooks (``state_sync._watcher_thread``
tree-mtime publish, ``checkpoint_lifecycle._api_switch_checkpoint`` run
publish) against a ``run_fixture_factory`` checkpoint. No real sockets, no
sleeps above 0.2 s.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ari.viz import routes, state_sync
from ari.viz import state as _st
from ari.viz.checkpoint_lifecycle import _api_switch_checkpoint
from ari.viz.v1 import events

_FACTORY_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "gui_refresh"
    / "run_fixture_factory.py"
)


def _load_factory():
    spec = importlib.util.spec_from_file_location(
        "gui_refresh_run_fixture_factory", _FACTORY_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


make_run_checkpoint = _load_factory().make_run_checkpoint

# Fast stream knobs: short heartbeat wait + immediately-expired deadline so
# every stream ends after its first idle tick (no sleeps above 0.2 s).
FAST = dict(heartbeat_s=0.01, max_stream_s=0.0)

EVENT_KEYS = {
    "event_id", "run_id", "topic", "revision", "occurred_at", "kind",
    "resource", "payload",
}


@pytest.fixture(autouse=True)
def _fresh_bus():
    events._reset_for_tests()
    yield
    events._reset_for_tests()


def _frames(raw: bytes) -> list[bytes]:
    """Split an SSE byte stream into its blank-line-delimited frames."""
    return [f for f in raw.split(b"\n\n") if f]


def _data_events(raw: bytes) -> list[dict]:
    """Decode every ``data:`` frame back into its event dict."""
    out = []
    for frame in _frames(raw):
        for line in frame.split(b"\n"):
            if line.startswith(b"data: "):
                out.append(json.loads(line[len(b"data: "):].decode("utf-8")))
    return out


# ── bus: publish shape / revision / overflow ─────────────────────────────


def test_publish_event_shape_and_monotonic_ids():
    e1 = events.publish("tree", "run-a")
    e2 = events.publish("run", "run-a", payload={"x": 1})
    assert set(e1.keys()) == EVENT_KEYS
    assert e1["kind"] == "resource.changed"
    assert e1["resource"] == "/api/v1/runs/run-a/tree"
    assert e2["resource"] == "/api/v1/runs/run-a/summary"
    assert e1["payload"] == {} and e2["payload"] == {"x": 1}
    # Monotonic int-as-str ids, UTC ISO occurred_at.
    assert [e1["event_id"], e2["event_id"]] == ["1", "2"]
    assert e1["occurred_at"].endswith("Z") and "T" in e1["occurred_at"]


def test_revision_counts_per_topic_and_run():
    assert events.publish("tree", "run-a")["revision"] == 1
    assert events.publish("tree", "run-a")["revision"] == 2
    assert events.publish("tree", "run-b")["revision"] == 1  # other run
    assert events.publish("run", "run-a")["revision"] == 1   # other topic


def test_publish_rejects_unknown_topic():
    with pytest.raises(ValueError):
        events.publish("logs", "run-a")  # not in the Wave 2b vocabulary


def test_ring_buffer_overflow_drops_oldest():
    for i in range(events.BUFFER_MAXLEN + 5):
        events.publish("tree", "run-a")
    replay = events.replay_since(0)
    assert len(replay) == events.BUFFER_MAXLEN
    assert replay[0]["event_id"] == "6"  # events 1..5 evicted
    assert replay[-1]["event_id"] == str(events.BUFFER_MAXLEN + 5)


# ── bus: replay + filtering + subscribe ──────────────────────────────────


def test_replay_since_last_event_id_and_filters():
    events.publish("tree", "run-a")
    events.publish("run", "run-a")
    events.publish("tree", "run-b")
    assert [e["event_id"] for e in events.replay_since("1")] == ["2", "3"]
    assert [e["event_id"] for e in events.replay_since(None)] == ["1", "2", "3"]
    assert [e["event_id"] for e in events.replay_since(0, run_id="run-b")] == ["3"]
    assert [e["event_id"] for e in events.replay_since(0, topics={"tree"})] == \
        ["1", "3"]
    assert events.replay_since("garbage") == events.replay_since(0)


def test_subscribe_replays_then_heartbeats_then_resumes():
    events.publish("tree", "run-a")
    events.publish("run", "run-a")
    gen = events.subscribe(heartbeat_s=0.01)
    assert next(gen)["event_id"] == "1"
    assert next(gen)["event_id"] == "2"
    assert next(gen) is None  # idle tick after ~10 ms wait
    events.publish("tree", "run-a")
    assert next(gen)["event_id"] == "3"


def test_subscribe_yields_heartbeat_when_all_events_filtered_out():
    gen = events.subscribe(run_id="run-x", heartbeat_s=0.01)
    events.publish("tree", "run-other")
    assert next(gen) is None  # cursor advances past the filtered event
    events.publish("tree", "run-x")
    assert next(gen)["run_id"] == "run-x"


# ── SSE framing onto a fake wfile ────────────────────────────────────────


def test_stream_preamble_and_initial_replay():
    for _ in range(3):
        events.publish("tree", "run-a")
    buf = io.BytesIO()
    events.stream_events(buf, **FAST)
    raw = buf.getvalue()
    assert raw.startswith(b": connected\n\nretry: 5000\n\n")
    assert raw.rstrip().endswith(b": stream-timeout - reconnect")
    got = _data_events(raw)
    assert [e["event_id"] for e in got] == ["1", "2", "3"]
    # Each data frame is preceded by its id: and event: fields.
    assert b"id: 1\nevent: resource.changed\ndata: " in raw


def test_stream_last_event_id_resume_and_filtering():
    events.publish("tree", "run-a")
    events.publish("run", "run-a")
    events.publish("tree", "run-b")
    buf = io.BytesIO()
    events.stream_events(
        buf, run_id="run-a", topics={"tree", "run"}, last_event_id="1", **FAST
    )
    got = _data_events(buf.getvalue())
    assert [e["event_id"] for e in got] == ["2"]  # after id 1, run-b filtered


class _ClockAdvancingWfile:
    """Fake wfile that jumps the patched clock forward once a heartbeat
    comment has been written, so the next idle tick hits the deadline."""

    def __init__(self, clock):
        self.buf = io.BytesIO()
        self._clock = clock

    def write(self, data):
        self.buf.write(data)
        if data == b": heartbeat\n\n":
            self._clock["t"] = 10_000.0

    def flush(self):
        pass


def test_stream_heartbeat_then_deadline(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(
        events, "time", SimpleNamespace(time=lambda: clock["t"])
    )
    wfile = _ClockAdvancingWfile(clock)
    events.stream_events(wfile, heartbeat_s=0.01, max_stream_s=300.0)
    raw = wfile.buf.getvalue()
    assert raw.count(b": heartbeat\n\n") == 1
    assert raw.rstrip().endswith(b": stream-timeout - reconnect")


class _BrokenPipeWfile:
    """Fake wfile raising BrokenPipeError from the Nth write onwards."""

    def __init__(self, fail_at: int):
        self.buf = io.BytesIO()
        self.writes = 0
        self.fail_at = fail_at

    def write(self, data):
        self.writes += 1
        if self.writes >= self.fail_at:
            raise BrokenPipeError
        self.buf.write(data)

    def flush(self):
        pass


def test_stream_client_disconnect_ends_cleanly():
    for _ in range(5):
        events.publish("tree", "run-a")
    wfile = _BrokenPipeWfile(fail_at=4)
    # Must swallow the BrokenPipeError exactly like /api/logs does.
    events.stream_events(wfile, **FAST)
    got = _data_events(wfile.buf.getvalue())
    assert [e["event_id"] for e in got] == ["1"]  # preamble(2) + frame, then cut


# ── routes.py endpoint branch (socketless handler) ───────────────────────


def _make_handler(path: str, headers: dict | None = None):
    h = routes._Handler.__new__(routes._Handler)
    h.path = path
    h.headers = headers or {}
    h.wfile = io.BytesIO()
    h.sent = []
    h.send_response = lambda code: h.sent.append(("status", code))
    h.send_header = lambda k, v: h.sent.append((k, v))
    h.end_headers = lambda: h.sent.append(("end", None))
    return h


@pytest.fixture
def _fast_stream(monkeypatch):
    """Make the endpoint's stream_events call end after its first idle tick."""
    real = events.stream_events

    def fast(wfile, **kw):
        kw.update(FAST)
        return real(wfile, **kw)

    monkeypatch.setattr(events, "stream_events", fast)


def test_endpoint_streams_with_filters_and_last_event_id(_fast_stream):
    events.publish("tree", "run-a")
    events.publish("run", "run-a")
    events.publish("tree", "run-b")
    h = _make_handler(
        "/api/v1/events/stream?run_id=run-a&topics=tree,run",
        headers={"Last-Event-ID": "1"},
    )
    h.do_GET()
    assert ("status", 200) in h.sent
    assert ("Content-Type", "text/event-stream") in h.sent
    raw = h.wfile.getvalue()
    assert raw.startswith(b": connected\n\nretry: 5000\n\n")
    assert [e["event_id"] for e in _data_events(raw)] == ["2"]


def test_endpoint_accepts_last_event_id_query_param(_fast_stream):
    """The frontend's manual backoff reconnect cannot set headers on
    EventSource, so the cursor arrives as ?last_event_id= (header wins)."""
    events.publish("tree", "run-a")
    events.publish("tree", "run-a")
    events.publish("tree", "run-a")
    h = _make_handler("/api/v1/events/stream?last_event_id=2")
    h.do_GET()
    assert [e["event_id"] for e in _data_events(h.wfile.getvalue())] == ["3"]
    # Header takes precedence over the query param when both are present.
    h2 = _make_handler(
        "/api/v1/events/stream?last_event_id=99",
        headers={"Last-Event-ID": "1"},
    )
    h2.do_GET()
    assert [e["event_id"] for e in _data_events(h2.wfile.getvalue())] == \
        ["2", "3"]


def test_endpoint_rejects_bad_subpath(_fast_stream):
    h = _make_handler("/api/v1/events/streamzzz")
    h.do_GET()
    assert ("status", 404) in h.sent
    assert json.loads(h.wfile.getvalue().decode("utf-8")) == {"error": "not found"}


# ── publication hooks ────────────────────────────────────────────────────


class _StopWatcher(Exception):
    pass


def test_watcher_publishes_tree_event_on_mtime_change(tmp_path, monkeypatch):
    ckpt = tmp_path / "20260723000000_evwatch"
    make_run_checkpoint(ckpt, nodes=5, seed=0)
    monkeypatch.setattr(_st, "_checkpoint_dir", ckpt)

    calls = {"n": 0}

    def fake_sleep(_s):
        calls["n"] += 1
        if calls["n"] == 2:
            # Second iteration: bump tree.json mtime (real change).
            import os
            st = (ckpt / "tree.json").stat()
            os.utime(ckpt / "tree.json", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        elif calls["n"] >= 3:
            raise _StopWatcher

    monkeypatch.setattr(state_sync, "time", SimpleNamespace(sleep=fake_sleep))
    with pytest.raises(_StopWatcher):
        state_sync._watcher_thread()

    evs = events.replay_since(0)
    assert [(e["topic"], e["run_id"]) for e in evs] == \
        [("tree", ckpt.name), ("tree", ckpt.name)]
    assert [e["revision"] for e in evs] == [1, 2]
    assert evs[0]["resource"] == f"/api/v1/runs/{ckpt.name}/tree"


def test_switch_checkpoint_publishes_run_event(tmp_path, monkeypatch):
    ckpt = tmp_path / "20260723000001_evswitch"
    make_run_checkpoint(ckpt, nodes=3, seed=1)
    # Register every global _api_switch_checkpoint mutates for restoration.
    for attr in (
        "_checkpoint_dir", "_settings_path", "_last_mtime", "_last_log_fh",
        "_last_log_path", "_last_experiment_md", "_launch_config",
        "_launch_llm_model", "_launch_llm_provider",
    ):
        monkeypatch.setattr(_st, attr, getattr(_st, attr))

    r = _api_switch_checkpoint(json.dumps({"path": str(ckpt)}).encode())
    assert r["ok"] is True
    evs = [e for e in events.replay_since(0) if e["topic"] == "run"]
    assert [e["run_id"] for e in evs] == [ckpt.name]
    assert evs[0]["resource"] == f"/api/v1/runs/{ckpt.name}/summary"
