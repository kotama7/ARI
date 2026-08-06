"""Measurement machinery for the ARI-native performance harnesses.

WHAT THIS IS FOR. The assurance catalog can express a ``benchmark`` harness
declaring ``performance-regression`` via ``benchmark-comparison`` — the slot has
been reserved and empty, while three knowledge-skill import profiles already
REQUIRE that property, so the requirement resolves to ``no_candidate``. This
module is the measuring half that fills it.

WHAT IT MEASURES, AND WHY IT IS SHAPED THIS WAY. Each of these decisions was
paid for by a defect the prototype found; they are not stylistic.

ONE COLD CALL PER PROCESS. The frozen driver times exactly one call to the
kernel and writes the seconds to a private file. There is no in-process warmup
and no in-process repetition: a warmup call in the same process lets a candidate
compute during it and no-op the timed call. Repetition means repeating the
PROCESS, with a fresh problem each time.

TWO DENOMINATORS. ``anchor`` is the frozen reference built with the DEFAULT
toolchain — the published quantity. ``matched`` is the same frozen source built
the way the candidate chose, and exists because a candidate that selects another
compiler is otherwise compared across a compiler boundary, where anything acting
on one side of it moves the ratio without either program changing. Their
quotient is what the toolchain bought. The matched build is only made when the
candidate's compiler resolves to a DIFFERENT binary than the default: naming the
default under another name is not a boundary, and building anyway reported the
reference's own flags as a toolchain effect.

CORRECTNESS FIRST. A fast wrong kernel is not a fast kernel. Every repetition's
output is checked against an independent oracle with a backward-error bound
before its time is credited, and the frozen reference is checked at the scored
size too — a reference that were wrong and fast would deflate every candidate.

WHAT IT DOES NOT MEASURE. The scored arrays are allocated and first-touched by
the driver OUTSIDE the timed window, serially, so their NUMA placement is the
harness's and not the candidate's. Only scratch a candidate allocates itself is
placed under measurement. This is declared, not implied: see the manifest's
``blind_to``-equivalent scope.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ari.protocols.integrity import DigestBoundModel, StrictModel


PerfKind = Literal["gemm", "spmm", "stencil"]
PerfTier = Literal["screen", "validate", "certify"]

#: Repetitions per case, per tier. A tier buys statistical resolution, exactly
#: as it buys case coverage in the correctness verifier.
TIER_REPETITIONS: dict[str, int] = {"screen": 1, "validate": 3, "certify": 5}

#: The compilers a candidate may name. The default is whatever ``cc`` resolves
#: to on the measuring node; naming it explicitly is allowed and is not a
#: compiler boundary.
COMPILER_ALLOWLIST: tuple[str, ...] = ("cc", "gcc", "clang", "fcc")

#: Flags a candidate may not have. Compiler instrumentation carries state
#: between repetitions and link-time optimisation defeats the object-level
#: symbol check, so both are refused rather than silently tolerated.
FLAG_DENY_SUBSTRINGS: tuple[str, ...] = (
    "profile", "fjprof", "sanitize", "plugin", "specs",
    "lto", "whole-program", "-fno-openmp", "noopenmp",
)


class PerfRepetitionV1(StrictModel):
    """One process launch: one cold timed call on one freshly generated problem."""

    index: int = Field(ge=0)
    input_seed: int
    credited_seconds: float = Field(gt=0)
    reference_seconds: float = Field(gt=0)
    speedup: float = Field(gt=0)
    matched_seconds: float | None = None
    speedup_matched: float | None = None
    toolchain_gain: float | None = None
    correct: bool
    max_rel_error: float = Field(ge=0)


class PerfCaseResultV1(StrictModel):
    """One scored problem shape, aggregated over its repetitions."""

    case_id: str
    verdict: Literal["pass", "fail", "inconclusive"]
    detail: str
    #: Median of the per-repetition anchor ratios. Median, not mean: one
    #: descheduled repetition should not move the case.
    speedup: float = Field(ge=0)
    speedup_matched: float | None = None
    toolchain_gain: float | None = None
    #: The spread the reader needs before acting on the median. A single
    #: repetition has none, by construction.
    relative_spread: float | None = None
    repetitions: tuple[PerfRepetitionV1, ...]


class NativePerfReportV1(DigestBoundModel):
    """The typed result a performance worker prints and a driver normalizes."""

    _digest_field = "report_digest"

    schema_version: Literal["ari.native-perf-report/v1"] = "ari.native-perf-report/v1"
    kind: PerfKind
    tier: PerfTier
    verdict: Literal["pass", "fail", "inconclusive"]
    case_results: tuple[PerfCaseResultV1, ...]
    #: Which denominator the ratios are against, named rather than assumed.
    denominator: Literal["frozen-reference-anchor"] = "frozen-reference-anchor"
    #: The regression threshold this run was judged against.
    regression_threshold: float = Field(gt=0)
    #: Resolved toolchains, so a ratio can be read next to what produced it.
    default_toolchain: str
    candidate_toolchain: str
    crossed_compiler_boundary: bool
    #: Where it ran. Two allocations of different shape otherwise produce
    #: identical records, and placement is not neutral for a timed kernel.
    placement: dict[str, Any]
    negative_control: bool = False
    report_digest: str = Field(default="")


# --------------------------------------------------------------------------
# toolchain resolution
# --------------------------------------------------------------------------

def default_compiler() -> str:
    return os.environ.get("ARI_PERF_CC", "cc")


def resolve_compiler(name: str | None) -> tuple[str, str]:
    """Return ``(status, resolved_path)`` for a candidate-declared compiler.

    Status is ``default`` (nothing declared), ``selected``, ``not_allowed`` or
    ``unavailable``. The last two fall back to the default and say so: an absent
    vendor module is a property of the machine, not a defect in the candidate.
    """
    fallback = shutil.which(default_compiler()) or default_compiler()
    if not name:
        return "default", fallback
    want = name.strip()
    if want not in COMPILER_ALLOWLIST:
        return "not_allowed", fallback
    resolved = shutil.which(want)
    if resolved is None:
        return "unavailable", fallback
    return "selected", resolved


def crosses_compiler_boundary(status: str, resolved: str) -> bool:
    """True only when the candidate's compiler is a DIFFERENT binary.

    ``selected`` alone is not enough: the allowlist contains the default, and on
    many systems ``cc`` and ``gcc`` are one file. Comparing through realpath is
    what stops a matched denominator being built against itself.
    """
    if status != "selected" or not resolved:
        return False
    default_path = shutil.which(default_compiler()) or default_compiler()
    return os.path.realpath(resolved) != os.path.realpath(default_path)


def screen_flags(raw: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split candidate-declared flags into ``(accepted, rejected)``."""
    accepted: list[str] = []
    rejected: list[str] = []
    for line in (raw or "").splitlines():
        for token in line.split("#", 1)[0].split():
            lowered = token.lower()
            if any(bad in lowered for bad in FLAG_DENY_SUBSTRINGS):
                rejected.append(token)
            elif token.startswith("-"):
                accepted.append(token)
            else:
                rejected.append(token)
    return tuple(accepted), tuple(rejected)


def isa_flags_for(compiler: str) -> tuple[str, ...]:
    """The ISA flag spelled for the compiler actually in use.

    Measured on an aarch64 compute node: the vendor driver accepts
    ``-march=native`` in its traditional mode but rejects it under ``-Nclang``
    ("the clang compiler does not support '-march=native'"), which is the mode
    the vendor compiler is worth selecting in. Handing it to every compiler
    therefore breaks precisely the interesting case, so it is chosen per
    compiler rather than exported once.
    """
    base = os.path.basename(compiler)
    if base.startswith(("fcc", "FCC", "mpifcc", "mpiFCC")):
        return ()
    return ("-march=native",)


# --------------------------------------------------------------------------
# where it ran
# --------------------------------------------------------------------------

def measurement_placement() -> dict[str, Any]:
    """The allocation's shape and the machine's memory topology.

    A timing is a statement about a machine. Two allocations of different shape
    — four memory domains or one, the whole node or a fragment of it — otherwise
    produce identical records, and nothing sets placement anywhere on this path,
    so every field here is an inherited default rather than a pinned choice.
    """
    def _read(path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None

    cpus = None
    for line in (_read("/proc/self/status") or "").splitlines():
        if line.startswith("Cpus_allowed_list:"):
            cpus = line.split(":", 1)[1].strip()
    nodes = {}
    for entry in sorted(Path("/sys/devices/system/node").glob("node*")):
        listing = _read(str(entry / "cpulist"))
        if listing is not None:
            nodes[entry.name] = listing
    try:
        page = os.sysconf("SC_PAGESIZE")
    except (ValueError, OSError):
        page = None
    return {
        "machine": os.uname().machine,
        "page_size_bytes": page,
        "cpus_allowed": cpus,
        "numa_nodes_total": len(nodes) or None,
        "thread_budget": os.environ.get("OMP_NUM_THREADS"),
        "omp_proc_bind": os.environ.get("OMP_PROC_BIND"),
        "omp_places": os.environ.get("OMP_PLACES"),
        "placement_is_set_by_the_harness": False,
    }


# --------------------------------------------------------------------------
# build and run
# --------------------------------------------------------------------------

class PerfBuildError(RuntimeError):
    """The candidate did not build. A candidate fault, not a substrate fault."""


class PerfInfrastructureError(RuntimeError):
    """The measurement could not be taken. Never scored as a slow candidate."""


def kernels_root() -> Path:
    return Path(__file__).resolve().parent / "kernels"


def compile_binary(
    *,
    kind: PerfKind,
    role: Literal["candidate", "reference", "reference_matched"],
    source: Path,
    out_dir: Path,
    compiler: str,
    extra_flags: tuple[str, ...] = (),
    reference_flags: tuple[str, ...] = (),
) -> Path:
    """Compile the frozen driver plus one kernel into ``out_dir``.

    The driver is always compiled with the DEFAULT flags: in the prototype one
    invocation compiled driver and kernel together with the candidate's flags
    appended, so a candidate flag reached the frozen driver and could delete the
    pre-timer team creation from one side of the comparison.

    The candidate is compiled from a HEADER-LESS copy, because a quoted include
    searches the including file's own directory first — a candidate sitting
    beside an edited copy of the header would bind to that instead of the pinned
    one reached through ``-I``.
    """
    kdir = kernels_root() / kind
    main_c = kdir / f"{kind}_main.c"
    if not main_c.is_file():
        raise PerfInfrastructureError(f"frozen driver missing: {main_c}")
    staged = source
    if role == "candidate":
        staged = out_dir / f"candidate_{kind}.c"
        shutil.copy2(source, staged)

    base = ["-O3", "-fopenmp", *isa_flags_for(compiler)]
    main_o = out_dir / f"main_{role}.o"
    kern_o = out_dir / f"kern_{role}.o"
    exe = out_dir / f"kernel_{role}.exe"

    def _run(argv: list[str], what: str):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=300)
        except OSError as exc:
            raise PerfInfrastructureError(f"{what} could not be invoked: {exc}") from exc

    completed = _run([compiler, *base, f"-I{kdir}", "-c", str(main_c), "-o", str(main_o)],
                     "compiler")
    if completed.returncode != 0:
        raise PerfInfrastructureError(
            f"frozen driver failed to compile: {completed.stderr.strip()[-400:]}")

    kernel_flags = [*base, *reference_flags, *extra_flags]
    completed = _run([compiler, *kernel_flags, f"-I{kdir}", "-c", str(staged),
                      "-o", str(kern_o)], "compiler")
    if completed.returncode != 0:
        message = f"{role} failed to compile: {completed.stderr.strip()[-400:]}"
        if role == "candidate":
            raise PerfBuildError(message)
        raise PerfInfrastructureError(message)

    completed = _run([compiler, *base, str(main_o), str(kern_o), "-o", str(exe), "-lm"],
                     "linker")
    if completed.returncode != 0:
        message = f"{role} failed to link: {completed.stderr.strip()[-400:]}"
        if role == "candidate":
            raise PerfBuildError(message)
        raise PerfInfrastructureError(message)
    return exe


def run_timed(exe: Path, problem: Path, out_path: Path, timing: Path,
              *, timeout: float, env: dict[str, str] | None = None) -> float:
    """One cold call in a fresh process; return the driver's own credited time.

    The time comes from the driver's private file rather than from the wall
    clock: the wall clock includes process spawn, the problem read and the
    write-out, which on this scaffolding are the same order as the kernel.
    """
    for stale in (out_path, timing):
        try:
            stale.unlink()
        except OSError:
            pass
    run_env = dict(os.environ if env is None else env)
    run_env.pop("ARI_WORK_DIR", None)
    try:
        completed = subprocess.run(
            [str(exe), str(problem), str(out_path), str(timing)],
            capture_output=True, text=True, timeout=timeout, env=run_env,
            start_new_session=True)
    except subprocess.TimeoutExpired as exc:
        raise PerfBuildError(f"candidate exceeded {timeout:g}s") from exc
    if completed.returncode != 0:
        raise PerfBuildError(f"run failed: {completed.stderr.strip()[-400:]}")
    if not timing.is_file():
        raise PerfBuildError("kernel wrote no timing")
    raw = timing.read_bytes()
    if len(raw) < 8:
        raise PerfBuildError("kernel wrote a short timing record")
    seconds = struct.unpack("<d", raw[:8])[0]
    if not (math.isfinite(seconds) and seconds > 0):
        raise PerfBuildError(f"kernel reported an impossible time: {seconds!r}")
    return float(seconds)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def relative_spread(values: list[float]) -> float | None:
    """Max-minus-min over the median. None below two points: one point has no
    spread, and reporting 0.0 for it would read as perfect stability."""
    if len(values) < 2:
        return None
    centre = median(values)
    if centre <= 0:
        return None
    return (max(values) - min(values)) / centre


def source_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "COMPILER_ALLOWLIST",
    "FLAG_DENY_SUBSTRINGS",
    "TIER_REPETITIONS",
    "NativePerfReportV1",
    "PerfBuildError",
    "PerfCaseResultV1",
    "PerfInfrastructureError",
    "PerfKind",
    "PerfRepetitionV1",
    "PerfTier",
    "compile_binary",
    "crosses_compiler_boundary",
    "default_compiler",
    "isa_flags_for",
    "kernels_root",
    "measurement_placement",
    "median",
    "relative_spread",
    "resolve_compiler",
    "run_timed",
    "screen_flags",
    "source_digest",
]
