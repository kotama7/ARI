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
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ari.assurance.native_perf import reference_flags, verify_native_perf
from ari.assurance.native_perf_common import (
    PerfBuildError, PerfInfrastructureError, compile_binary)
from ari.assurance.problems import load_problem

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


def _score(problem, source_text: str):
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw, "candidate.c")
        path.write_text(source_text)
        return verify_native_perf(
            problem, path, tier="screen", dataset_revision=SMOKE,
            candidate_flags=" ".join(reference_flags(problem)),
            regression_threshold=0.95)


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
    report = _score(problem, FORGES_ITS_TIMING)
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
