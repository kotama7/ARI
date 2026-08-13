"""A conformance declaration must be checked, not asserted.

Regression: the scoring path declared `interface_contract: gemm-c-abi/v1` for a
library built from a problem whose scaffolding exports `gemm`. The verifier
resolves `ari_gemm_f32` / `ari_gemm_f64`, so 33 of 33 cases failed with
"missing symbol" and every reported error was exactly 0.0 -- the kernel was
never entered. The declaration was a claim with nothing behind it.
"""
import ctypes.util
import subprocess

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
