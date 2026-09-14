"""Exact C ABI adapters for the native correctness families.

Each adapter marshals one kernel's exact signature, so this is per-family CODE
and cannot be data. What it stopped being is a per-family TABLE: the dispatch
dict at the bottom listed every kind, so the set of answerable questions was
written out here as well as in a Literal, a second dispatch dict and two
argparse ``choices`` tuples -- five places to find when one changed. Each
adapter now declares its own name where it is defined, and dispatch asks.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any, Callable


class NativeABIError(RuntimeError):
    pass


#: kind -> ABI adapter, populated by the decorator below at definition site.
_ABI_ADAPTERS: dict[str, Callable[..., Any]] = {}


def _abi_adapter(kind: str):
    """Declare which family an adapter serves, beside the adapter."""

    def register(function):
        if kind in _ABI_ADAPTERS:
            raise NativeABIError(f"two ABI adapters registered for {kind!r}")
        _ABI_ADAPTERS[kind] = function
        return function

    return register


def abi_adapter_kinds() -> tuple[str, ...]:
    """Every kind that can be called through this module."""
    return tuple(sorted(_ABI_ADAPTERS))


def _library(path: str | Path) -> ctypes.CDLL:
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise NativeABIError("native target must be a regular shared library")
    return ctypes.CDLL(str(target), mode=getattr(ctypes, "RTLD_LOCAL", 0))


def _scalar(dtype: str):
    if dtype == "float32":
        return ctypes.c_float, "f32"
    if dtype == "float64":
        return ctypes.c_double, "f64"
    raise NativeABIError(f"unsupported dtype: {dtype}")


def _array(values: list[float], scalar, offset: int = 0):
    storage = (scalar * (len(values) + offset))()
    for index, value in enumerate(values):
        storage[index + offset] = value
    pointer = ctypes.cast(
        ctypes.byref(storage, offset * ctypes.sizeof(scalar)),
        ctypes.POINTER(scalar),
    )
    return storage, pointer


def _output(storage, count: int, offset: int = 0) -> list[float]:
    return [float(storage[index + offset]) for index in range(count)]


@_abi_adapter("gemm")
def run_gemm(path: str | Path, case: dict[str, Any]) -> list[float]:
    scalar, suffix = _scalar(str(case["dtype"]))
    library = _library(path)
    try:
        function = getattr(library, f"ari_gemm_{suffix}")
    except AttributeError as exc:
        raise NativeABIError(f"missing ari_gemm_{suffix} symbol") from exc
    function.restype = ctypes.c_int
    offset = int(case.get("alignment_offset", 0))
    a_store, a_ptr = _array(list(case["a"]), scalar, offset)
    b_store, b_ptr = _array(list(case["b"]), scalar, offset)
    c_store, c_ptr = _array(list(case["c"]), scalar, offset)
    status = function(
        ctypes.c_int(int(case["m"])),
        ctypes.c_int(int(case["n"])),
        ctypes.c_int(int(case["k"])),
        ctypes.c_int(int(bool(case["transpose_a"]))),
        ctypes.c_int(int(bool(case["transpose_b"]))),
        ctypes.c_int(int(case["lda"])),
        ctypes.c_int(int(case["ldb"])),
        ctypes.c_int(int(case["ldc"])),
        scalar(float(case["alpha"])),
        a_ptr,
        b_ptr,
        scalar(float(case["beta"])),
        c_ptr,
        ctypes.c_int(int(case["thread_count"])),
    )
    if status != 0:
        raise NativeABIError(f"GEMM target returned status {status}")
    return _output(c_store, len(case["c"]), offset)


@_abi_adapter("spmm")
def run_spmm(path: str | Path, case: dict[str, Any]) -> list[float] | dict[str, str]:
    scalar, suffix = _scalar(str(case["dtype"]))
    library = _library(path)
    try:
        function = getattr(library, f"ari_spmm_{suffix}")
    except AttributeError as exc:
        raise NativeABIError(f"missing ari_spmm_{suffix} symbol") from exc
    function.restype = ctypes.c_int
    row_ptr = (ctypes.c_int64 * len(case["row_ptr"]))(*map(int, case["row_ptr"]))
    col_idx = (ctypes.c_int64 * len(case["col_idx"]))(*map(int, case["col_idx"]))
    values_store, values_ptr = _array(list(case["values"]), scalar)
    b_store, b_ptr = _array(list(case["b"]), scalar)
    c_store, c_ptr = _array(list(case["c"]), scalar)
    flags = 1 if case.get("duplicate_policy") == "sum" else 0
    status = function(
        ctypes.c_int(int(case["m"])),
        ctypes.c_int(int(case["k"])),
        ctypes.c_int(int(case["n"])),
        ctypes.c_int64(len(case["values"])),
        row_ptr,
        col_idx,
        values_ptr,
        b_ptr,
        ctypes.c_int(int(case["ldb"])),
        c_ptr,
        ctypes.c_int(int(case["ldc"])),
        scalar(float(case["alpha"])),
        scalar(float(case["beta"])),
        ctypes.c_int(int(case["thread_count"])),
        ctypes.c_uint(flags),
    )
    if status != 0:
        return {"status": "invalid_input"}
    return _output(c_store, len(case["c"]))


@_abi_adapter("stencil")
def run_stencil(path: str | Path, case: dict[str, Any]) -> list[float]:
    scalar, suffix = _scalar(str(case["dtype"]))
    library = _library(path)
    try:
        function = getattr(library, f"ari_stencil_{suffix}")
    except AttributeError as exc:
        raise NativeABIError(f"missing ari_stencil_{suffix} symbol") from exc
    function.restype = ctypes.c_int
    input_store, input_ptr = _array(list(case["input"]), scalar)
    output_store, output_ptr = _array([0.0] * len(case["input"]), scalar)
    status = function(
        ctypes.c_int(int(case["nx"])),
        ctypes.c_int(int(case["ny"])),
        ctypes.c_int(int(case["nz"])),
        ctypes.c_int(int(case["iterations"])),
        ctypes.c_int(1 if case["boundary"] == "periodic" else 0),
        ctypes.c_int(1 if case["update_mode"] == "in-place" else 0),
        input_ptr,
        output_ptr,
        ctypes.c_int(int(case["thread_count"])),
    )
    if status != 0:
        raise NativeABIError(f"Stencil target returned status {status}")
    return _output(output_store, len(case["input"]))


def run_shared_library(
    kind: str, path: str | Path, case: dict[str, Any]
) -> list[float] | dict[str, str]:
    try:
        function = _ABI_ADAPTERS[kind]
    except KeyError as exc:
        raise NativeABIError(
            f"unsupported native Harness kind: {kind!r}; known: "
            f"{list(abi_adapter_kinds())}") from exc
    return function(path, case)


__all__ = ["NativeABIError", "abi_adapter_kinds", "run_gemm",
           "run_shared_library", "run_spmm", "run_stencil"]
