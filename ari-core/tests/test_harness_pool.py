"""A task may be served by several harnesses, and ambiguity must never resolve itself.

WHY THIS MATTERS. A harness directory used to BE the task, so "the scientific
question" and "one way of measuring it" were the same string and a second way of
measuring could not exist. Every property that makes a measurement trustworthy is
a choice — denominator, problem size, timed window, toolchain, environment — and
each of those choices was made once, invisibly, and turned out to be wrong at
least once. A pool makes the alternatives exist so they can be compared before
the mistake instead of after it.

THE PROPERTY THIS FILE DEFENDS. When more than one harness serves a task, loading
by task name must REFUSE. Picking whichever sorted first would make the number a
property of a directory name while it is reported as a property of the task —
exactly the conflation the pool exists to end. A convenient default here would
undo the whole change, silently, and every test would still pass.
"""
import pathlib
import re
import shutil
import sys
import tomllib

import pytest

from ari.harness_registry import (HarnessIntegrityError, available_tasks,
                                  harnesses_for, load, manifest_integrity_hash,
                                  registered_harnesses, sha256_file)

#: SYNTHETIC ON PURPOSE, like ``test_harness_registry``. This file tests the
#: POOL MECHANISM -- ambiguity refusal, independent pinning, provenance -- none
#: of which is a property of any particular harness. Copying a real harness
#: directory to get a fixture tied these tests to one untracked tree, so they
#: failed on a checkout without it and would have to be rewritten whenever that
#: tree moved. What the mechanism needs is two directories serving one task;
#: that is all this builds.
_BODY = (
    "def kernels_dir():\n"
    "    import os\n"
    "    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k')\n"
    "def seed_work_dir(work_dir):\n"
    "    return ['driver.c']\n"
    "def measure_node(work_dir, **kw):\n"
    "    return {'compile_ok': True,"
    " 'families': {'f': {'speedup': 2.0, 'valid': True}}}\n"
)


def _repin(d: pathlib.Path) -> None:
    tp = d / "harness.toml"
    text = tp.read_text()
    tp.write_text(re.sub(r'^self_sha256 = "[0-9a-f]{64}"',
                         f'self_sha256 = "{manifest_integrity_hash(tomllib.loads(text))}"',
                         text, flags=re.M))


def _make(root: pathlib.Path, name: str, *, task: str | None = None,
          band: bool = True) -> pathlib.Path:
    """One harness directory, pinned like a real one.

    ``band=False`` builds a variant nobody characterised: the band fields are
    ABSENT rather than copied, because a band inherited from a different
    configuration is a number with no measurement behind it.
    """
    d = root / name
    (d / "k").mkdir(parents=True)
    (d / "k" / "driver.c").write_text("int main(void){return 0;}\n")
    entry = f"{name}_harness.py"
    (d / entry).write_text(_BODY)

    lines = ["[harness]"]
    if task:
        lines.append(f'task = "{task}"')
    lines += [f'entry = "{entry}"', "target = 16.0", 'scale = "linear"',
              "", "[declares]", 'question = "how fast is the kernel"',
              'denominator = "competent_frozen"',
              'blind_to = ["placement", "page size"]']
    if band:
        lines += ["resolves = 0.00149", 'resolves_measured_on = "2026-01-01"',
                  "resolves_reps = 5"]
    lines += ["", "[files]"]
    lines += [f'"{f}" = "{sha256_file(d / f)}"' for f in ("k/driver.c", entry)]
    text = "\n".join(lines) + "\n"
    (d / "harness.toml").write_text(text)
    _pin = manifest_integrity_hash(tomllib.loads(text))
    (d / "harness.toml").write_text(
        text + f'\n[integrity]\nself_sha256 = "{_pin}"\n')
    return d


@pytest.fixture
def pool(tmp_path, monkeypatch):
    """Two harness directories serving one task."""
    root = tmp_path / "harnesses"
    root.mkdir()
    _make(root, "gemm")
    _make(root, "gemm_variant", task="gemm", band=False)
    monkeypatch.setenv("ARI_WORKSPACE", str(tmp_path))
    for m in [k for k in sys.modules if k.endswith("_harness")]:
        sys.modules.pop(m, None)
    return root


def test_a_task_can_be_served_by_more_than_one_harness(pool):
    assert registered_harnesses() == ["gemm", "gemm_variant"]
    assert available_tasks() == ["gemm"], (
        "available_tasks() reports the distinct QUESTIONS, not the harness "
        "count; two ways of measuring gemm are still one gemm")
    assert harnesses_for("gemm") == ["gemm", "gemm_variant"]


def test_loading_by_task_alone_refuses_when_the_choice_is_ambiguous(pool):
    with pytest.raises(HarnessIntegrityError) as e:
        load("gemm")
    msg = str(e.value)
    assert "gemm_variant" in msg and "no choice was made" in msg, (
        "a convenient default here would silently make every score a property "
        "of whichever directory name sorted first, reported as a property of "
        "the task")


def test_naming_the_harness_binds_it(pool):
    h = load("gemm", harness="gemm_variant")
    assert h.task == "gemm"
    assert h.origin.endswith("gemm_variant")


def test_a_harness_cannot_be_bound_to_a_task_it_does_not_serve(pool):
    with pytest.raises(HarnessIntegrityError) as e:
        load("stencil", harness="gemm_variant")
    assert "serves task" in str(e.value)


def test_an_unknown_harness_name_raises(pool):
    with pytest.raises(HarnessIntegrityError):
        load("gemm", harness="no_such_harness")


def test_a_variant_declares_its_own_band_or_none_at_all(pool):
    """A band copied from another configuration is not a measurement."""
    assert load("gemm", harness="gemm").declares.band_is_measured
    assert not load("gemm", harness="gemm_variant").declares.band_is_measured


def test_the_variant_is_pinned_independently(pool):
    """Two harnesses, two content-addressed manifests; neither covers the other."""
    a = load("gemm", harness="gemm").manifest_hash
    b = load("gemm", harness="gemm_variant").manifest_hash
    assert a and b and a != b


def test_editing_a_variant_without_repinning_refuses_to_score(pool):
    tp = pool / "gemm_variant/harness.toml"
    tp.write_text(re.sub(r"^target = .*$", "target = 999.0",
                         tp.read_text(), flags=re.M))
    with pytest.raises(HarnessIntegrityError) as e:
        load("gemm", harness="gemm_variant")
    assert "self-hash mismatch" in str(e.value)


def test_an_unreadable_manifest_does_not_quietly_leave_the_pool(pool):
    """Swallowing the parse error would dissolve an ambiguity that must be refused.

    A harness whose manifest cannot be read used to be reported as serving its
    own directory name. Two harnesses declaring one task would then look like
    two tasks, ``load(task)`` would see no ambiguity to refuse, and the survivor
    would be bound without anyone having chosen it -- a broken file silently
    deciding which harness measures the study.
    """
    (pool / "gemm_variant/harness.toml").write_text("this is not toml [[[\n")
    with pytest.raises(HarnessIntegrityError) as e:
        harnesses_for("gemm")
    assert "could not be read" in str(e.value)


def test_a_single_harness_task_still_loads_by_name_alone(pool):
    """The pool must not make the ordinary one-harness case harder."""
    shutil.rmtree(pool / "gemm_variant")
    assert load("gemm").origin.endswith("gemm")


def test_a_manifest_without_an_explicit_task_serves_its_directory_name(pool):
    """Every harness registered before the pool existed keeps working."""
    tp = pool / "gemm_variant/harness.toml"
    tp.write_text(tp.read_text().replace('task = "gemm"\n', ""))
    _repin(pool / "gemm_variant")
    assert harnesses_for("gemm") == ["gemm"]
    assert harnesses_for("gemm_variant") == ["gemm_variant"]
    assert load("gemm").origin.endswith("gemm")


def test_the_choice_and_its_alternatives_are_in_provenance(pool):
    """"We used the best harness" is unfalsifiable unless both are recorded.

    With a pool the score is a property of the harness as much as of the code.
    A record naming only the winner lets a reader check that a harness was used;
    it does not let them check that the choice was reasonable, which is the part
    a pool newly makes questionable.
    """
    pv = load("gemm", harness="gemm_variant").provenance()
    assert pv["harness"] == "gemm_variant"
    assert pv["alternatives"] == ["gemm"], (
        "the alternatives are what make the choice reviewable")
    assert pv["declares"]["resolves"] is None
    assert "blind_to" in pv["declares"]

    other = load("gemm", harness="gemm").provenance()
    assert other["alternatives"] == ["gemm_variant"]
    assert other["manifest_sha256"] != pv["manifest_sha256"]


def test_ari_harness_reaches_a_caller_that_passes_no_argument(pool, monkeypatch):
    """Callers select the harness the same way they already select the task."""
    monkeypatch.setenv("ARI_HARNESS", "gemm_variant")
    assert load("gemm").origin.endswith("gemm_variant")
    monkeypatch.setenv("ARI_HARNESS", "gemm")
    assert load("gemm").origin.endswith("gemm")


def test_an_empty_ari_harness_does_not_count_as_a_choice(pool, monkeypatch):
    """An unset-looking variable must not satisfy the ambiguity check."""
    monkeypatch.setenv("ARI_HARNESS", "")
    with pytest.raises(HarnessIntegrityError) as e:
        load("gemm")
    assert "no choice was made" in str(e.value)
