"""Token accounting must cover the calls that FAILED, not just the ones that returned.

Why this matters for the study: "how many tokens did this experiment need" is
answered from ``cost_trace.jsonl``. Only ``success_callback`` was registered, so a
run that burnt half its budget on timeouts and retries reported the half that
happened to come back — under-reporting consumption, and hiding retry storms
entirely (a failed call looks identical to a call that never happened).

A failed call still SENT its prompt. Those tokens were spent. They are booked with
``status="failed"`` rather than mixed into the successes: counted in the totals,
but distinguishable, because tokens spent for nothing are not the same as tokens
spent on work.
"""

from __future__ import annotations

import json

import pytest

from ari import cost_tracker


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens, self.completion_tokens = p, c


class _Response:
    def __init__(self, p, c, model="m"):
        self.usage, self.model = _Usage(p, c), model


META = {"metadata": {"node_id": "node_aaaa1111", "phase": "react", "skill": "coding"}}


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    t = cost_tracker.init_from_env()
    assert t is not None
    return t


def _rows(tmp_path):
    return [json.loads(l) for l in (tmp_path / "cost_trace.jsonl").read_text().splitlines() if l.strip()]


def _summary(tmp_path):
    return json.loads((tmp_path / "cost_summary.json").read_text())


# --------------------------------------------------------------------------
# The gap this closes
# --------------------------------------------------------------------------

def test_failed_call_is_recorded(tracker, tmp_path):
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [{"role": "user", "content": "x " * 50}],
         "exception": TimeoutError("upstream"), **META}, None, 0, 1)
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "TimeoutError"


def test_failed_call_books_the_tokens_it_actually_sent(tracker, tmp_path):
    """No usage comes back from a failed call, but the prompt went over the wire.
    Booking 0 would record a burnt call as free."""
    cost_tracker._litellm_failure_handler(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "token " * 100}],
         "exception": RuntimeError("boom"), **META}, None, 0, 1)
    row = _rows(tmp_path)[0]
    assert row["prompt_tokens"] > 50, "prompt tokens must be counted from the request"
    assert row["completion_tokens"] == 0, "nothing was generated"
    assert row["total_tokens"] == row["prompt_tokens"]


def test_failed_call_keeps_its_node_and_phase(tracker, tmp_path):
    """Otherwise per-arm / per-node consumption cannot be attributed."""
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [], "exception": ValueError("x"), **META}, None, 0, 1)
    row = _rows(tmp_path)[0]
    assert (row["node_id"], row["phase"], row["skill"]) == ("node_aaaa1111", "react", "coding")


def test_partial_usage_from_a_failed_call_is_preferred_over_recounting(tracker, tmp_path):
    """When the provider does return usage on the error, trust it."""
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [{"role": "user", "content": "y " * 500}],
         "exception": RuntimeError("filtered"), **META}, _Response(77, 5), 0, 1)
    row = _rows(tmp_path)[0]
    assert (row["prompt_tokens"], row["completion_tokens"]) == (77, 5)


def test_missing_exception_still_books_the_call(tracker, tmp_path):
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [], **META}, None, 0, 1)
    assert _rows(tmp_path)[0]["error"] == "unknown"


def test_failure_handler_never_raises(tracker, tmp_path):
    """Accounting must not be able to break the LLM call path."""
    cost_tracker._litellm_failure_handler(None, None, 0, 1)
    cost_tracker._litellm_failure_handler({"messages": object()}, None, 0, 1)


def test_both_callbacks_are_installed():
    litellm = pytest.importorskip("litellm")
    cost_tracker._install_litellm_callback()
    names = lambda cbs: {getattr(c, "__name__", "") for c in (cbs or [])}
    assert "_litellm_success_handler" in names(litellm.success_callback)
    assert "_litellm_failure_handler" in names(litellm.failure_callback)


def test_callback_installation_is_idempotent():
    litellm = pytest.importorskip("litellm")
    for _ in range(3):
        cost_tracker._install_litellm_callback()
    n = sum(1 for c in (litellm.failure_callback or [])
            if getattr(c, "__name__", "") == "_litellm_failure_handler")
    assert n == 1


# --------------------------------------------------------------------------
# Successes and failures must stay separable
# --------------------------------------------------------------------------

def test_summary_separates_failed_from_ok(tracker, tmp_path):
    cost_tracker._litellm_success_handler({"model": "m", **META}, _Response(1000, 200), 0, 1)
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [{"role": "user", "content": "z " * 100}],
         "exception": TimeoutError("t"), **META}, None, 0, 1)
    s = _summary(tmp_path)
    assert s["call_count"] == 2
    assert s["failed_call_count"] == 1
    assert s["by_status"]["ok"]["tokens"] == 1200
    assert s["by_status"]["failed"]["tokens"] == s["failed_tokens"] > 0
    # Spent is spent: the total covers both.
    assert s["total_tokens"] == s["by_status"]["ok"]["tokens"] + s["failed_tokens"]


def test_a_clean_run_reports_no_failures(tracker, tmp_path):
    cost_tracker._litellm_success_handler({"model": "m", **META}, _Response(10, 2), 0, 1)
    s = _summary(tmp_path)
    assert s["failed_call_count"] == 0 and s["failed_tokens"] == 0
    assert set(s["by_status"]) == {"ok"}


def test_reload_preserves_status(tmp_path, monkeypatch):
    """A re-init (pipeline after cli) rebuilds records from the trace file. When
    that reload dropped fields, failed calls came back as ``status="ok"`` and the
    summary silently recounted them as successful work."""
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    cost_tracker.init_from_env()
    cost_tracker._litellm_failure_handler(
        {"model": "m", "messages": [{"role": "user", "content": "q " * 40}],
         "exception": TimeoutError("t"), **META}, None, 0, 1)

    cost_tracker.init_from_env()          # re-init: reloads from disk
    cost_tracker._litellm_success_handler({"model": "m", **META}, _Response(5, 1), 0, 1)

    s = _summary(tmp_path)
    assert s["failed_call_count"] == 1, "the reloaded failure was recounted as ok"
    assert s["by_status"]["ok"]["calls"] == 1


def test_reload_preserves_the_other_additive_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(tmp_path))
    t = cost_tracker.init_from_env()
    t.record(model="m", prompt_tokens=1, completion_tokens=1, component="memory",
             op="search", backend="letta", embedding_tokens=9, latency_ms=12.5)
    cost_tracker.init_from_env()
    t2 = cost_tracker.get()
    r = t2._records[0]
    assert (r.component, r.op, r.backend) == ("memory", "search", "letta")
    assert (r.embedding_tokens, r.latency_ms) == (9, 12.5)
