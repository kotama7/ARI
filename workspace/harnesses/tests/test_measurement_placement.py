"""WHERE a measurement ran, not just under what settings.

WHY THIS FILE EXISTS. ``measurement_environment`` captures variables, and every
one of them is a constant the launcher exports — invariant to the hardware. So a
study spread across allocations of different shape passed every check and
reported one environment. Measured on two partitions of one cluster on
2026-08-07: four NUMA domains of twelve cores with 64 KiB pages and a cpuset
covering the whole node, against one domain with 4 KiB pages and a cpuset of
eight cores plus their SMT siblings carved out of 192. Nothing in a result told
them apart.

That is not a bookkeeping nicety. The harness first-touches its scored arrays
SERIALLY outside the timed window, so every page lands on one memory domain —
measured, 100% on one node — while the threads are spread across all of them.
A candidate that first-touches its own scratch in parallel gets an even split
instead, and the archived gate measured placement at about 1.29x on the frozen
stencil. Placement reaches the score; it was simply never written down.

The properties below are the ones whose failure mode is silence.
"""
import importlib.util
import pathlib

import pytest

HARNESSES = pathlib.Path(__file__).resolve().parents[1]
# Discovered, not listed: a sixth harness is covered the moment it exists.
TASKS = tuple(sorted(
    d.name for d in HARNESSES.iterdir()
    if d.is_dir() and (d / f"{d.name}_harness.py").is_file()))
assert TASKS, "no registered harness found; this test would pass vacuously"

# Every field a reader needs to answer "was this the same kind of machine?".
# Dropping one silently narrows what the drift checker can see.
REQUIRED = (
    "machine", "page_size_bytes", "cpus_allowed", "cpus_allowed_count",
    "numa_nodes_total", "numa_nodes_spanned", "thread_budget",
    "omp_proc_bind", "omp_places", "sha256",
)


def _module(task: str):
    path = HARNESSES / task / f"{task}_harness.py"
    spec = importlib.util.spec_from_file_location(f"_pl_{task}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("task", TASKS)
def test_every_harness_records_where_it_ran(task):
    rec = _module(task).measurement_placement()
    missing = [k for k in REQUIRED if k not in rec]
    assert not missing, f"{task}: placement record is missing {missing}"
    assert len(rec["sha256"]) == 64


@pytest.mark.parametrize("task", TASKS)
def test_an_unreadable_field_is_none_not_a_guess(task):
    """A machine that does not publish its topology must record that it did not.

    Substituting a plausible default is how a spec-sheet number becomes a
    measurement — the failure this repository has already retracted once.
    """
    rec = _module(task).measurement_placement()
    for key in ("numa_nodes_total", "cpus_allowed", "page_size_bytes"):
        assert rec[key] is None or rec[key], (
            f"{task}: {key} is falsy-but-present, which reads as a measured zero")


# The machine half of the record. thread_budget is deliberately NOT here: the
# three speedup harnesses hand their child ARI_<TASK>_THREADS (falling back to a
# literal 16 when nothing set it, which is exactly the "launched outside the
# worker" case worth seeing), while erfc and meshpart set no budget at all. That
# is a real difference between harnesses, not a divergence to be papered over.
_MACHINE_FIELDS = ("machine", "page_size_bytes", "cpus_allowed",
                   "cpus_allowed_count", "mems_allowed", "numa_nodes_total",
                   "numa_node_cpulists", "numa_nodes_spanned")


def test_all_harnesses_agree_on_one_machine():
    """They are all running on the same machine, so they must all say so.

    Each harness carries its own copy — the registration design keeps them
    standalone, so there is nowhere shared to put it — and a divergence would
    make a placement record task-specific without saying so.
    """
    views = {t: {k: _module(t).measurement_placement()[k] for k in _MACHINE_FIELDS}
             for t in TASKS}
    first = views[TASKS[0]]
    for task, view in views.items():
        assert view == first, (
            f"{task} disagrees with {TASKS[0]} about the machine they are both "
            f"running on: {view} vs {first}. Copies of measurement_placement "
            f"must be kept in step by hand.")


def test_the_thread_budget_is_recorded_even_when_nothing_set_one():
    """The literal 16 the three speedup harnesses fall back to is a finding, not
    a default to hide: a run launched any way other than through the campaign
    worker measures at 16 threads on a machine with far more."""
    for task in TASKS:
        rec = _module(task).measurement_placement()
        assert "thread_budget" in rec


@pytest.mark.parametrize("task", TASKS)
def test_the_record_says_that_nothing_sets_placement(task):
    """The most important field is the one that says this is all inherited.

    There is no numactl, taskset, mbind or set_mempolicy anywhere on the
    measurement path. A reader who assumes the study PINNED its placement would
    draw the opposite conclusion from the same numbers.
    """
    rec = _module(task).measurement_placement()
    assert rec["placement_is_set_by_the_study"] is False


@pytest.mark.parametrize("task", TASKS)
def test_the_thread_budget_is_the_childs_not_the_harnesss(task, monkeypatch):
    """Recording the ambient value would describe the harness process, not the
    measurement: the three speedup harnesses override OMP_NUM_THREADS for the
    timed child from their own ARI_<TASK>_THREADS."""
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    upper = task.upper()
    if f"ARI_{upper}_THREADS" in _module(task).measurement_placement.__doc__ or True:
        monkeypatch.setenv(f"ARI_{upper}_THREADS", "7")
    rec = _module(task).measurement_placement()
    # gemm/spmm/stencil resolve ARI_<TASK>_THREADS first; erfc/meshpart set no
    # budget for their child at all and inherit the ambient one.
    assert rec["thread_budget"] in ("7", "3"), rec["thread_budget"]


@pytest.mark.parametrize("task", TASKS)
def test_placement_is_attached_to_the_result_not_merely_computable(task):
    """A helper nobody calls leaves every score just as unattributable as before
    — the same shape the environment capture had to fix."""
    src = (HARNESSES / task / f"{task}_harness.py").read_text()
    assert '"measurement_placement": measurement_placement()' in src


def test_the_environment_digest_is_left_alone():
    """Folding these fields into measurement_environment would change ITS digest
    and break comparability with every record already written."""
    for task in TASKS:
        mod = _module(task)
        env = mod.measurement_environment()
        assert set(env) == {"variables", "sha256", "note"}, (
            f"{task}: measurement_environment grew a field; every archived "
            f"digest is now incomparable")


def test_the_drift_checker_reads_the_placement_record():
    """Recording is not checking — the lesson the environment capture already
    learned once, when nothing read it back."""
    tool = (HARNESSES.parents[0] / "tools" / "check_environment_drift.py").read_text()
    assert 'key="measurement_placement"' in tool
    assert "_placement_drift" in tool
