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
from pathlib import Path

import yaml

from ari.assurance.models import HarnessManifestV1
from ari.assurance.request import _worker_argv
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


# --- what actually governs resolution -----------------------------------------

def test_a_case_records_how_long_it_was_timed_for():
    """The record carried the spread and not the duration it is a fraction of.

    That is why "did not resolve" read as noise from an unspecified source. The
    sweep that settled it varied ONLY the thread budget on one exclusive node,
    so the case and the machine were fixed and the duration was not: 81 ms gave
    a spread of 0.0012 and 3.3 ms gave 0.214, with the worst reading at ONE
    thread per core and the best-but-one at two per core -- the opposite of what
    core sharing would predict.
    """
    from ari.assurance.native_perf_common import PerfCaseResultV1

    assert "median_seconds" in PerfCaseResultV1.model_fields


#: WHAT THE FLOOR IS DERIVED FROM. The clean control is the frozen reference
#: scored against itself, so its right answer is 1.0 and any departure is the
#: instrument's own error at that duration. Forty runs per thread budget on an
#: idle exclusive x86 node, one case, timed at ten durations: ``seconds ->
#: worst |1 - ratio| over the forty``.
#:
#: The old floor was set from a six-point sweep of the SPREAD and landed at
#: 5 ms, inside the region where this error is 0.11-0.18 -- so a run at 5-10 ms
#: was told it was on a noisy machine when the answer was that its case is too
#: small for the machine. Those are opposite instructions.
MEASURED_DEVIATION_BY_DURATION = {
    0.0035: 0.2569, 0.0047: 0.1480, 0.0059: 0.1795, 0.0075: 0.1122,
    0.0107: 0.0901, 0.0138: 0.0826, 0.0209: 0.0444, 0.0273: 0.0431,
    0.0408: 0.0078, 0.0809: 0.0128,
}


def test_the_error_is_a_fixed_jitter_and_not_a_fixed_ratio():
    """The claim the floor's SHAPE rests on, held as a measurement.

    A floor stated in seconds is only meaningful if the instrument's error is
    roughly constant in seconds. Re-read as ``spread x median`` the sweep says
    it is: across a 23-fold range of durations the absolute deviation stays
    inside a 3.7-fold band while the relative deviation moves 33-fold. That is
    what makes the relative spread "jitter divided by duration" rather than a
    property of the case, and it is what says the quantity to carry to another
    machine is the jitter and not this number of milliseconds.
    """
    durations = sorted(MEASURED_DEVIATION_BY_DURATION)
    absolute = [seconds * MEASURED_DEVIATION_BY_DURATION[seconds]
                for seconds in durations]
    relative = [MEASURED_DEVIATION_BY_DURATION[seconds] for seconds in durations]
    duration_span = durations[-1] / durations[0]
    assert duration_span > 20, duration_span
    assert max(relative) / min(relative) > 20, (
        "the relative deviation barely moved, so it is not dominated by the "
        "duration and this whole account of the floor is wrong")
    assert max(absolute) / min(absolute) < 5, (
        f"the absolute deviation spans {max(absolute) / min(absolute):.1f}x "
        f"across {duration_span:.0f}x of duration, so it is not a fixed jitter "
        f"and a floor stated in seconds does not describe it")


def test_the_resolving_floor_is_where_the_clean_control_re_enters_the_band():
    """Derived, not chosen, and derived from the quantity it labels.

    Below the floor the clean control must be OUT of the band the instrument is
    trusted at -- otherwise the floor calls a good measurement too short. Above
    it the control must be IN the band at every longer duration -- otherwise the
    floor calls a measurement resolved that the instrument's own bound does not.
    """
    from ari.assurance.drivers.perf import _MAX_CLEAN_SPREAD, _MIN_RESOLVING_SECONDS

    assert _MIN_RESOLVING_SECONDS == 0.010
    assert _MAX_CLEAN_SPREAD == 0.1
    for seconds, deviation in sorted(MEASURED_DEVIATION_BY_DURATION.items()):
        if seconds < _MIN_RESOLVING_SECONDS:
            assert deviation > _MAX_CLEAN_SPREAD, (
                f"{seconds}s strayed {deviation}, inside the trusted band, so a "
                f"floor above it labels a measurement that resolved as too short")
        else:
            assert deviation <= _MAX_CLEAN_SPREAD, (
                f"{seconds}s strayed {deviation}, outside the trusted band, so a "
                f"floor below it labels an unresolved measurement as merely noisy")


def _perf_manifest():
    path = (Path(__file__).resolve().parents[1] / "config" / "harnesses"
            / "builtin" / "hpc_gemm_performance.yaml")
    return HarnessManifestV1.model_validate(yaml.safe_load(
        path.read_text(encoding="utf-8")))


def test_the_pinned_budget_travels_in_the_argv():
    """THE DEFECT. The budget was ambient, and the container drops ambient.

    ``measurement_thread_regime`` reads ``ARI_PERF_THREADS`` from the
    environment. The container executor launches with ``--cleanenv`` and passes
    exactly one variable through, so a budget exported beside a governed run did
    not arrive: the manifest recorded the host-side number and the timed child
    ran the machine's full width. MEASURED on one exclusive node, the same clean
    control read 18.2 ms at a spread of 0.024 with the pinned budget in force
    and 3.2 ms at a spread of 0.164 without it -- the case being too short to
    resolve at full width. The pin described something the run did not do.
    """
    manifest = _perf_manifest()
    budget = manifest.registered_placement["thread_budget"]
    argv = _worker_argv(manifest, _Declaration(), tier="validate", seed=1)
    assert "--threads" in argv, (
        "the pinned placement's thread budget does not reach the worker; the "
        "container drops the environment, so an argv without it measures at a "
        "width the manifest does not pin")
    assert argv[argv.index("--threads") + 1] == str(budget)


def test_the_worker_applies_the_budget_it_is_handed(monkeypatch):
    """Carried is not enforced until something sets the regime from it.

    ``verify_native_perf`` does not take a thread count; the regime is read from
    the environment inside the measurement. So the worker's job is to put the
    carried number where that read will find it, before the measurement starts.
    """
    from ari.assurance.drivers import perf_worker

    seen = {}

    def capture(*args, **kwargs):
        seen["threads"] = os.environ.get("ARI_PERF_THREADS")
        raise _Stop()

    monkeypatch.setattr(perf_worker, "verify_native_perf", capture)
    monkeypatch.delenv("ARI_PERF_THREADS", raising=False)
    try:
        perf_worker.main([
            "--problem", "gemm-dense-fp64/v1@2026q3",
            "--candidate", "candidate_gemm.c",
            "--tier", "screen", "--seed", "1",
            "--dataset-revision", "native-perf-gemm-cases/v1@scored-2026q3",
            "--threads", "4",
        ])
    except _Stop:
        pass
    assert seen.get("threads") == "4", (
        "the worker took the budget and did not put it where "
        "measurement_thread_regime looks, so the flag is decoration")


class _Stop(Exception):
    """Stops the worker once the environment it built has been observed."""


class _Declaration:
    logical_name = "candidate_gemm.c"
    compiler = None
    compile_flags = None
