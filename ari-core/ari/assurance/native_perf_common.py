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
import re as _re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

# PIN THE CONTROL-SIDE BLAS BEFORE ANYTHING IMPORTS NUMPY. The oracle runs in
# THIS process; an unpinned OpenBLAS/MKL spins up a thread pool sized to the whole
# allocation and keeps it alive on the same cores the next timed child will use.
# setdefault, not assignment: an operator who pinned it differently keeps their
# value, and the choice is recorded either way.
for _blas in ("OPENBLAS_NUM_THREADS", "GOTO_NUM_THREADS", "MKL_NUM_THREADS",
              "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas, "1")

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

#: What a candidate flag may LOOK LIKE. An allowlist, not a denylist: the deny
#: list below can only refuse what someone thought of, and the flags that matter
#: here are the ones that change WHAT IS BUILT rather than how well.
#:
#: A deny-only screen let ``-I`` through, and an accepted ``-I`` lands before the
#: pinned ``-I<kernels>`` in the argv, so a candidate-supplied header wins the
#: quoted include and the header-less staging below is inert. Verified by
#: compiling a candidate with its own ``gemm_kernel.h``: the candidate's header
#: won. ``-B`` was accepted too, which substitutes the compiler proper inside the
#: scored compile — the one thing a compiler allowlist exists to prevent.
#:
#: This admits optimisation and ISA selection (-O*, -f*, -m*, the vendor's -K/-N
#: namespaces, --param=k=v) and nothing that names a path, a library, a linker
#: option or an output.
FLAG_ALLOW_PATTERN = _re.compile(
    r"^(?:-O[0-3sgz]?|-Ofast"
    r"|-f[A-Za-z0-9][A-Za-z0-9._-]*(?:=[A-Za-z0-9._,+-]+)?"
    r"|-m[A-Za-z0-9][A-Za-z0-9._-]*(?:=[A-Za-z0-9._,+-]+)?"
    r"|-K[A-Za-z0-9][A-Za-z0-9._,=-]*"
    r"|-N[A-Za-z0-9][A-Za-z0-9._,=-]*"
    r"|--param=[A-Za-z0-9_-]+=[0-9]+)$"
)

#: Refused even when the shape above admits them. Compiler instrumentation
#: carries state between repetitions; link-time optimisation defeats the
#: object-level checks; the vendor library spellings link a BLAS that is out of
#: contract for these kernels.
FLAG_DENY_SUBSTRINGS: tuple[str, ...] = (
    "profile", "fjprof", "sanitize", "plugin", "specs",
    "lto", "whole-program", "-fno-openmp", "noopenmp",
    "ssl2", "scalapack",
)

#: A command line is not an essay. The cap also bounds what a malformed flag
#: file can do to the argv.
FLAG_MAX_TOKENS = 32


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
    #: Resolved toolchains with their VERSIONS, so a ratio can be read next to
    #: what produced it. A bare name is not an identity: the same `cc` is one
    #: version on the submit node and another on the compute nodes.
    default_toolchain: dict[str, Any]
    #: Including what the candidate ASKED for and whether it got it. A run that
    #: requested the vendor compiler, did not get it, and was scored on the
    #: default was otherwise indistinguishable from one that requested nothing.
    candidate_toolchain: dict[str, Any]
    crossed_compiler_boundary: bool
    #: The flags that produced these numbers, and the ones that were dropped. A
    #: candidate could not learn its flags were refused, and a reader could not
    #: reconstruct which flags a number came from.
    base_flags: tuple[str, ...]
    reference_flags: tuple[str, ...]
    accepted_flags: tuple[str, ...]
    rejected_flags: tuple[str, ...]
    #: Captured by prefix with its own digest, so a run can be compared with
    #: another only when the conditions match.
    environment: dict[str, Any]
    #: WHICH PROBLEMS, named and pinned. A report that did not say this could be
    #: read as evidence about a size it never measured.
    dataset_revision: str
    dataset_sha256: str
    #: Where it ran. Two allocations of different shape otherwise produce
    #: identical records, and placement is not neutral for a timed kernel.
    placement: dict[str, Any]
    negative_control: bool = False

    @model_validator(mode="after")
    def _placement_is_a_record(self):
        """An empty placement is a valid dict and an invalid measurement.

        The schema enforced "a placement field exists", not "a placement was
        recorded", so a producer emitting {} minted a digest-bound report that
        said nothing about where it ran.
        """
        missing = [k for k in ("machine", "cpus_allowed", "numa_nodes_total",
                               "thread_budget", "sha256")
                   if k not in self.placement]
        if missing:
            raise ValueError(f"placement record is missing {missing}")
        return self
    report_digest: str = Field(default="")


# --------------------------------------------------------------------------
# which problems: a pinned case set, never a request parameter
# --------------------------------------------------------------------------

class CaseSetV1(StrictModel):
    """A named, digest-pinned set of problems a harness measures on."""

    schema_version: Literal["ari.harness-case-set/v1"] = "ari.harness-case-set/v1"
    revision: str
    kind: PerfKind
    description: str
    cases: tuple[tuple[int, ...], ...]
    #: False marks a set that is cheap but NOT resolved enough to support a
    #: verdict. Stated in the data rather than left for a reader to infer from
    #: the numbers after the fact.
    resolves: bool = True


def case_sets_root() -> Path:
    configured = os.environ.get("ARI_HARNESS_CASE_SETS")
    if configured:
        return Path(configured)
    return (Path(__file__).resolve().parents[2]
            / "config" / "harnesses" / "case_sets")


def load_case_set(revision: str) -> tuple[CaseSetV1, str]:
    """Resolve a case-set revision to its cases and the digest of its bytes.

    The size a harness measures at is DATA, not a request parameter. Registration
    evidence is established at a size and does not transfer -- measured on an
    aarch64 compute node, the same harness reproduced to 0.095% at the scored
    shape and to a 100x spread at a small one. A run free to choose its own size
    would carry an attestation saying "verified" about a problem the manifest
    never named.

    So the manifest names a revision in ``dataset.revision`` and pins these bytes
    in ``dataset.sha256``: changing a size changes this file, which changes the
    manifest digest, which is a re-registration. Returns ``(case_set, sha256)``
    so the caller can check the pin.
    """
    import yaml as _yaml

    root = case_sets_root()
    if not root.is_dir():
        raise PerfInfrastructureError(f"no case-set directory at {root}")
    for path in sorted(root.glob("*.yaml")):
        raw = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if str(raw.get("revision", "")) != revision:
            continue
        case_set = CaseSetV1.model_validate(raw)
        digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if not case_set.cases:
            raise PerfInfrastructureError(
                f"case set {revision!r} declares no cases")
        return case_set, digest
    known = sorted(
        str((_yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("revision"))
        for p in sorted(root.glob("*.yaml"))
    )
    raise PerfInfrastructureError(
        f"no registered case set {revision!r}; a size is chosen by naming a "
        f"pinned set, not by passing shapes. Known: {known}")


# --------------------------------------------------------------------------
# toolchain resolution
# --------------------------------------------------------------------------

def default_compiler() -> str:
    return os.environ.get("ARI_PERF_CC", "cc")


#: Where a compiler may live when it is not on PATH. The vendor toolchain is
#: reachable only once its module is loaded, and the measuring job pins a bare
#: PATH — so a which()-only probe reports "unavailable" for a compiler that is
#: sitting on the disk. Verified on a compute node: shutil.which("fcc") is None
#: while /opt/<vendor>/*/bin/fcc exists. Globs, not a pinned version, so a site
#: upgrade does not silently remove the toolchain axis.
COMPILER_SEARCH_GLOBS: dict[str, tuple[str, ...]] = {
    "fcc": ("/opt/FJSVstclanga/*/bin/fcc",),
}


def toolchain_identity(compiler: str) -> dict[str, str | None]:
    """Resolve a compiler and capture its VERSION.

    A bare name is not an identity: the same ``cc`` is one version on the submit
    node and another on the compute nodes, and a campaign that changed version
    mid-flight would be confounded with the conditions rather than recorded.
    Failures are recorded, not raised — the build a moment later gives a better
    message than this probe could.
    """
    path = shutil.which(compiler) or compiler
    version = None
    try:
        completed = subprocess.run([path, "--version"], capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode == 0 and completed.stdout:
            version = completed.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        version = None
    return {"requested": compiler, "resolved_path": path, "version": version}


def runtime_libs_for(resolved: str | None) -> str | None:
    """Loader directories a binary built by *resolved* may need.

    Without this a candidate that legitimately selects the vendor compiler
    builds, links, and then dies at exec on a missing shared object — charged to
    the candidate for a harness omission.
    """
    if not resolved:
        return None
    bindir = Path(resolved).resolve().parent
    candidates = [bindir.parent / "lib64", bindir.parent / "lib"]
    present = [str(path) for path in candidates if path.is_dir()]
    return ":".join(present) or None


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
        # Not on PATH is not the same as not installed.
        import glob as _glob
        for pattern in COMPILER_SEARCH_GLOBS.get(want, ()):
            found = sorted(_glob.glob(pattern))
            if found:
                resolved = found[-1]
                break
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
    """Split candidate-declared flags into ``(accepted, rejected)``.

    A token must MATCH THE ALLOWED SHAPE and then survive the deny list; failing
    either rejects it. Literal ``\n``/``\t`` are normalised first, because a
    flag file written that way otherwise glues a comment tail onto the first real
    flag and destroys it — measured on 54 of 2133 files in the prototype's
    corpus. Comments run from ``#`` to end of line, matching how the agent-facing
    build strips them, so the local build and the scored build agree.
    """
    text = (raw or "").replace("\\n", "\n").replace("\\t", "\t")
    accepted: list[str] = []
    rejected: list[str] = []
    for line in text.splitlines():
        for token in line.split("#", 1)[0].split():
            lowered = token.lower()
            if len(accepted) >= FLAG_MAX_TOKENS:
                rejected.append(token)
            elif any(bad in lowered for bad in FLAG_DENY_SUBSTRINGS):
                rejected.append(token)
            elif FLAG_ALLOW_PATTERN.match(token):
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

    cpus = mems = None
    for line in (_read("/proc/self/status") or "").splitlines():
        if line.startswith("Cpus_allowed_list:"):
            cpus = line.split(":", 1)[1].strip()
        elif line.startswith("Mems_allowed_list:"):
            mems = line.split(":", 1)[1].strip()
    nodes = {}
    for entry in sorted(Path("/sys/devices/system/node").glob("node*")):
        listing = _read(str(entry / "cpulist"))
        if listing is not None:
            nodes[entry.name] = listing
    try:
        page = os.sysconf("SC_PAGESIZE")
    except (ValueError, OSError):
        page = None
    import json as _json

    allowed = _cpu_set(cpus or "")
    regime = measurement_thread_regime()
    body = {
        "machine": os.uname().machine,
        "page_size_bytes": page,
        "cpus_allowed": cpus,
        # Machine-comparable without re-parsing a cpulist at analysis time.
        "cpus_allowed_count": len(allowed) or None,
        # Which domains memory may be allocated FROM. Independent of the cpu
        # mask, and on a first-touch machine it is what decides where the scored
        # arrays land -- dropping it made a memory-confined run and an
        # unconfined one byte-identical.
        "mems_allowed": mems,
        "numa_nodes_total": len(nodes) or None,
        "numa_node_cpulists": nodes or None,
        # Packed on one domain or spread across four, at the same core count,
        # is a different machine for a bandwidth-bound kernel.
        "numa_nodes_spanned": len(
            [n for n, cl in nodes.items() if allowed and (_cpu_set(cl) & allowed)]
        ) or None,
        # What the TIMED CHILD is given, not what happens to be ambient here.
        "thread_budget": regime["OMP_NUM_THREADS"],
        "omp_proc_bind": regime["OMP_PROC_BIND"],
        "omp_places": regime["OMP_PLACES"],
        "omp_dynamic": regime["OMP_DYNAMIC"],
        # The binding above IS set by the harness; the memory policy is not.
        # There is no numactl, taskset, mbind or set_mempolicy on this path.
        "binding_is_set_by_the_harness": True,
        "memory_policy_is_set_by_the_harness": False,
    }
    digest = hashlib.sha256(
        _json.dumps(body, sort_keys=True, separators=(",", ":"),
                    default=str).encode()).hexdigest()
    # Its OWN digest, so records can be grouped by allocation shape. Folded into
    # the report digest alone it identifies the whole run and nothing smaller.
    return {**body, "sha256": f"sha256:{digest}"}


def _cpu_set(spec: str) -> set:
    out: set = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo, hi = part.split("-", 1)
                out.update(range(int(lo), int(hi) + 1))
            else:
                out.add(int(part))
        except ValueError:
            return set()
    return out


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
    main_src: Path | None = None,
    tag: str | None = None,
    entry_point: str | None = None,
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
    # main_src swaps the FROZEN DRIVER only -- same kernel source, same compiler,
    # same flags, same object-level audit. It exists for the profiled driver,
    # which is the scored one plus a counter gate; the scored build passes
    # nothing and is unchanged. One compile path, because a second would drift
    # from the flags being profiled.
    main_c = Path(main_src) if main_src else kdir / f"{kind}_main.c"
    _tag = tag or role
    if not main_c.is_file():
        raise PerfInfrastructureError(f"frozen driver missing: {main_c}")
    staged = source
    if role == "candidate":
        staged = out_dir / f"candidate_{_tag}_{kind}.c"
        shutil.copy2(source, staged)

    base = ["-O3", "-fopenmp", *isa_flags_for(compiler)]
    main_o = out_dir / f"main_{_tag}.o"
    kern_o = out_dir / f"kern_{_tag}.o"
    exe = out_dir / f"kernel_{_tag}.exe"

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

    # Audit BEFORE linking: once the object is in the executable the symbols have
    # already won, and the point is to refuse rather than to detect afterwards.
    audit_kernel_object(entry_point or kind, kern_o, role=role)

    completed = _run([compiler, *base, *reference_flags, str(main_o), str(kern_o),
                      "-o", str(exe), "-lm"], "linker")
    if completed.returncode != 0:
        message = f"{role} failed to link: {completed.stderr.strip()[-400:]}"
        if role == "candidate":
            raise PerfBuildError(message)
        raise PerfInfrastructureError(message)
    return exe


#: Sections that mean "this object runs code outside the measured call".
_OUT_OF_BAND_SECTIONS = (".init_array", ".preinit_array", ".ctors",
                         ".fini_array", ".dtors")


def audit_kernel_object(entry_point: str, obj: Path, *, role: str) -> None:
    """Refuse a kernel object that can act outside the timed call.

    Three checks, because they catch three different things and the first two
    alone are not enough:

    * ``nm -g --defined-only`` — the object may export the kernel entry point and
      nothing else. This is what stops a candidate defining ``clock_gettime``
      (the driver's ``now_sec`` is static and not shadowable, but the libc
      symbol is) or ``GOMP_parallel``.
    * ``readelf -SW`` — no ``.init_array``/``.fini_array``/``.ctors``/``.dtors``.
      Out-of-band code exports NO extra global symbol, so the name check above
      cannot see it. A destructor is exactly how the prototype's own forge test
      cheated: it read ``/proc/self/cmdline`` for the private timing path and
      overwrote it.
    * ``readelf -sW`` — no IFUNC. An ifunc resolver runs at load, before main.

    Fails CLOSED. If ``nm`` or ``readelf`` cannot run, the object is not audited
    and nothing may be measured with it: an unaudited object that scored would
    make every one of these checks optional in practice.
    """
    entry = entry_point
    if not entry:
        raise PerfInfrastructureError("no entry point declared for this kernel")

    def _tool(argv: list[str], what: str):
        try:
            completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        except OSError as exc:
            raise PerfInfrastructureError(
                f"{what} is unavailable, so {role} cannot be audited: {exc}") from exc
        if completed.returncode != 0:
            raise PerfInfrastructureError(
                f"{what} failed on {role}: {completed.stderr.strip()[-200:]}")
        return completed.stdout

    fault = PerfBuildError if role == "candidate" else PerfInfrastructureError

    listing = _tool(["nm", "-g", "--defined-only", str(obj)], "nm")
    exported = sorted({
        parts[-1] for line in listing.splitlines()
        if len(parts := line.split()) >= 3 and parts[-2] in "TDBRWVi"
    } - {entry})
    if exported:
        raise fault(
            f"{role} kernel exports symbols other than {entry!r}: {exported[:8]}")

    sections = _tool(["readelf", "-SW", str(obj)], "readelf")
    symbols = _tool(["readelf", "-sW", str(obj)], "readelf")
    out_of_band = sorted({name for name in _OUT_OF_BAND_SECTIONS if name in sections})
    ifuncs = sorted({
        parts[7] for line in symbols.splitlines()
        if len(parts := line.split()) >= 8 and parts[3] == "IFUNC"
    })
    if out_of_band or ifuncs:
        raise fault(
            f"{role} kernel runs code outside the measured call "
            f"(sections={out_of_band}, ifunc={ifuncs}); all work must happen "
            f"inside {entry}")


#: Captured by PREFIX, never by a list of names. A hand list records exactly the
#: variables somebody thought of: the prototype's list omitted the one variable
#: later measured to move the same frozen source by 5.9x. Secrets are dropped by
#: name fragment so a credential's VALUE never reaches a published record.
_ENV_PREFIXES: tuple[str, ...] = (
    "ARI_", "OMP_", "GOMP_", "KMP_", "XOS_", "FLIB_", "FJ_", "MALLOC_",
    "OPENBLAS_", "GOTO_", "MKL_", "BLIS_", "VECLIB_", "NUMEXPR_",
    "LD_LIBRARY_PATH", "LD_PRELOAD", "NUMA",
)
_ENV_SECRET: tuple[str, ...] = (
    "SECRET", "TOKEN", "PASSWORD", "PASSWD", "KEY", "CREDENTIAL",
)


def measurement_environment(extra: dict[str, str] | None = None) -> dict[str, Any]:
    """What the measurement was taken under, with a digest.

    Recorded, not restricted: a variable outside this prefix set is neither
    captured nor known to be harmless, and the note says so rather than implying
    coverage.
    """
    import json as _json

    env: dict[str, str] = {}
    for key, value in sorted(os.environ.items()):
        if not key.startswith(_ENV_PREFIXES):
            continue
        if any(fragment in key.upper() for fragment in _ENV_SECRET):
            continue
        env[key] = value
    if extra:
        env.update({k: v for k, v in extra.items()
                    if not any(f in k.upper() for f in _ENV_SECRET)})
    digest = hashlib.sha256(
        _json.dumps(env, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "variables": env,
        "sha256": f"sha256:{digest}",
        "note": ("recorded, not restricted; a variable outside this prefix set is "
                 "neither captured nor known to be harmless"),
    }


def _fault(role: str):
    """A frozen-reference failure is a SUBSTRATE failure.

    Charging it to the candidate produced messages naming a program the candidate
    did not write ("candidate exceeded 300s" for a descheduled anchor) and scored
    an overloaded node as a bad kernel.
    """
    return PerfBuildError if role == "candidate" else PerfInfrastructureError


def measurement_thread_regime() -> dict[str, str]:
    """The thread budget and binding every timed process is given.

    The budget defaults to the CPUs the allocation actually granted, not to
    ``os.cpu_count()``: on a shared node the cpuset is narrower than the machine,
    and a team sized to the machine oversubscribes it.
    """
    configured = os.environ.get("ARI_PERF_THREADS")
    if configured:
        threads = configured
    else:
        try:
            threads = str(len(os.sched_getaffinity(0)))
        except (AttributeError, OSError):
            threads = str(os.cpu_count() or 1)
    return {
        "OMP_NUM_THREADS": threads,
        "OMP_PROC_BIND": os.environ.get("OMP_PROC_BIND", "spread"),
        "OMP_PLACES": os.environ.get("OMP_PLACES", "cores"),
        # Without this the runtime may hand consecutive processes in one
        # repetition different team sizes.
        "OMP_DYNAMIC": os.environ.get("OMP_DYNAMIC", "FALSE"),
    }


def run_timed(exe: Path, problem: Path, out_path: Path, timing: Path,
              *, timeout: float, role: str = "candidate",
              ld_library_path: str | None = None,
              launcher: tuple[str, ...] = (),
              capture: dict[str, str] | None = None,
              env: dict[str, str] | None = None) -> float:
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
    # BOTH SIDES OF THE COMPARISON MEASURED UNDER ONE REGIME. Nothing set the
    # thread budget or the binding, so the team size was whatever libgomp made of
    # the visible CPUs and threads migrated freely — and under an isolated
    # executor the placement variables are not in the environment at all, so the
    # three fields the placement record reports would be null while the run was
    # still bound to something. Pinned here so the anchor, the candidate and the
    # matched reference are all measured the same way, and recorded so a reader
    # can see which way that was.
    run_env.update(measurement_thread_regime())
    if ld_library_path:
        previous = run_env.get("LD_LIBRARY_PATH", "")
        run_env["LD_LIBRARY_PATH"] = (f"{ld_library_path}:{previous}"
                                      if previous else ld_library_path)
    try:
        completed = subprocess.run(
            [*launcher, str(exe), str(problem), str(out_path), str(timing)],
            capture_output=True, text=True, timeout=timeout, env=run_env,
            start_new_session=True)
    except subprocess.TimeoutExpired as exc:
        raise _fault(role)(f"{role} exceeded {timeout:g}s") from exc
    # `capture` is how a launcher's stdout gets back out. The scored path drains
    # stdout only so the pipe cannot fill; default None keeps that behaviour.
    if capture is not None:
        capture["stdout"] = completed.stdout or ""
        capture["stderr"] = completed.stderr or ""
    if completed.returncode != 0:
        raise _fault(role)(f"{role} run failed: {completed.stderr.strip()[-400:]}")
    if not timing.is_file():
        raise _fault(role)(f"{role} wrote no timing")
    raw = timing.read_bytes()
    if len(raw) < 8:
        raise _fault(role)(f"{role} wrote a short timing record")
    seconds = struct.unpack("<d", raw[:8])[0]
    if not (math.isfinite(seconds) and seconds > 0):
        raise _fault(role)(f"{role} reported an impossible time: {seconds!r}")
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
    "FLAG_ALLOW_PATTERN",
    "FLAG_DENY_SUBSTRINGS",
    "FLAG_MAX_TOKENS",
    "TIER_REPETITIONS",
    "NativePerfReportV1",
    "PerfBuildError",
    "PerfCaseResultV1",
    "PerfInfrastructureError",
    "PerfKind",
    "PerfRepetitionV1",
    "PerfTier",
    "audit_kernel_object",
    "CaseSetV1",
    "case_sets_root",
    "compile_binary",
    "crosses_compiler_boundary",
    "default_compiler",
    "isa_flags_for",
    "kernels_root",
    "load_case_set",
    "measurement_environment",
    "measurement_placement",
    "measurement_thread_regime",
    "median",
    "relative_spread",
    "resolve_compiler",
    "runtime_libs_for",
    "toolchain_identity",
    "run_timed",
    "screen_flags",
    "source_digest",
]
