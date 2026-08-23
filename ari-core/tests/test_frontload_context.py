"""Front-loading the node's own state must remove round trips, not add leaks.

On the previous campaign about 27.5% of all ReAct steps went on listing the work
dir, reading back the inherited candidate, and re-probing the environment. With
the budget cut to 20 those steps are the difference between iterating on the
kernel and never reaching it. Everything front-loaded is already reachable
through the agent's own tools, so the block must grant nothing new — these tests
pin both halves of that: the content arrives, and nothing outside the node's own
directory does.
"""
import pathlib

from ari.agent.loop import build_workdir_context_messages as build


def _wd(tmp_path, **files):
    d = tmp_path / "node"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body)
    return str(d)


def test_returns_nothing_for_a_missing_or_empty_dir(tmp_path):
    assert build(str(tmp_path / "nope")) == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build(str(empty)) == []


def test_candidate_source_and_flags_are_carried_in_full(tmp_path):
    src = "void gemm(int n){/* body */}\n" * 20
    wd = _wd(tmp_path, **{"candidate_gemm.c": src,
                          "candidate_flags.txt": "-O3 -march=native\n",
                          "Makefile": "all:\n"})
    msgs = build(wd)
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    body = msgs[0]["content"]
    assert src.strip() in body, "the candidate the node edits was not front-loaded"
    assert "-O3 -march=native" in body
    assert "Makefile" in body          # listed...
    assert "all:" not in body          # ...but not dumped: only the edited files


def test_hidden_files_are_not_exposed(tmp_path):
    """.lastgood/ and friends are harness bookkeeping, not agent-facing."""
    wd = _wd(tmp_path, **{"candidate_x.c": "int x;", ".secret": "do-not-show"})
    body = build(wd)[0]["content"]
    assert ".secret" not in body and "do-not-show" not in body


def test_is_capped_so_one_huge_file_cannot_crowd_out_the_prompt(tmp_path):
    wd = _wd(tmp_path, **{"candidate_big.c": "x" * 500_000})
    body = build(wd, max_chars=5000)[0]["content"]
    assert len(body) <= 5000 + 64
    assert "truncated" in body


def test_environment_summary_is_included_only_when_given(tmp_path):
    wd = _wd(tmp_path, **{"candidate_a.c": "int a;"})
    assert "do not re-query" not in build(wd)[0]["content"]
    assert "gcc 8.5" in build(wd, env_summary="gcc 8.5")[0]["content"]


def test_the_front_loaded_environment_is_the_HARDWARE_not_the_queue():
    """Regression: the first version front-loaded the wrong function.

    get_environment_summary() returns scheduler, container and a partition
    table — a queue listing. It carries no CPU, no NUMA topology and no cache
    geometry, so front-loading it handed the agent a list of partitions while
    the code claimed to have given it the machine. An architecture-aware
    implementation needs the second set and none of the first.
    """
    from ari.agent.loop import _frontload_env_summary

    s = _frontload_env_summary()
    if not s:
        import pytest
        pytest.skip("environment probe unavailable on this host")
    assert "arch:" in s and "threads:" in s, "the hardware catalogue is missing"
    assert "cpu_model:" in s
    # The two that the reviewers' questions turned on, and that the previous
    # campaign's agents could not see.
    assert "numa:" in s or "cache_measured:" in s, (
        "neither the NUMA topology nor the measured cache reached the agent")


def test_the_environment_probe_is_computed_once_per_process():
    """It costs seconds, almost all of it the cache measurement.

    Recomputing per node would add that to every node in the campaign for an
    answer that cannot change between nodes on one host.
    """
    import time

    from ari.agent.loop import _frontload_env_summary

    _frontload_env_summary()          # warm
    t0 = time.monotonic()
    _frontload_env_summary()
    assert time.monotonic() - t0 < 0.05, "the probe is being re-run per call"
