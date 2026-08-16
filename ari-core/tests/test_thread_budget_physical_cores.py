"""The timed team is sized in cores, not in CPUs.

``sched_getaffinity`` returns LOGICAL cpus. On a machine with 2-way
simultaneous multithreading that is twice the cores, so the budget came out at
two threads per core and ``OMP_PLACES=cores`` had to put both on one -- sharing
its execution units, with which sibling lands beside which, and how much it
contends, varying from run to run.

MEASURED, and it decided where this instrument could be registered. The clean
control is the reference scored against itself, so it should read 1.0 every
time. On the SMT-free aarch64 node at 48 threads it read within 0.6%; on an x86
node at a 64-thread budget it read 0.983 / 1.071 / 1.006. A spread of 7-16%
cannot resolve the difference a regression verdict is quoted to, so the x86
registration was rejected -- and the aarch64 one passed for a reason nobody had
noticed: that machine has no SMT, so its logical count already was its core
count. The budget was right by accident on one machine and wrong on the other.

The placement record could not have told anyone that, because it wrote the CPU
count and the budget and nothing about cores. It writes both now.
"""

from __future__ import annotations

import os

from ari.assurance.native_perf_common import (
    allowed_cpus,
    measurement_placement,
    measurement_thread_regime,
    physical_cores,
)


def test_the_budget_never_exceeds_the_cores_it_will_run_on():
    """THE DEFECT. On a 2-way SMT host the old budget was exactly twice this."""
    cores = physical_cores()
    if cores is None:
        import pytest
        pytest.skip("this host does not expose cpu topology")
    budget = int(measurement_thread_regime()["OMP_NUM_THREADS"])
    assert budget <= cores, (
        f"the timed team is {budget} threads on {cores} cores, so threads share "
        f"cores and the run-to-run spread stops resolving")


def test_the_budget_is_the_core_count_when_the_topology_is_readable(monkeypatch):
    monkeypatch.delenv("ARI_PERF_THREADS", raising=False)
    cores = physical_cores()
    if cores is None:
        import pytest
        pytest.skip("this host does not expose cpu topology")
    assert int(measurement_thread_regime()["OMP_NUM_THREADS"]) == cores


def test_an_explicit_budget_still_wins():
    """The override is how a measurement brackets the boundary deliberately."""
    previous = os.environ.get("ARI_PERF_THREADS")
    os.environ["ARI_PERF_THREADS"] = "3"
    try:
        assert measurement_thread_regime()["OMP_NUM_THREADS"] == "3"
    finally:
        if previous is None:
            os.environ.pop("ARI_PERF_THREADS", None)
        else:
            os.environ["ARI_PERF_THREADS"] = previous


def test_cores_never_exceed_the_cpus_they_are_folded_from():
    cores = physical_cores()
    if cores is None:
        import pytest
        pytest.skip("this host does not expose cpu topology")
    assert 0 < cores <= len(allowed_cpus())


def test_the_placement_records_the_cores_and_the_smt_ratio():
    """Two allocations of 64 logical cpus -- one of 64 cores, one of 32 with two
    threads each -- used to write identical placements while behaving
    differently enough that the instrument resolved on one and not the other."""
    place = measurement_placement()
    assert "physical_cores" in place
    assert "threads_per_core" in place
    if place["physical_cores"]:
        assert place["threads_per_core"] == round(
            place["cpus_allowed_count"] / place["physical_cores"], 2)
        assert int(place["thread_budget"]) <= place["physical_cores"]
