"""A node waiting on a scheduler job must not hold a concurrency slot.

Nodes run in a ThreadPoolExecutor capped at four. A node blocked on a SLURM job
held one of those slots for the whole job while using no CPU, so four such
nodes stalled the entire search. Concurrency is now bounded by a semaphore the
node hands back while it can only wait; the pool is sized larger so a parked
thread has somewhere to sit.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ari.agent.loop import (
    _append_poll_observation,
    _completion_marker_path,
    conversation_chars,
    context_budget_chars,
    parked_for_job,
    set_node_concurrency_gate,
)


def test_parking_is_a_no_op_without_a_gate():
    # AgentLoop must stay usable on its own; only the orchestrator installs one.
    set_node_concurrency_gate(None)
    with parked_for_job("job"):
        pass


def test_parking_releases_and_retakes_the_permit():
    gate = threading.Semaphore(1)
    set_node_concurrency_gate(gate)
    try:
        gate.acquire()
        assert not gate.acquire(blocking=False), "precondition: permit is held"
        with parked_for_job("job"):
            # Released while parked, so somebody else can run.
            assert gate.acquire(blocking=False)
            gate.release()
        # Taken back on the way out, so post-wait work obeys the same limit.
        assert not gate.acquire(blocking=False)
        gate.release()
    finally:
        set_node_concurrency_gate(None)


def test_a_waiting_node_does_not_block_other_nodes():
    """The property C exists for, measured rather than asserted structurally."""
    max_active, job_wait = 2, 0.4
    gate = threading.Semaphore(max_active)
    set_node_concurrency_gate(gate)
    peak = {"held": 0, "now": 0}
    lock = threading.Lock()
    started = time.monotonic()
    compute_finished = []

    def node(waits: bool):
        gate.acquire()
        with lock:
            peak["now"] += 1
            peak["held"] = max(peak["held"], peak["now"])
        try:
            if waits:
                with lock:
                    peak["now"] -= 1
                with parked_for_job("job"):
                    time.sleep(job_wait)
                with lock:
                    peak["now"] += 1
            else:
                compute_finished.append(time.monotonic() - started)
        finally:
            with lock:
                peak["now"] -= 1
            gate.release()

    work = [True] * max_active + [False] * 4
    try:
        with ThreadPoolExecutor(max_workers=max_active + 8) as ex:
            list(ex.map(node, work))
    finally:
        set_node_concurrency_gate(None)

    # Every waiter is parked, so the compute nodes must not have queued behind
    # them for the length of the job.
    assert max(compute_finished) < job_wait, compute_finished
    # And the limit still holds: parking frees a slot, it does not add one.
    assert peak["held"] <= max_active


def test_poll_observations_stay_far_inside_the_context_budget():
    """State is idempotent, so only transitions are recorded.

    Appending every poll put tens of thousands of characters of repetition
    into the budget; _build_safe_window then keeps the last messages, which
    were the polls, and dropped the agent's own reasoning instead.
    """
    result = '{"status": "RUNNING", "job_id": "1"}'
    transitions = []
    for i, _ in enumerate(("PENDING", "RUNNING", "COMPLETED"), start=1):
        _append_poll_observation(transitions, "job_status", "1", i, result)
    assert conversation_chars(transitions) < context_budget_chars() // 10


def test_marker_path_is_derived_not_exposed():
    digest = "b" * 64
    path = _completion_marker_path("/w", {"request_digest": "sha256:" + digest})
    assert path == __import__("pathlib").Path(
        "/w/.ari-hpc") / digest / "wrapper-completion-v1.json"
    # A digest that is not a digest must never become a path component.
    assert _completion_marker_path("/w", {"request_digest": "../../etc"}) is None
    assert _completion_marker_path("", {"request_digest": digest}) is None
    assert _completion_marker_path("/w", "not json") is None
