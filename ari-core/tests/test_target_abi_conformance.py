"""A conformance declaration must be checked, not asserted.

Regression: the scoring path declared `interface_contract: gemm-c-abi/v1` for a
library built from a problem whose scaffolding exports `gemm`. The verifier
resolves `ari_gemm_f32` / `ari_gemm_f64`, so 33 of 33 cases failed with
"missing symbol" and every reported error was exactly 0.0 -- the kernel was
never entered. The declaration was a claim with nothing behind it.
"""
import ctypes.util
import subprocess
import sys

import pytest

from ari.assurance.target_abi import abi_identity
from ari.evaluator.assurance_measure import TargetABIMismatch, _missing_abi_symbols


def _build(tmp_path, source: str):
    src = tmp_path / "t.c"
    src.write_text(source, encoding="utf-8")
    lib = tmp_path / "t.so"
    proc = subprocess.run(["cc", "-shared", "-fPIC", str(src), "-o", str(lib)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"no working C compiler: {proc.stderr[:200]}")
    return lib


def test_the_registry_names_the_symbols_the_verifier_resolves():
    # Kept in step with drivers/shared_library.py, which does getattr(lib, f"ari_{kind}_{suffix}").
    for family in ("gemm", "spmm", "stencil"):
        assert abi_identity(family).exported_symbols == (
            f"ari_{family}_f32", f"ari_{family}_f64")


def test_a_library_exporting_only_the_problem_entry_point_is_refused(tmp_path):
    lib = _build(tmp_path, "void gemm(int n,int m,int p,const double*a,"
                           "const double*b,double*c){(void)n;(void)m;(void)p;}\n")
    missing = _missing_abi_symbols(lib, abi_identity("gemm").exported_symbols)
    assert missing == ["ari_gemm_f32", "ari_gemm_f64"]


def test_a_library_exporting_the_contract_passes(tmp_path):
    lib = _build(tmp_path, "int ari_gemm_f32(void){return 0;}\n"
                           "int ari_gemm_f64(void){return 0;}\n")
    assert _missing_abi_symbols(lib, abi_identity("gemm").exported_symbols) == []


def test_no_declared_symbols_means_nothing_to_check(tmp_path):
    lib = _build(tmp_path, "int anything(void){return 0;}\n")
    assert _missing_abi_symbols(lib, ()) == []


def test_an_unloadable_library_is_a_mismatch_not_a_crash(tmp_path):
    bad = tmp_path / "not-a-library.so"
    bad.write_bytes(b"not an ELF object")
    with pytest.raises(TargetABIMismatch, match="will not load"):
        _missing_abi_symbols(bad, ("ari_gemm_f64",))


# --------------------------------------------------------------------------
# The audit must not give the candidate a constructor slot in the SCORER.
#
# `dlopen` runs the object's ELF constructors. While the audit called it
# in-process, a candidate could run code inside the process that goes on to
# score every later node. Measured: `5e-324 * 1.0` returned `5e-324` before the
# audit and `0.0` after it, because `-Ofast` links `crtfastmath.o` whose
# constructor sets MXCSR FTZ/DAZ process-wide with no matching unset. Oracles
# whose guarantee depends on denormals -- the spmm bound of exactly 0.0 for an
# empty row -- then answer differently for every subsequent candidate, and
# nothing in the evidence records that it happened.
#
# These fail against the in-process audit. The first two fail loudly; the last
# one takes the whole session down, which is precisely the point being made.
# --------------------------------------------------------------------------

#: The smallest positive double. Only representable while denormals are kept.
_TINY = float.fromhex("0x0.0000000000001p-1022")


def _multiply(a: float, b: float) -> float:
    """Kept out of line so the product is computed, not constant-folded."""
    return a * b


def _denormals_survive() -> bool:
    return _multiply(_TINY, 1.0) != 0.0


#: Opens a library in-process and reports whether that flushed denormals. Run
#: in a subprocess: asking the question in the test process would answer it by
#: poisoning the test process.
#: Each observation is reduced to a BOOL before the next step. DAZ makes the
#: hardware read an already-stored denormal as zero, so `before != 0.0`
#: evaluated after the dlopen answers about the new mode, not the old one --
#: which is how this check first reported "intact" for a library that flushes.
_INPROCESS_FLUSH_CHECK = """
import ctypes, sys
tiny = float.fromhex("0x0.0000000000001p-1022")
mul = lambda a, b: a * b
before = mul(tiny, 1.0) != 0.0
ctypes.CDLL(sys.argv[1])
after = mul(tiny, 1.0) != 0.0
sys.stdout.write("flushed" if before and not after else "intact")
"""

#: Two routes to the same effect. The flags are not the mechanism: the second
#: reaches it from a plain -O2 build, so a screen over flag spellings closes the
#: spelling and leaves the escape.
_FTZ_CANDIDATES = {
    "declared -Ofast, no constructor of its own": (
        ["-Ofast"],
        "double gemm(void){return 1.0;}\n",
    ),
    "plain -O2, its own constructor": (
        ["-O2"],
        "#include <xmmintrin.h>\n"
        "#include <pmmintrin.h>\n"
        "static void __attribute__((constructor)) arm(void){\n"
        "  _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON);\n"
        "  _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_ON);\n"
        "}\n"
        "double gemm(void){return 1.0;}\n",
    ),
}


def _build_candidate(tmp_path, flags, source):
    """Build with candidate-chosen flags, skipping if THIS toolchain cannot."""
    src = tmp_path / "c.c"
    src.write_text(source, encoding="utf-8")
    lib = tmp_path / "c.so"
    proc = subprocess.run(["cc", "-shared", "-fPIC", *flags, str(src), "-o", str(lib)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"toolchain will not build this candidate: {proc.stderr[:200]}")
    return lib


@pytest.mark.parametrize("route", sorted(_FTZ_CANDIDATES))
def test_the_audit_cannot_change_the_scorers_rounding(tmp_path, route):
    lib = _build_candidate(tmp_path, *_FTZ_CANDIDATES[route])
    # Only meaningful where this toolchain and architecture actually produce the
    # escape; establish that first, in a process we are willing to lose.
    check = subprocess.run([sys.executable, "-c", _INPROCESS_FLUSH_CHECK, str(lib)],
                           capture_output=True, text=True)
    if check.stdout.strip() != "flushed":
        pytest.skip(f"opening this object in-process does not flush denormals here "
                    f"({check.stdout.strip() or check.stderr[:120]!r})")

    assert _denormals_survive(), "the test process already had denormals flushed"
    assert _missing_abi_symbols(lib, ("gemm",)) == []
    assert _denormals_survive(), (
        f"auditing a candidate ({route}) flushed denormals in the SCORER: "
        f"every later evaluation in this process now rounds differently")


def test_a_constructor_that_kills_its_process_does_not_kill_the_scorer(tmp_path):
    # The reason the fix is a process boundary and not an FP save/restore: an FP
    # restore would hand back the MXCSR bits and still let this one through.
    lib = _build_candidate(tmp_path, ["-O2"],
                           "#include <unistd.h>\n"
                           "static void __attribute__((constructor)) boom(void)"
                           "{_exit(9);}\n"
                           "double gemm(void){return 1.0;}\n")
    with pytest.raises(TargetABIMismatch, match="will not load"):
        _missing_abi_symbols(lib, ("gemm",))


# --- the declare-time build goes through the instrument's two screens --------
#
# `declare_target` builds the scored candidate a SECOND time, as a shared
# library, and it used to run the candidate's declared compiler by name and
# `shlex.split` its declared flags straight into that argv. Neither screen the
# timed build applies was reachable from there, so `-B<dir>` -- which this
# repository's own comment beside FLAG_ALLOW_PATTERN calls "the one thing a
# compiler allowlist exists to prevent" -- landed in a compile the scorer runs.
#
# The security reading is the loud one. The quiet one matters as much: an
# unscreened build here builds a DIFFERENT program from the one that was timed,
# so the declaration would describe a binary nobody scored.

def _declare_build_argv(tmp_path, monkeypatch, *, flags: str, compiler: str):
    """Run `declare_target` and return the argv of the shared-library link."""
    from ari.assurance.problems import load_problem
    from ari.evaluator import assurance_measure as am

    problem = load_problem("gemm-dense-fp64/v1@2026q3")
    am.seed_work_dir(tmp_path, problem)
    (tmp_path / am.CANDIDATE_FLAGS_FILE).write_text(flags, encoding="utf-8")
    (tmp_path / am.CANDIDATE_COMPILER_FILE).write_text(compiler, encoding="utf-8")

    seen: list[list[str]] = []
    real_run = am.subprocess.run

    def spy(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)):
            seen.append([str(item) for item in argv])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(am.subprocess, "run", spy)
    am.declare_target(tmp_path, problem)
    links = [argv for argv in seen if "-shared" in argv]
    assert links, f"no shared-library link was run; saw {seen}"
    return links[0]


def test_a_candidate_cannot_put_its_own_toolchain_into_the_declare_build(
    tmp_path, monkeypatch
):
    marker = tmp_path / "PWNED"
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "as").write_text(f"#!/bin/sh\ntouch {marker}\nexec /usr/bin/as \"$@\"\n")
    (fake / "as").chmod(0o755)

    argv = _declare_build_argv(
        tmp_path, monkeypatch,
        flags=f"-O2 -B{fake} -I{tmp_path}/evil -L{tmp_path} -lm", compiler="cc")

    assert not marker.exists(), (
        "the candidate's own binary was executed by the declare-time build")
    assert "-O2" in argv, "the screen must still admit an ordinary optimisation flag"
    for token in argv:
        assert not token.startswith("-B"), f"a -B reached the link: {token}"
        assert not token.startswith("-L"), f"a -L reached the link: {token}"
        assert not token.startswith("-l"), f"a -l reached the link: {token}"
    # The pinned contract-header include is the instrument's own and must stay;
    # the candidate's must not.
    assert f"-I{tmp_path}/evil" not in argv
    assert any(token.startswith("-I") for token in argv), (
        "the pinned contract header include was dropped along with the rest")


def test_the_declare_build_will_not_run_a_compiler_the_allowlist_refuses(
    tmp_path, monkeypatch
):
    impostor = tmp_path / "my_compiler"
    impostor.write_text("#!/bin/sh\nexit 0\n")
    impostor.chmod(0o755)

    argv = _declare_build_argv(tmp_path, monkeypatch,
                               flags="-O2", compiler=str(impostor))

    assert argv[0] != str(impostor), (
        "the candidate named its own compiler and the declare build ran it")
