"""A problem may be free, so the boundary it cannot cross has to be mechanical.

The decision this file pins: a research problem is PINNED but not APPROVED. It
supplies inputs -- scaffolding, goal text, case set, entry point -- and a new
research theme is a new directory rather than an ARI edit or a signing ceremony.
That is only safe if a problem is structurally incapable of touching the things
that make a measurement trustworthy: compiler flags, the timed window, the
thread regime, the oracle, the rules the reference is built by.

"We reviewed the problem files" is not that guarantee, because nobody signs
them. ``extra="forbid"`` plus the absence of any such field is, and these tests
are what keep it true when someone later adds a convenient field.
"""

from __future__ import annotations

import pytest

from ari.assurance.problems import (PROBLEM_STATEMENT_NAME, ProblemError,
                                    load_problem, materialize,
                                    problems_root, registered_problems)

_HEADER = "void widget(int n, const double *a, double *b);\n"
_DRIVER = "int main(void){return 0;}\n"
_REFERENCE = "/* the denominator */\n"
_SEED = "/* correct, unoptimised */\n"

_MANIFEST = """\
schema_version: ari.harness-problem/v1
id: widget
revision: widget/v1@test
family: widget
entry_point: widget
description: A problem used to test the problem mechanism.
scaffolding:
  contract_header: widget.h
  driver: widget_main.c
  reference: reference_widget.c
  seed_candidate: seed_widget.c
score_inputs: [candidate.c]
case_set: widget-cases/v1@test
axis: speedup
denominator: competent_frozen
goal: |
  Make widget faster without changing what it computes.
"""


@pytest.fixture
def problem(tmp_path, monkeypatch):
    root = tmp_path / "problems"
    d = root / "widget"
    d.mkdir(parents=True)
    (d / "problem.yaml").write_text(_MANIFEST)
    (d / "widget.h").write_text(_HEADER)
    (d / "widget_main.c").write_text(_DRIVER)
    (d / "reference_widget.c").write_text(_REFERENCE)
    (d / "seed_widget.c").write_text(_SEED)
    monkeypatch.setenv("ARI_HARNESS_PROBLEMS", str(root))
    return d


def _rewrite(d, **replacements):
    text = (d / "problem.yaml").read_text()
    for old, new in replacements.items():
        assert old in text, f"fixture drifted: {old!r} is no longer in the manifest"
        text = text.replace(old, new)
    (d / "problem.yaml").write_text(text)


# --------------------------------------------------------------------------
# the boundary that lets a problem be unapproved
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "candidate_flags: ['-ffast-math']",
    "repetitions: 1",
    "regression_threshold: 0.0",
    "residual_tolerance: 1e9",
    "omp_num_threads: 1",
    "reference_flags: ['-O0']",
])
def test_a_problem_cannot_declare_anything_that_weakens_the_instrument(problem, field):
    """The whole approval decision rests on this.

    A problem is pinned but nobody signs it, so the reason an untrusted problem
    file is safe cannot be "a reviewer would notice". Each of these would move a
    number the verdict is read off -- a threshold, a tolerance, the flags one
    side is built with -- and none of them has a field here, so the closed
    schema refuses the file outright instead of ignoring the key.
    """
    (problem / "problem.yaml").write_text(
        (problem / "problem.yaml").read_text() + field + "\n")
    with pytest.raises(ProblemError) as e:
        load_problem("widget/v1@test")
    assert "malformed" in str(e.value)


def test_a_problem_cannot_reach_outside_its_own_directory(problem):
    """A problem is unapproved, so a path in it is untrusted input."""
    _rewrite(problem, **{"seed_candidate: seed_widget.c":
                         "seed_candidate: ../../../etc/passwd"})
    with pytest.raises(ProblemError) as e:
        load_problem("widget/v1@test")
    assert "plain filename" in str(e.value)


def test_a_scored_input_cannot_escape_the_work_dir(problem):
    """``materialize`` writes score_inputs[0] into a work dir it was handed."""
    _rewrite(problem, **{"score_inputs: [candidate.c]":
                         "score_inputs: ['../candidate.c']"})
    with pytest.raises(ProblemError) as e:
        load_problem("widget/v1@test")
    assert "plain filename" in str(e.value)


def test_an_entry_point_must_be_a_symbol(problem):
    """It is passed to an object-level symbol audit, not quoted into a shell."""
    _rewrite(problem, **{"entry_point: widget": "entry_point: 'wid get; rm -rf'"})
    with pytest.raises(ProblemError):
        load_problem("widget/v1@test")


# --------------------------------------------------------------------------
# pinning, which is what a problem gets INSTEAD of approval
# --------------------------------------------------------------------------

def test_the_digest_covers_the_scaffolding_not_just_the_declaration(problem):
    """Otherwise what the agent starts from could change with nothing recorded."""
    before = load_problem("widget/v1@test").digest
    (problem / "seed_widget.c").write_text(_SEED + "/* a different start */\n")
    after = load_problem("widget/v1@test").digest
    assert before != after


def test_the_goal_statement_is_inside_the_pin(problem):
    """A prompt is an experimental condition, not documentation.

    Two runs of "the same" problem are comparable only if they were asked the
    same question. An unpinned goal lets that change while every artifact still
    claims one problem was measured.
    """
    before = load_problem("widget/v1@test").digest
    _rewrite(problem, **{"Make widget faster": "Make widget faster, using SVE"})
    assert load_problem("widget/v1@test").digest != before


def test_a_named_file_that_is_absent_refuses_rather_than_loading(problem):
    (problem / "reference_widget.c").unlink()
    with pytest.raises(ProblemError) as e:
        load_problem("widget/v1@test")
    assert "reference_widget.c" in str(e.value)


def test_an_unknown_revision_raises_and_says_what_exists(problem):
    with pytest.raises(ProblemError) as e:
        load_problem("no-such-problem/v1")
    assert "widget/v1@test" in str(e.value)
    assert registered_problems() == ("widget/v1@test",)


def test_per_file_digests_say_which_file_moved(problem):
    """A single bundle digest tells a reader THAT it changed, not what."""
    names = dict(load_problem("widget/v1@test").file_digests)
    assert set(names) == {"problem.yaml", "widget.h", "widget_main.c",
                          "reference_widget.c", "seed_widget.c"}


# --------------------------------------------------------------------------
# materialize: the seed_work_dir equivalent
# --------------------------------------------------------------------------

def test_materialize_seeds_the_start_and_writes_the_question(problem, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    record = materialize(load_problem("widget/v1@test"), work)
    assert (work / "widget.h").read_text() == _HEADER
    assert (work / "widget_main.c").read_text() == _DRIVER
    # The seed candidate arrives under the SCORED name, so the file the agent
    # edits and the file the evaluator compiles are the same file.
    assert (work / "candidate.c").read_text() == _SEED
    assert "Make widget faster" in (work / PROBLEM_STATEMENT_NAME).read_text()
    assert record["problem_revision"] == "widget/v1@test"
    assert [item["name"] for item in record["seeded"]] == [
        "widget.h", "widget_main.c", "candidate.c", PROBLEM_STATEMENT_NAME]


def test_the_reference_is_never_seeded(problem, tmp_path):
    """The reference is the denominator; seeding it makes the task a copy."""
    work = tmp_path / "work"
    work.mkdir()
    record = materialize(load_problem("widget/v1@test"), work)
    assert not (work / "reference_widget.c").exists()
    # Named in the record rather than left as an absence a reader must notice.
    assert record["withheld"] == ["reference_widget.c"]


def test_the_seed_record_is_checkable_against_the_work_dir(problem, tmp_path):
    """"It started from the pinned scaffolding" is otherwise unfalsifiable."""
    from ari.protocols.integrity import bytes_digest

    work = tmp_path / "work"
    work.mkdir()
    record = materialize(load_problem("widget/v1@test"), work)
    for item in record["seeded"]:
        assert bytes_digest((work / item["name"]).read_bytes()) == item["sha256"]


def test_ari_ships_no_problems_of_its_own(monkeypatch, tmp_path):
    """Same property the harness registry has: the repo is not a task list."""
    monkeypatch.setenv("ARI_HARNESS_PROBLEMS", str(tmp_path / "absent"))
    assert registered_problems() == ()
    assert problems_root() == tmp_path / "absent"
