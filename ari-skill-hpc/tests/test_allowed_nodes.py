"""A site can bound the nodes ARI is allowed to place work on.

Configured through the environment rather than a tracked file: node names are
site identity and this repository does not carry them. Unset — the default —
means no restriction and every request passes through untouched.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ari_skill_hpc.contracts import ResourceRequestV1
from ari_skill_hpc.scheduler import (
    ALLOWED_NODES_ENV,
    SchedulerValidationError,
    SlurmScheduler,
    allowed_nodes_from_env,
    expand_hostlist,
)

from test_slurm_local import CommandResult, FakeRunner, _request, _scheduler


# ── hostlist expansion ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "spec,expected",
    [
        ("", set()),
        ("n01", {"n01"}),
        ("n01,n02", {"n01", "n02"}),
        ("n[01-04]", {"n01", "n02", "n03", "n04"}),
        ("n[1,3-5]", {"n1", "n3", "n4", "n5"}),
        ("n[01-02]x", {"n01x", "n02x"}),
        # A comma inside brackets is part of the range, not a separator.
        ("a,n[1-2],b", {"a", "b", "n1", "n2"}),
    ],
)
def test_expansion(spec, expected):
    assert expand_hostlist(spec) == expected


def test_zero_padding_is_significant():
    # n01 and n1 are different nodes; collapsing them would let a request onto
    # a node the policy never named.
    assert expand_hostlist("n[01-02]") == {"n01", "n02"}
    assert expand_hostlist("n[1-2]") == {"n1", "n2"}


@pytest.mark.parametrize(
    "spec", ["n[01-", "n]01[", "n[a-b]", "n[04-01]", "n[0-99999]", "bad name!"])
def test_expansion_fails_closed(spec):
    """Anything that cannot be expanded EXACTLY must raise.

    This backs an allowlist: a spec that cannot be proven inside the allowed
    set has to be refused, not admitted because it looked unfamiliar.
    """
    with pytest.raises(SchedulerValidationError):
        expand_hostlist(spec)


def test_env_is_read_and_empty_by_default(monkeypatch):
    monkeypatch.delenv(ALLOWED_NODES_ENV, raising=False)
    assert allowed_nodes_from_env() == frozenset()
    monkeypatch.setenv(ALLOWED_NODES_ENV, "cn[01-02]")
    assert allowed_nodes_from_env() == {"cn01", "cn02"}


# ── enforcement ────────────────────────────────────────────────────────────

def _resources(nodelist: str = "") -> ResourceRequestV1:
    return ResourceRequestV1(partition="p", nodes=1, walltime="00:05:00",
                             nodelist=nodelist or None)


def _sched(tmp_path: Path, allowed: str) -> SlurmScheduler:
    s = _scheduler(tmp_path, FakeRunner(CommandResult("1;c\n", "", 0)))
    s.allowed_nodes = expand_hostlist(allowed)
    return s


def test_no_policy_leaves_the_request_untouched(tmp_path):
    s = _sched(tmp_path, "")
    r = _resources()
    assert s._confine_to_allowed_nodes(r) is r


def test_an_unnamed_request_is_confined_not_rejected(tmp_path):
    """Without a nodelist the scheduler may pick any node in the partition —
    exactly what the policy exists to prevent — so it is filled in."""
    s = _sched(tmp_path, "cn[01-03]")
    assert expand_hostlist(
        s._confine_to_allowed_nodes(_resources()).nodelist) == {
            "cn01", "cn02", "cn03"}


def test_a_request_inside_the_policy_is_not_narrowed(tmp_path):
    # Narrowing silently would run something other than what was asked for.
    s = _sched(tmp_path, "cn[01-03]")
    assert s._confine_to_allowed_nodes(_resources("cn02")).nodelist == "cn02"


def test_a_request_outside_the_policy_is_refused(tmp_path):
    s = _sched(tmp_path, "cn[01-03]")
    with pytest.raises(SchedulerValidationError):
        s._confine_to_allowed_nodes(_resources("cn02,cn09"))


def test_the_refusal_does_not_name_the_nodes(tmp_path):
    # Error text reaches logs and tool responses; site identity must not.
    s = _sched(tmp_path, "cn[01-03]")
    with pytest.raises(SchedulerValidationError) as exc:
        s._confine_to_allowed_nodes(_resources("secret-node-7"))
    assert "secret-node-7" not in str(exc.value)


def test_an_unexpandable_nodelist_is_refused_under_policy(tmp_path):
    s = _sched(tmp_path, "cn[01-03]")
    with pytest.raises(SchedulerValidationError):
        s._confine_to_allowed_nodes(_resources("cn[01-"))


def test_the_bridge_is_confined_too(tmp_path):
    """slurm_submit must not be a way around the typed path's policy."""
    runner = FakeRunner(CommandResult("1;c\n", "", 0))
    s = _scheduler(tmp_path, runner)
    s.allowed_nodes = expand_hostlist("cn[01-02]")
    asyncio.run(s.submit_script_bridge(
        script="make", job_name="b", partition="p", nodes=1,
        walltime="00:05:00", work_dir=str(tmp_path)))
    assert "#SBATCH --nodelist=cn01,cn02" in runner.calls[0][1].decode()


def test_confinement_changes_the_claim_identity(tmp_path):
    """Two requests differing only in where they may run are different jobs.

    If confinement happened after the digest, a resumed run could inherit a
    claim made under a wider policy and return its result.
    """
    base = _request(tmp_path)
    wide = _sched(tmp_path, "cn[01-03]")._confine_to_allowed_nodes(base.resources)
    narrow = _sched(tmp_path, "cn01")._confine_to_allowed_nodes(base.resources)
    assert (base.model_copy(update={"resources": wide}).request_digest
            != base.model_copy(update={"resources": narrow}).request_digest)


# ── multi-node shape through the bridge ────────────────────────────────────

def test_the_bridge_can_request_a_multi_node_shape(tmp_path):
    """`nodes` alone is not enough to use more than one node.

    The allocation shape has four parts and the bridge exposed only `nodes`,
    so a script could take four nodes and still be given one task on one of
    them. All four now reach the batch header.
    """
    runner = FakeRunner(CommandResult("1;c\n", "", 0))
    s = _scheduler(tmp_path, runner)
    asyncio.run(s.submit_script_bridge(
        script="srun --ntasks=8 ./bench", job_name="b", partition="p",
        nodes=2, tasks=8, tasks_per_node=4, cpus_per_task=12,
        walltime="00:10:00", work_dir=str(tmp_path)))
    script = runner.calls[0][1].decode()
    for header in ("--nodes=2", "--ntasks=8", "--ntasks-per-node=4",
                   "--cpus-per-task=12"):
        assert f"#SBATCH {header}" in script, header


def test_the_bridge_still_defaults_to_a_single_task(tmp_path):
    # Unspecified must stay what it was, so existing callers are untouched.
    runner = FakeRunner(CommandResult("1;c\n", "", 0))
    s = _scheduler(tmp_path, runner)
    asyncio.run(s.submit_script_bridge(
        script="make", job_name="b", partition="p", nodes=1,
        walltime="00:10:00", work_dir=str(tmp_path)))
    assert "#SBATCH --ntasks=1" in runner.calls[0][1].decode()


def test_the_shape_is_part_of_the_claim(tmp_path):
    # Same script on a different allocation shape is a different job; folding
    # them onto one claim would return the first shape's result for the second.
    seen = []
    for shape in ({"nodes": 1, "tasks": 1}, {"nodes": 4, "tasks": 16}):
        runner = FakeRunner(CommandResult("1;c\n", "", 0))
        s = _scheduler(tmp_path / f"n{shape['nodes']}", runner)
        h = asyncio.run(s.submit_script_bridge(
            script="./bench", job_name="b", partition="p",
            walltime="00:10:00", work_dir=str(tmp_path), **shape))
        seen.append(h.request_digest)
    assert seen[0] != seen[1]


# ── how the payload is launched inside the allocation ──────────────────────

def _shape(**kw) -> ResourceRequestV1:
    return ResourceRequestV1(partition="p", walltime="00:10:00", **kw)


def test_auto_binds_a_single_task_and_leaves_larger_shapes_alone():
    """The historical behaviour, unchanged and now pinned.

    A batch step inherits the whole node's affinity mask, so a threaded
    payload spreads across the machine and loses to its own serial baseline —
    which reads as a slow kernel rather than an unbound allocation.
    """
    one = SlurmScheduler._bound_step_command(
        ["./bench"], _shape(nodes=1, tasks=1, cpus_per_task=8))
    assert one == ["srun", "--ntasks=1", "--cpus-per-task=8", "./bench"]
    # Several tasks under `auto` are assumed to launch themselves.
    assert SlurmScheduler._bound_step_command(
        ["mpirun", "-np", "8", "./bench"],
        _shape(nodes=2, tasks=8)) == ["mpirun", "-np", "8", "./bench"]


def test_srun_launches_the_declared_shape():
    step = SlurmScheduler._bound_step_command(
        ["./bench"],
        _shape(nodes=2, tasks=8, tasks_per_node=4, cpus_per_task=6,
               launcher="srun"))
    assert step[0] == "srun"
    # --nodes is passed too: otherwise Slurm may pack the tasks onto fewer
    # nodes than the allocation holds, which is not the requested shape.
    for flag in ("--nodes=2", "--ntasks=8", "--cpus-per-task=6",
                 "--ntasks-per-node=4"):
        assert flag in step, flag
    assert step[-1] == "./bench"


def test_none_never_wraps():
    assert SlurmScheduler._bound_step_command(
        ["./bench"], _shape(nodes=1, tasks=1, launcher="none")) == ["./bench"]


def test_the_launcher_is_part_of_the_claim(tmp_path):
    """Same script, same shape, different launch = different job.

    One runs the payload once, the other runs it `tasks` times. Sharing a
    claim would return the wrong one's result.
    """
    base = _request(tmp_path)
    digests = set()
    for mode in ("auto", "srun"):
        resources = base.resources.model_copy(
            update={"nodes": 2, "tasks": 8, "launcher": mode})
        digests.add(base.model_copy(
            update={"resources": resources}).request_digest)
    assert len(digests) == 2


def test_auto_is_the_default():
    # A caller that says nothing must keep the behaviour it had.
    assert _shape().launcher == "auto"
