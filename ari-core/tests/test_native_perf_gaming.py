"""Three ways a candidate could beat this harness, each demonstrated then closed.

WHY THESE ARE A SEPARATE FILE. They are not hypotheticals. Every one was built,
compiled and scored against the real gemm problem before it was fixed:

  - a CORRECT naive kernel that overwrote its own timing file was credited
    1e-9 s and ranked at 336,887x with the oracle satisfied;
  - a candidate whose entire contents were ``#include "reference_gemm.c"``
    compiled and scored 13.7x, verdict pass;
  - a file-scope global built with ``-fcommon`` passed the "entry point and
    nothing else" audit that the same source without the flag failed.

The first is the one that matters most: in a BFTS run it is not an exploit, it
is a local optimum the search finds and then climbs, and every number after it
is fiction. Nothing in the object audit can see it, because the code runs
INSIDE the entry point, which is where the audit stops looking.

Each test costs a compile and a run on the smoke case set. That is the price of
knowing these stay shut.

TWO RATIOS, ONE FUNCTION APART, AND ONLY ONE OF THEM IS REACHABLE FROM A LAUNCH.
Read this before adding work to the launch path, because both of us got it
wrong in the same week and in opposite directions.

  overhead ratio   over_cand / over_ref     built from WALL      (this file's guard)
  relative spread  relative_spread(ratios)  built from CREDITED  (the verdict rule)

``run_timed`` returns the driver's OWN timer as the credited figure and records
wall separately, so ``overhead = wall - credited``. Anything that makes a launch
take longer without crediting the time therefore lands in the overhead ratio and
NOT in the spread.

WHAT THAT COST, in both directions:

* A network observation was added inside the timed region. On a routed host its
  probe ran to a 250 ms timeout -- against 0.023 ms for the filesystem record
  beside it -- so every launch carried a constant in wall, hence in overhead.
  The guard below is a RATIO, and the same constant on both terms pulls it to
  one. MEASURED: the self-timing forger went from refused to VERDICT PASS. Not
  caught by a weaker rule -- not caught. Reinstating a bare 250 ms sleep in that
  region reproduces it; removing it restores the refusal.

* The same constant was then suspected of flattening the SPREAD, because a
  clean-control spread came back larger once it was removed. It cannot: the
  spread is built from credited ratios and the constant never entered credited.
  MEASURED anyway, same node, same budget, n=5 each, sleeping 250 ms inside the
  wall window: median spread 0.001550 without and 0.002326 with, ranges
  overlapping almost entirely. No effect, in either direction.

So: a launch-time constant is invisible to the verdict rule and disabling to the
forgery guard. The mechanism is real and applies to exactly one of the two. Ask
which quantity it acts on before measuring, or the measurement answers a
question nobody asked.
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path

import pytest

from ari.assurance.native_perf import reference_flags, verify_native_perf
from ari.assurance.native_perf_common import (
    PerfBuildError, PerfInfrastructureError, compile_binary)
from ari.assurance.problems import load_problem
from ari.assurance.sandbox import SandboxUnavailable, sandbox_record

PROBLEM = "gemm-dense-fp64/v1@2026q3"
SMOKE = "native-perf-gemm-cases/v1@smoke"

_NAIVE_BODY = """
  for (int i = 0; i < n; i++)
    for (int j = 0; j < m; j++) {
      double s = 0.0;
      for (int l = 0; l < p; l++) s += A[i * p + l] * B[l * m + j];
      C[i * m + j] = s;
    }
"""

#: Correct output, real work, and a forked writer that replaces the credited
#: time after the frozen driver has written the true one.
FORGES_ITS_TIMING = f'''#include "gemm_kernel.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {{
{_NAIVE_BODY}
  FILE *cl = fopen("/proc/self/cmdline", "rb");
  if (!cl) return;
  char buf[8192];
  size_t got = fread(buf, 1, sizeof(buf) - 1, cl);
  fclose(cl);
  buf[got] = 0;
  char *args[8];
  int k = 0;
  for (size_t i = 0; i < got && k < 8;) {{ args[k++] = buf + i; i += strlen(buf + i) + 1; }}
  if (k < 4) return;
  if (fork() == 0) {{
    usleep(200000);                       /* outlive the parent's wait */
    FILE *t = fopen(args[3], "wb");
    if (t) {{ double e = 1e-9; fwrite(&e, sizeof e, 1, t); fclose(t); }}
    _exit(0);
  }}
}}
'''

COPIES_THE_DENOMINATOR = '#include "reference_gemm.c"\n'

HONEST = f'''#include "gemm_kernel.h"
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {{
{_NAIVE_BODY}
}}
'''

EXTRA_GLOBAL = f'''#include "gemm_kernel.h"
double sneaky_scratch[16];
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {{
  sneaky_scratch[0] = 1.0;
{_NAIVE_BODY}
}}
'''


@pytest.fixture(scope="module")
def problem():
    return load_problem(PROBLEM)


def _score(problem, source_text: str, *, sandboxed: bool = True):
    """Measure a candidate, optionally as a kernel WITHOUT Landlock would.

    The two layers are tested separately on purpose. With the sandbox a forgery
    cannot be attempted -- it cannot read /proc to find the file. Without it
    (an older kernel, or an unsupported architecture) the checks are the only
    thing standing, and they have to still work: a defence that is only ever
    exercised behind another one is a defence nobody has tested.
    """
    import ari.assurance.sandbox as sandbox_module

    # Simulate a kernel with no Landlock by changing what the PROBE reports.
    # Breaking restrict_to instead would now fail the launch closed, which is
    # the other behaviour and has its own test: the decision is taken from the
    # probe, once, so that the record and the launch cannot disagree.
    real = sandbox_module.sandbox_record
    if not sandboxed:
        sandbox_module.sandbox_record = lambda *_a, **_k: {
            "filesystem_isolation": False, "mechanism": None,
            "reason": "no Landlock (simulated)"}
    try:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw, "candidate.c")
            path.write_text(source_text)
            return verify_native_perf(
                problem, path, tier="screen", dataset_revision=SMOKE,
                candidate_flags=" ".join(reference_flags(problem)),
                regression_threshold=0.95)
    finally:
        sandbox_module.sandbox_record = real


def _build(problem, source_text: str, flags=()) -> bool:
    """True when the candidate object survived the audit and linked.

    Checked INSIDE the temp dir: asking whether the executable exists after the
    directory is cleaned up answers False for a successful build too, which is
    how this helper first reported a passing case as a failure.
    """
    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw)
        path = out / "candidate.c"
        path.write_text(source_text)
        return compile_binary(
            include_dir=problem.directory,
            driver=problem.path(problem.definition.scaffolding.driver),
            entry_point=problem.definition.entry_point, role="candidate",
            source=path, out_dir=out, compiler="cc",
            extra_flags=tuple(flags)).is_file()


def test_a_kernel_cannot_credit_itself_a_time_it_did_not_take(problem):
    """The parent's clock is the one the candidate cannot reach.

    The credited figure is the driver's internal timer, because wall time
    includes process start and the problem read. But that timer goes to a file
    whose path is in the child's own argv, and a kernel can read
    /proc/self/cmdline from inside the timed call. The parent now bounds the
    credit by the wall clock it measured itself, and reaps the child's whole
    process group before reading -- the forger's writer used to outlive the
    wait.
    """
    report = _score(problem, FORGES_ITS_TIMING, sandboxed=False)
    case = report.case_results[0]
    assert case.verdict == "fail"
    assert "wall clock" in case.detail, case.detail
    # And it is refused, not floored: crediting the floor would let a forger
    # tune to it.
    assert case.speedup == 0.0


def test_an_honest_kernel_is_not_caught_by_the_same_guard(problem):
    """The bound has to refuse forgery without refusing a fast kernel."""
    report = _score(problem, HONEST)
    case = report.case_results[0]
    assert case.repetitions and case.repetitions[0].correct
    assert case.speedup > 0.0
    assert "wall clock" not in case.detail


def test_the_denominator_is_not_on_the_candidates_include_path(problem):
    """Withholding the reference from the WORK DIR does not withhold it from the
    compiler: the candidate's include root used to be the problem directory,
    which is where the frozen reference lives. One line made the task a copy.

    It comes back as a REPORT saying the candidate did not build, not as a
    raise: a build failure is a fact about the candidate, and the worker and the
    evaluator used to classify the same failure differently.
    """
    report = _score(problem, COPIES_THE_DENOMINATOR)
    assert report.build_error and "reference_gemm.c" in report.build_error
    assert report.verdict == "fail"
    assert report.case_results == ()


def test_the_contract_header_is_still_reachable(problem):
    """Narrowing the include root must not take the contract with it."""
    report = _score(problem, HONEST)
    assert report.case_results[0].repetitions


def test_a_global_hidden_by_fcommon_is_still_refused(problem):
    """An allowlist of nm symbol types is the same mistake as a denylist of
    flags, one level down: the filter omitted ``C``, and ``-fcommon`` turns a
    file-scope global into one."""
    for flags in ((), ("-fcommon",)):
        with pytest.raises(PerfBuildError, match="exports symbols other than"):
            _build(problem, EXTRA_GLOBAL, flags)
    assert _build(problem, HONEST, ("-fcommon",))


#: Times ITSELF and writes a plausible fraction, rather than an absurd 1e-9.
#: This is what the wall bound alone does not catch: measured at 89.3x, pass.
FORGES_ADAPTIVELY = f'''#include "gemm_kernel.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static double now(void) {{
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + 1e-9 * t.tv_nsec;
}}
void gemm(int n, int m, int p, const double *A, const double *B, double *C) {{
  double t0 = now();
{_NAIVE_BODY}
  double mine = now() - t0;
  FILE *cl = fopen("/proc/self/cmdline", "rb");
  if (!cl) return;
  char buf[8192];
  size_t got = fread(buf, 1, sizeof(buf) - 1, cl);
  fclose(cl);
  buf[got] = 0;
  char *args[8];
  int k = 0;
  for (size_t i = 0; i < got && k < 8;) {{ args[k++] = buf + i; i += strlen(buf + i) + 1; }}
  if (k < 4) return;
  if (fork() == 0) {{
    usleep(200000);
    FILE *t = fopen(args[3], "wb");
    if (t) {{ double e = mine * 0.02; fwrite(&e, sizeof e, 1, t); fclose(t); }}
    _exit(0);
  }}
}}
'''


def test_a_kernel_that_times_itself_cannot_write_a_fraction_of_it(problem):
    """The wall bound is not enough on its own, and this is why.

    Bounding the credit by the wall clock catches a forger that writes 1e-9. It
    does not catch one that measures its OWN elapsed time and writes 2% of it --
    measured at 89.3x, verdict pass, after the wall bound was in place.

    What separates them: forging shrinks the CREDIT without shrinking the WALL,
    so the process's non-kernel overhead inflates by exactly what was hidden.
    The reference runs the same frozen driver on the same problem in the same
    loop, so its overhead is a live calibration for the candidate's -- no
    constant, no assumption about the host.
    """
    report = _score(problem, FORGES_ADAPTIVELY, sandboxed=False)
    case = report.case_results[0]
    assert case.verdict == "fail"
    assert "does not account for what ran" in case.detail, case.detail
    assert case.speedup == 0.0


# --- the layer that makes the forgery impossible rather than detectable --------

def test_the_sandbox_denies_the_path_the_forgeries_used(problem):
    """Both forgeries found the timing file by reading /proc/self/cmdline.

    Landlock's ruleset does not include /proc, and it is applied between fork
    and exec so it binds the child and everything the child starts. The forgery
    code therefore returns early and the kernel just computes: it scores like
    what it is, an honest naive loop, with no forged credit and no check having
    to fire.
    """
    if not sandbox_record()["filesystem_isolation"]:
        pytest.skip("this kernel has no Landlock; the checks are the only layer")
    report = _score(problem, FORGES_ITS_TIMING)
    case = report.case_results[0]
    assert case.repetitions and case.repetitions[0].correct
    # Not refused -- it never managed to forge anything.
    assert "wall clock" not in case.detail
    assert "does not account" not in case.detail


def test_what_the_sandbox_does_not_claim():
    """A record that overstates is worse than none: this is filesystem access
    control, and fork, CPU and memory are not restricted by it."""
    record = sandbox_record("/tmp")
    if not record["filesystem_isolation"]:
        pytest.skip("no Landlock on this kernel")
    assert record["mechanism"] == "landlock"
    assert set(record["does_not_restrict"]) >= {"fork", "cpu", "memory"}


def test_the_report_says_whether_the_run_was_sandboxed(problem):
    """A record nobody writes is worse than none, and this one was not written.

    The first version of the sandbox swallowed a failure inside preexec_fn under
    a comment saying a record elsewhere would show it. There was no such record:
    ``sandbox_record`` had no caller, so a child that failed to restrict itself
    ran unprotected with nothing anywhere saying so -- the exact defect this
    harness spends its length guarding against, written into the guard.
    """
    report = _score(problem, HONEST)
    assert report.sandbox, "the report does not say whether it was sandboxed"
    assert report.sandbox["filesystem_isolation"] is (
        sandbox_record()["filesystem_isolation"])
    if report.sandbox["filesystem_isolation"]:
        assert report.sandbox["mechanism"] == "landlock"
        assert set(report.sandbox["does_not_restrict"]) >= {"fork", "cpu", "memory"}


def test_a_sandbox_that_cannot_be_applied_kills_the_launch(problem, monkeypatch):
    """Fail closed. If this kernel CAN enforce isolation, a child that failed to
    restrict itself must not be measured -- the alternative is a measurement
    that looks protected and is not."""
    import ari.assurance.sandbox as sandbox_module

    if not sandbox_record()["filesystem_isolation"]:
        pytest.skip("no Landlock here; there is nothing to fail closed on")

    def _broken(*_a, **_k):
        raise RuntimeError("ruleset could not be applied")

    monkeypatch.setattr(sandbox_module, "restrict_to", _broken)
    with pytest.raises(Exception) as caught:
        _score(problem, HONEST)
    # It must not come back as a quiet success or a candidate fault.
    # Typed as a substrate failure, never as the candidate's: CPython replaces
    # the preexec_fn exception with an opaque message, so an untyped one would
    # be scored as a bad kernel.
    assert isinstance(caught.value, PerfInfrastructureError), caught.value
    assert "isolation" in str(caught.value)


# --- the oracle is not in the room ------------------------------------------
#
# "A candidate cannot read the hidden oracle" is usually argued at the sandbox
# layer: the problem directory is outside the Landlock ruleset, so the candidate
# cannot open what is in it. That argument is weaker than it looks, and the
# weakness is worth naming because it is the one an auditor should press on: a
# restriction record says the door was locked, which is not the same as saying
# nobody tried the handle, and Landlock at this node's ABI gives the sandboxing
# process no denial channel to learn the difference from. Observing ATTEMPTS
# would need seccomp user-notify or the audit subsystem.
#
# For the ORACLE the sandbox argument is not needed at all, because the oracle
# is never written down. `_residual_ok` computes `reference = a @ b` in the
# PARENT's numpy at scoring time; `_write_problem` writes the shapes and the two
# INPUT matrices and nothing else; and the child's argv carries the problem file,
# an output path and a timing path. There is no room to break into.
#
# What Landlock IS load-bearing for is a different object -- `restrict_to`'s own
# docstring names it -- the frozen reference BINARY, which is the candidate's
# denominator and IS on disk. That half is a sandbox-layer question and the
# fail-closed verdict gate on the launch record is what answers it.

def test_the_oracle_is_never_written_where_a_candidate_could_reach_it():
    """Structural, and therefore stronger than an access check.

    Asserted over what `_write_problem` EMITS rather than over a list of field
    names kept here: the file is read back and its byte length must be exactly
    the three shapes plus the two input matrices. A third array of any size
    makes the length wrong, so this fails if anything at all is added -- which
    an enumeration of expected keys would not.
    """
    import numpy as np
    from ari.assurance import native_perf_gemm

    rng = np.random.default_rng(7)
    a = rng.standard_normal((6, 5))
    b = rng.standard_normal((5, 4))
    with tempfile.TemporaryDirectory() as scratch:
        problem = Path(scratch) / "problem.bin"
        native_perf_gemm._write_problem(problem, a, b)
        written = problem.stat().st_size

    header = np.dtype(np.int32).itemsize * 3
    inputs = a.nbytes + b.nbytes
    assert written == header + inputs, (
        f"the problem file is {written} bytes against {header + inputs} for the "
        f"shapes and the two inputs; something else was written into the file "
        f"the candidate is handed")

    # And the answer really is a parent-side expression: the reference appears
    # in the scorer and in nothing that produces the child's inputs.
    emit = inspect.getsource(native_perf_gemm._write_problem)
    assert "reference" not in emit and "@" not in emit, (
        "the problem writer references the oracle expression")


def test_the_child_is_handed_the_problem_an_output_and_a_clock_and_nothing_else():
    """The other half of the same claim, at the launch boundary.

    Derived from the argv the launcher actually builds, so a fourth path added
    to it fails here rather than passing an enumeration of the first three.
    """
    from ari.assurance import native_perf_common

    source = inspect.getsource(native_perf_common)
    argv_lines = [line.strip() for line in source.splitlines()
                  if line.strip().startswith("argv = [")]
    assert argv_lines, "the launcher's argv construction was not found"
    for line in argv_lines:
        assert "reference" not in line and "oracle" not in line, line
