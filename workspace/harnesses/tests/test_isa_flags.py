"""The ISA flag is chosen per compiler, because one compiler rejects the usual one.

WHY IT EXISTS. `-march=native` is the obvious way to let a candidate use the
machine it is running on, and it is what the harness passes by default. The
vendor compiler does not accept it IN THE MODE WORTH SELECTING IT FOR.
Measured on an aarch64 compute node 2026-08-07: `fcc -O3 -fopenmp -march=native`
compiles (rc=0), but `fcc -Nclang -O3 -fopenmp -march=native` fails with
`clang-7: error: the clang compiler does not support '-march=native'` — and
`-Nclang` is the mode in which fcc measured 403 GF/s against gcc's 385 on this
kernel, i.e. the only reason to select it. So the flag breaks exactly the
interesting case, not every case. That
happened on all three tasks, and it did not look like a bug -- a candidate that
names an unavailable compiler is *designed* to fall back to the default and have
the fallback recorded. So the toolchain axis reported "fcc was not usable here"
in a well-formed way, for every run, while the real cause was one flag the
harness itself was adding.

That is the shape worth guarding: not a crash, but a silent collapse of an
experimental axis into a recorded, plausible-looking fallback. The tests below
pin both directions -- the vendor compiler must not be handed the flag, and the
compilers that do accept it must still get it, since dropping it everywhere
would quietly de-optimize every default build instead.
"""
import importlib
import pathlib
import sys

import pytest

HARNESSES = pathlib.Path(__file__).resolve().parents[1]
TASKS = ("gemm", "spmm", "stencil")

# The vendor driver names. Each rejects -march=native in -Nclang mode,
# which is the mode a candidate selects fcc in.
VENDOR = ("fcc", "FCC", "mpifcc", "mpiFCC")
# Compilers that accept it, and whose builds get slower without it.
ACCEPTS_NATIVE = ("gcc", "clang", "cc", "gcc-13", "clang-17")


@pytest.fixture(params=TASKS)
def harness(request, monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESSES / request.param))
    mod = importlib.import_module(f"{request.param}_harness")
    yield mod
    sys.modules.pop(f"{request.param}_harness", None)


@pytest.mark.parametrize("cc", VENDOR)
def test_the_vendor_compiler_is_not_handed_a_flag_it_rejects(harness, cc):
    """This is the flag that made every fcc run report an unusable compiler."""
    assert "-march=native" not in harness._isa_flags_for(cc), (
        f"{cc} rejects -march=native outright, so the compile fails, the "
        f"candidate falls back to the default compiler, and the fallback is "
        f"recorded as if the vendor toolchain had simply been unavailable. The "
        f"toolchain axis then reads as a measured result rather than a harness "
        f"defect.")


@pytest.mark.parametrize("cc", VENDOR)
def test_the_vendor_compiler_is_recognised_by_path_too(harness, cc):
    """Selection resolves to an absolute path before this is called."""
    full = f"/opt/some-vendor-tree/cp-1.0/bin/{cc}"
    assert "-march=native" not in harness._isa_flags_for(full), (
        "the compiler arrives here as a resolved path, so matching only the "
        "bare name would let the flag back in on every real invocation while "
        "the unit test still passed")


@pytest.mark.parametrize("cc", ACCEPTS_NATIVE)
def test_a_compiler_that_accepts_native_still_gets_it(harness, cc):
    """Dropping it for everyone would trade one silent defect for another."""
    assert "-march=native" in harness._isa_flags_for(cc), (
        f"{cc} accepts -march=native and needs it to emit SVE for this part; "
        f"removing it globally would de-optimize the default build, which is "
        f"the denominator of every score")


def test_an_unknown_compiler_gets_the_default_treatment(harness):
    """A name nobody anticipated must not crash the compile step."""
    assert isinstance(harness._isa_flags_for("some-future-cc"), list)
    assert isinstance(harness._isa_flags_for(""), list)
    assert isinstance(harness._isa_flags_for(None), list)


def test_the_flags_are_actually_used_on_the_compile_line(harness):
    """A correct helper nobody calls fixes nothing."""
    src = (HARNESSES / harness.__name__.split("_")[0]
           / f"{harness.__name__}.py").read_text()
    assert "_isa_flags_for(cc)" in src, (
        "the per-compiler ISA flags must reach the base compile flags; "
        "otherwise fcc goes on being handed -march=native")
