"""Tests for the task-harness registry MECHANISM.

Deliberately synthetic: every harness here is built in ``tmp_path``. ARI ships no
harnesses, and the real ones live in an untracked workspace, so a repo test that
loaded them would fail on any checkout without that workspace. The registered
harnesses' own parity tests travel with them
(``workspace/harnesses/<task>/tests/``, plus the cross-task metadata parity in
``workspace/harnesses/tests/``).

The trap this file exists to pin: every harness's ``measure_node`` accepts
``(work_dir, *, seed=0)``, so a *uniform* ``measure_node(work_dir, seed=seed)`` is
a LEGAL call against all of them — it just silently measures something else (SpMM
would drop from n=20000 to the harness default n=512, ~39x smaller, where even a
perfect kernel scores ~1x and the BFTS gradient dies). Hence ``[measure_kwargs]``
is declared per harness and asserted here by capturing the actual call.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from ari import harness_registry as reg
from ari.harness_registry import HarnessIntegrityError

HARNESS_PY = (
    "def kernels_dir():\n"
    "    import os\n"
    "    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k')\n"
    "def seed_work_dir(work_dir):\n"
    "    return ['driver.c']\n"
    "def measure_node(work_dir, **kw):\n"
    "    return {'compile_ok': True, 'families': {'f': {'speedup': 2.0, 'valid': True}}}\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for k in ("ARI_TASK", "ARI_SEED", "ARI_SPMM_N", "ARI_SPMM_K", "ARI_T_TARGET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARI_WORKSPACE", str(tmp_path / "ws"))


def register(task="t", *, target=16.0, scale="linear", target_env=None, axis=None,
             kwargs_toml="", body=HARNESS_PY, pin=True, nested=True):
    """Build a harness under the fixture workspace and return its dir."""
    d = reg.workspace_harness_root() / task
    (d / "k").mkdir(parents=True)
    (d / "k" / "driver.c").write_text("int main(void){return 0;}\n")
    (d / f"{task}_harness.py").write_text(body)
    files = [f"k/driver.c", f"{task}_harness.py"] if pin else []
    man = [f'[harness]\nentry = "{task}_harness.py"\ntarget = {target}\nscale = "{scale}"']
    if axis:
        man.append(f'axis = "{axis}"')
    if target_env:
        man.append(f'target_env = "{target_env}"')
    if kwargs_toml:
        man.append("\n[measure_kwargs]\n" + kwargs_toml)
    man.append("\n[files]")
    man += [f'"{f}" = "{reg.sha256_file(d / f)}"' for f in files]
    (d / reg.MANIFEST_NAME).write_text("\n".join(man) + "\n")
    return d


def call_kwargs(task="t", **env):
    """What Harness.measure() actually passes to measure_node."""
    for k, v in env.items():
        os.environ[k] = v
    try:
        seen: dict = {}
        h = reg.load(task)
        h._measure_node = lambda work_dir, **kw: seen.update(kw) or {}
        h.measure("/nowhere")
        return seen
    finally:
        for k in env:
            os.environ.pop(k, None)


# --------------------------------------------------------------------------
# measure_kwargs — the declared, non-uniform call
# --------------------------------------------------------------------------

def test_absent_measure_kwargs_means_no_kwargs():
    """GEMM's shape: it accepts seed= but was never passed one, and starting to
    would silently break comparability with banked replicates."""
    register()
    assert call_kwargs() == {}


def test_env_backed_kwarg_resolves_from_the_environment():
    register(kwargs_toml='seed = {env = "ARI_SEED", default = 0}')
    assert call_kwargs() == {"seed": 0}
    assert call_kwargs(ARI_SEED="7") == {"seed": 7}


def test_env_value_is_coerced_to_the_default_type():
    register(kwargs_toml='n = {env = "ARI_SPMM_N", default = 20000}')
    got = call_kwargs(ARI_SPMM_N="512")
    assert got == {"n": 512} and isinstance(got["n"], int)


def test_uncoercible_env_falls_back_to_the_default_instead_of_raising():
    """A bad env var must not abort a run mid-measurement."""
    register(kwargs_toml='seed = {env = "ARI_SEED", default = 0}')
    assert call_kwargs(ARI_SEED="not-a-number") == {"seed": 0}


def test_literal_kwarg_pins_a_value_with_no_env_override():
    register(kwargs_toml="n = 4096")
    assert call_kwargs(ARI_SPMM_N="1") == {"n": 4096}


def test_multiple_kwargs_are_all_passed():
    register(kwargs_toml='n = {env = "ARI_SPMM_N", default = 20000}\n'
                         'k = {env = "ARI_SPMM_K", default = 64}')
    assert call_kwargs() == {"n": 20000, "k": 64}


# --------------------------------------------------------------------------
# target / scale
# --------------------------------------------------------------------------

def test_describe_reads_target_and_scale_from_the_manifest():
    register(target=256.0, scale="log")
    assert reg.describe("t") == (256.0, "log")


def test_target_env_is_declared_by_the_harness(monkeypatch):
    register(target=256.0, scale="log", target_env="ARI_T_TARGET")
    monkeypatch.setenv("ARI_T_TARGET", "99.5")
    assert reg.describe("t")[0] == 99.5
    assert reg.load("t").target == 99.5


def test_target_env_is_ignored_when_the_harness_declares_none(monkeypatch):
    register(target=256.0)
    monkeypatch.setenv("ARI_T_TARGET", "99.5")
    assert reg.describe("t")[0] == 256.0


def test_bad_target_env_value_falls_back_to_the_default(monkeypatch):
    register(target=256.0, target_env="ARI_T_TARGET")
    monkeypatch.setenv("ARI_T_TARGET", "garbage")
    assert reg.describe("t")[0] == 256.0


def test_bad_scale_is_refused():
    register(scale="quadratic")
    with pytest.raises(HarnessIntegrityError):
        reg.describe("t")


# --------------------------------------------------------------------------
# axis — the analysis domain, NOT the same thing as scale
# --------------------------------------------------------------------------

@pytest.mark.parametrize("declared", ("speedup", "score"))
def test_axis_is_read_from_the_manifest(declared):
    register(axis=declared)
    assert reg.axis("t") == declared


def test_axis_defaults_to_speedup():
    register()
    assert reg.axis("t") == "speedup"


def test_axis_is_independent_of_scale():
    """A linear SCALE does not make a task score-shaped: SpMM is linear+speedup,
    erfc is linear+score. Conflating them runs the equivalence test in the wrong
    domain (log of a [0,1] score against a ratio margin)."""
    register("a", scale="linear", axis="speedup")
    register("b", scale="linear", axis="score")
    assert (reg.describe("a")[1], reg.axis("a")) == ("linear", "speedup")
    assert (reg.describe("b")[1], reg.axis("b")) == ("linear", "score")


def test_bad_axis_is_refused():
    register(axis="vibes")
    with pytest.raises(HarnessIntegrityError) as e:
        reg.axis("t")
    assert "bad axis" in str(e.value)


def test_axis_of_an_unregistered_task_raises():
    with pytest.raises(HarnessIntegrityError):
        reg.axis("nope")


def test_describe_does_not_import_the_harness(monkeypatch):
    """The evaluator constructs per node and only needs two numbers; importing a
    harness (numpy/scipy) to read them would regress that."""
    register(body="raise AssertionError('describe() must not import the harness')\n")
    reg.describe("t")


# --------------------------------------------------------------------------
# kernels_dir — provenance must name the dir actually compiled from
# --------------------------------------------------------------------------

def test_harness_defined_kernels_dir_wins():
    d = register()
    assert reg.load("t").kernels_dir() == str(d / "k")


def test_flat_layout_falls_back_to_the_harness_dir():
    d = register(body="def seed_work_dir(w):\n    return []\n"
                      "def measure_node(w, **k):\n    return {}\n")
    assert reg.load("t").kernels_dir() == str(d)


# --------------------------------------------------------------------------
# Content-addressing: the falsifiability claim
# --------------------------------------------------------------------------

def test_tampered_file_refuses_to_score():
    """The property is not "the agent cannot touch it" (same uid) — it is that
    tampering cannot pass SILENTLY."""
    d = register()
    reg.load("t")
    (d / "k" / "driver.c").write_text("int main(void){return 1;}\n")
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("t")
    assert "does not match the manifest" in str(e.value)


def test_tampered_harness_python_is_also_caught():
    """Pinning only the C fixtures would leave the measurement code editable."""
    d = register()
    (d / "t_harness.py").write_text(HARNESS_PY + "# touched\n")
    with pytest.raises(HarnessIntegrityError):
        reg.load("t")


def test_missing_pinned_file_refuses_to_score():
    d = register()
    (d / "k" / "driver.c").unlink()
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("t")
    assert "missing" in str(e.value)


def test_manifest_pinning_no_files_is_refused():
    register(pin=False)
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("t")
    assert "not falsifiable" in str(e.value)


def test_digests_are_recorded_and_are_a_copy():
    register()
    h = reg.load("t")
    assert set(h.digests()) == {"k/driver.c", "t_harness.py"}
    assert all(len(v) == 64 for v in h.digests().values())
    h.digests()["k/driver.c"] = "tampered"
    assert "tampered" not in h.digests().values()


def test_harness_missing_required_functions_is_refused():
    register(body="def seed_work_dir(w):\n    return []\n")   # no measure_node
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("t")
    assert "measure_node" in str(e.value)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def test_unknown_task_raises_rather_than_scoring_something_else():
    """The pre-registry dispatcher fell through to SpMM: a typo in ARI_TASK scored
    a DIFFERENT benchmark and reported it under the requested name."""
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("nope")
    assert "unknown task" in str(e.value)


def test_unknown_task_error_says_where_harnesses_come_from():
    register("real")
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("nope")
    msg = str(e.value)
    assert "harnesses" in msg and "real" in msg


def test_error_is_explicit_when_nothing_is_registered():
    with pytest.raises(HarnessIntegrityError) as e:
        reg.load("nope")
    assert "ARI_WORKSPACE" in str(e.value)


def test_available_tasks_lists_only_registered_harnesses():
    assert reg.available_tasks() == []
    register("a")
    register("b")
    assert reg.available_tasks() == ["a", "b"]


def test_a_directory_without_a_manifest_is_not_a_task():
    (reg.workspace_harness_root() / "notes").mkdir(parents=True)
    assert reg.available_tasks() == []


def test_workspace_harness_root_follows_ari_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_WORKSPACE", str(tmp_path / "elsewhere"))
    assert reg.workspace_harness_root() == tmp_path / "elsewhere" / "harnesses"


def test_harness_resolution_does_not_depend_on_the_cwd(monkeypatch, tmp_path):
    """Relocating the harnesses out of the package traded an ``import``-resolved
    instrument for a path-resolved one. Resolving that path from ``os.getcwd()``
    would mean a job script whose cwd is not the repo root (a normal scheduler
    default) finds no harness — and neither call site crashes on that: seeding
    logs a warning and ``evaluate_sync`` has a blanket except, so the run scores
    EVERY node 0.0 and reads as total agent failure, not a misconfiguration.

    ``ari.paths.RuntimePathResolver.resolve_workspace_root`` already owns this
    question and is anchored on ``__file__``; the registry must defer to it.
    """
    from ari.paths import RuntimePathResolver

    monkeypatch.delenv("ARI_WORKSPACE", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ARI_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert reg.workspace_harness_root() != tmp_path / "workspace" / "harnesses"
    assert reg.workspace_harness_root() == (
        RuntimePathResolver.resolve_workspace_root() / "harnesses")


def test_ari_root_relocates_the_harness_root(monkeypatch, tmp_path):
    """Deferring to the resolver means the registry honours ARI_ROOT too, which
    start.sh already computes cwd-independently."""
    monkeypatch.delenv("ARI_WORKSPACE", raising=False)
    monkeypatch.delenv("ARI_CHECKPOINT_DIR", raising=False)
    monkeypatch.setenv("ARI_ROOT", str(tmp_path))
    assert reg.workspace_harness_root() == tmp_path / "workspace" / "harnesses"


def test_load_defaults_to_ari_task(monkeypatch):
    register("mine")
    monkeypatch.setenv("ARI_TASK", "mine")
    assert reg.load().task == "mine"


def test_no_hardcoded_task_set_in_core():
    """ARI core must name no task. When it did, the evaluator resolved a harness
    while bfts_loop's hardcoded gate seeded NOTHING — the node scored 0 for lack
    of scaffolding and read as "the agent could not optimize".
    """
    core = Path(__file__).resolve().parents[1] / "ari"
    known = {"gemm", "spmm", "stencil", "erfc", "meshpart"}
    offenders = []
    for py in core.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
                continue
            elts = node.keys if isinstance(node, ast.Dict) else node.elts
            names = {e.value for e in elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if len(names & known) >= 3:
                offenders.append(f"{py.relative_to(core)}:{node.lineno}")
    assert not offenders, "ARI core names tasks; ask available_tasks():\n" + "\n".join(offenders)
