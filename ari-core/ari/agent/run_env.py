"""Capture-and-read helper for `_run_env.json`.

Each `_run_env.json` records *where and on what hardware* a tool call ran:
hostname, SLURM job id/partition (when applicable), CPU model, thread count.
Skills (hpc, coding) write it from inside the executing process so that the
node_report builder can later attach this metadata to `node_report.json`,
and downstream stages (paper writing, reproducibility check) can recover
"this experiment ran on gpu-private partition, hostnameX, Intel Xeon …" instead
of guessing from blank artifacts.

Why a flat JSON file beside the work_dir, not an env var:
- SLURM jobs run on a different node than the agent — env vars don't survive
- run_bash subprocesses are short-lived — same problem
- The work_dir is the one place both the executing process and the orchestrator
  can see, so it's the natural carrier
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
import pathlib
from pathlib import Path
from typing import Any

_RUN_ENV_FILENAME = "_run_env.json"


def capture_env(
    work_dir: Path | str,
    *,
    executor: str,
    slurm_job_id: str = "",
    slurm_partition: str = "",
) -> dict:
    """Write `<work_dir>/_run_env.json` describing the current host/HW.

    Idempotent in the sense of correctness: each call OVERWRITES the file.
    The latest tool call's environment wins, which matches what the user
    cares about ("where did the LAST measurement come from").

    Returns the dict that was written. Best-effort — never raises.
    """
    info: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "executor": executor or "local",
    }

    # SLURM context (preferred when present; either via arg or env)
    info["slurm_job_id"] = (
        str(slurm_job_id or os.environ.get("SLURM_JOB_ID", "")).strip()
    )
    info["slurm_partition"] = (
        slurm_partition or os.environ.get("SLURM_JOB_PARTITION", "")
    ).strip()
    nodelist = os.environ.get("SLURM_JOB_NODELIST", "").strip()
    if nodelist:
        info["slurm_nodelist"] = nodelist

    # Hostname
    try:
        info["hostname"] = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "unknown"
    except Exception:
        info["hostname"] = "unknown"

    # CPU info via lscpu (Linux); fall back to /proc/cpuinfo on parse miss
    info["cpu_info"] = _capture_cpu_info()

    # Memory total
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        info["mem_total_kb"] = int(parts[1])
                    break
    except Exception:
        pass

    # Compiler version (best-effort; helps reproducibility)
    info["compilers"] = _capture_compilers()
    # ...and what is in the vendor toolchain trees that `module avail` does not
    # list, plus the page/NUMA state that can dominate a timing. Both were added
    # after a day in which a machine was reported to have no profiler (it had
    # two, beside the compiler) and a kernel was found to run 5.9x apart on one
    # vendor memory variable.
    info["toolchain_dirs"] = _capture_toolchain_dirs()
    info["memory_system"] = _capture_memory_system()

    out_path = Path(work_dir) / _RUN_ENV_FILENAME
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(info, indent=2))
    except OSError:
        pass
    return info


def read_run_env(work_dir: Path | str) -> dict:
    """Read `<work_dir>/_run_env.json` if present.

    Returns ``{}`` when the file is missing or unparseable. Used by the
    node_report builder to enrich the report with executor metadata.
    """
    p = Path(work_dir) / _RUN_ENV_FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _capture_cpu_info() -> dict:
    """Best-effort CPU summary via lscpu, with /proc/cpuinfo as backup."""
    info: dict[str, Any] = {}
    try:
        out = subprocess.run(
            ["lscpu"], capture_output=True, text=True, timeout=3,
        ).stdout
        for line in out.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "Model name":
                info["model"] = v
            elif k == "CPU(s)":
                try: info["threads"] = int(v)
                except ValueError: pass
            elif k.startswith("CPU MHz") or k == "CPU max MHz":
                try: info["mhz"] = float(v)
                except ValueError: pass
            elif k == "Architecture":
                info["arch"] = v
            elif k == "Vendor ID":
                info["vendor"] = v
    except Exception:
        pass
    if "model" in info:
        return info

    # Fallback parse /proc/cpuinfo
    try:
        with open("/proc/cpuinfo") as fh:
            text = fh.read()
        m = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
        if m: info["model"] = m.group(1).strip()
        info["threads"] = len(re.findall(r"^processor\s*:", text, re.MULTILINE))
        m = re.search(r"^cpu MHz\s*:\s*([\d.]+)", text, re.MULTILINE)
        if m:
            try: info["mhz"] = float(m.group(1))
            except ValueError: pass
    except Exception:
        pass
    return info


def _capture_compilers() -> dict:
    """Record version of common compilers if available."""
    out: dict[str, str] = {}
    for tool, args in (("gcc", ["--version"]),
                       ("g++", ["--version"]),
                       ("python3", ["--version"])):
        try:
            r = subprocess.run(
                [tool, *args], capture_output=True, text=True, timeout=3,
            )
            text = (r.stdout or r.stderr or "").splitlines()
            if text:
                out[tool] = text[0].strip()
        except Exception:
            continue
    return out


def _capture_toolchain_dirs(max_dirs: int = 12, max_each: int = 60) -> dict:
    """Executables living in vendor toolchain trees, reported as DATA.

    WHY THIS EXISTS. The catalog's `module avail` dump is cluster-agnostic but it
    is not complete: on a two-level module tree a bare `module avail` lists entry
    modules and no compiler at all, and a vendor toolchain installed under /opt is
    invisible to it entirely. Measured 2026-08-03 on an A64FX system: the vendor
    compiler and BOTH of its profilers sat in one /opt directory that no module
    listed, and an audit that searched by module name concluded the machine had
    no profiler. It had two.

    NO NAME IS HARDCODED, keeping the property the rest of this module has: this
    enumerates whatever is executable in directories that LOOK like toolchain
    installs and hands the listing to the agent as data. It does not know what a
    compiler is called, so it stays correct on a machine whose vendor is someone
    else's.
    """
    import glob as _glob
    out: dict[str, list[str]] = {}
    seen: set[str] = set()
    for pattern in ("/opt/*/bin", "/opt/*/*/bin", "/usr/local/*/bin"):
        for d in sorted(_glob.glob(pattern)):
            if d in seen or len(out) >= max_dirs:
                continue
            seen.add(d)
            try:
                names = sorted(
                    e.name for e in os.scandir(d)
                    if e.is_file() and os.access(e.path, os.X_OK))
            except OSError:
                continue
            if names:
                out[_mask_home(d)] = names[:max_each]
    return out


def _capture_memory_system() -> dict:
    """Page-size and NUMA state, because it can dominate a measurement.

    Measured 2026-08-03: the same stencil source ran 1375 ms or 232 ms -- 5.9x --
    according to one environment variable, read only by a vendor large-page
    library that only that vendor's builds link. None of this appears in
    `module avail`, `lscpu`, or the compiler version strings, and an experiment
    that does not record it is reporting a function of site configuration.
    These are machine facts, not secrets, so values are safe to report here.
    """
    out: dict = {}
    try:
        thp = Path("/sys/kernel/mm/transparent_hugepage/enabled")
        out["transparent_hugepage"] = thp.read_text().strip() if thp.is_file() else None
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            for line in meminfo.read_text().splitlines():
                for key in ("HugePages_Total", "Hugepagesize", "AnonHugePages"):
                    if line.startswith(key + ":"):
                        out[key.lower()] = line.split(":", 1)[1].strip()
        nb = Path("/proc/sys/kernel/numa_balancing")
        out["numa_balancing"] = nb.read_text().strip() if nb.is_file() else None
        import glob as _glob
        libs = _glob.glob("/opt/*/mmm/lib64/libmpg.so*") + _glob.glob(
            "/opt/*/lib*/libhugetlbfs.so*")
        out["large_page_library"] = _mask_home(libs[0]) if libs else None
    except Exception:
        pass
    return out


# ── Node-aware heterogeneous environment catalog (multi-node HPC) ───────────
# ARI probes DIFFERENT things depending on where it was started:
#   - login node  : recursively srun-probe each partition in ARI_PROBE_PARTITIONS
#                   (one node per partition — heterogeneity is per-partition), so
#                   the agent sees the WHOLE cluster's toolchains up front.
#   - compute node: report ONLY the local node's env (we are already inside the
#                   allocation; the other partitions are irrelevant to this job).
#   - local/laptop: same as compute (single-node).
# Cluster-agnostic by design (cf. paper-re bridge): the probe dumps raw
# `module avail` / `nvidia-smi` output as DATA — no compiler/module name is ever
# hardcoded here — so ARI carries no cluster-specific toolchain knowledge.

# Toolchain env vars whose PRESENCE we report (names only, never values). The
# probe emits only which of THESE are set — so no secret NAME is ever surfaced
# (a full listing would reveal *_API_KEY etc.) and no VALUE is ever surfaced (a
# value dump would leak API keys + usernames embedded in PATH/LD_LIBRARY_PATH).
# The agent `echo $VAR`s on demand for the specific ones it needs; the value
# then appears only in that node's trace, not in the up-front catalog.
_ENV_ALLOWLIST = (
    "PATH", "LD_LIBRARY_PATH", "LIBRARY_PATH", "CPATH", "MODULEPATH",
    "LOADEDMODULES", "CUDA_HOME", "CUDA_PATH", "CUDA_VISIBLE_DEVICES",
    "NVHPC_ROOT", "CC", "CXX", "FC", "F77", "F90",
    "OMP_NUM_THREADS", "OMP_PLACES", "OMP_PROC_BIND",
    "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MPI_HOME",
    # Vendor memory/runtime controls. Presence only, like everything here; the
    # harness records the VALUE separately into its own manifest, because a
    # measurement has to be reproducible and one of these was measured moving a
    # kernel 5.9x.
    "XOS_MMM_L_PAGING_POLICY", "XOS_MMM_L_HPAGE_TYPE", "FLIB_HUGETLB",
)

# One portable probe script, run either locally or on a partition via srun. Emits
# delimited sections to stdout (avoids fragile JSON-escaping of `module avail`).
_PROBE_SCRIPT = r"""
echo '###ARCH###'; uname -m 2>/dev/null
echo '###CPU###'; lscpu 2>/dev/null | awk -F: '/Model name/{sub(/^ +/,"",$2);print $2;exit}'
echo '###THREADS###'; nproc 2>/dev/null
echo '###MEM_KB###'; awk '/MemTotal/{print $2;exit}' /proc/meminfo 2>/dev/null
echo '###CPU_DETAIL###'
# full lscpu: sockets, cores/socket, threads/core, L1/L2/L3 cache, NUMA node
# CPU mapping, CPU max MHz, and the flags line (AVX-512/SVE/FMA/... ISA support)
lscpu 2>/dev/null
echo '###NUMA###'
# NUMA topology + per-node memory + inter-node distances
(numactl --hardware 2>/dev/null || echo '(numactl unavailable — see NUMA lines in CPU_DETAIL)')
echo '###MEM_DETAIL###'
awk '/^(MemTotal|MemAvailable|HugePages_Total|Hugepagesize)/{print}' /proc/meminfo 2>/dev/null
echo '###COMPILERS###'
for t in gcc g++ gfortran nvcc mpicc mpicxx icc icx clang; do
  command -v "$t" >/dev/null 2>&1 && printf '%s: %s\n' "$t" "$($t --version 2>&1 | head -1)"
done
echo '###GPU###'; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null
echo '###ENV_PRESENT###'
# names ONLY of set toolchain vars — never the value (would leak keys/usernames)
for v in __ENV_ALLOWLIST__; do eval "_val=\${$v:-}"; [ -n "$_val" ] && echo "$v"; done
echo '###MODULES###'
# TWO-TIER MODULE TREES. A single `module avail` lists only what the CURRENT
# MODULEPATH exposes. On a hierarchical setup the top level is a set of entry
# modules and the real toolchains only appear in MODULEPATH once one of them is
# loaded, so a flat listing can show no compiler at all while several are
# installed. `module spider` would flatten it in one call but is Lmod-only and
# absent on Tcl Environment Modules, which is what this site runs.
#
# So: list the top level, then load each entry candidate IN A SUBSHELL and list
# again, reporting only what is NEW. The subshell matters — loading modules for
# real would change the compilers seen by everything that runs afterwards, and
# this probe must not have side effects on the node it is describing.
(
  module avail 2>&1 || echo '(no module system)'
)
if command -v module >/dev/null 2>&1 || type module >/dev/null 2>&1; then
  # Exclude Environment Modules' OWN pseudo-modules. These are package
  # internals with fixed upstream names, not site names, so naming them here
  # carries no site information; loading them reveals nothing and each one
  # otherwise emits an empty section.
  _skip='^(dot|null|modules|module-info|module-git|use\.own)$'
  # `Key:` and friends are the avail legend, not module names.
  _legend='^(Key|Loading|Where|Default|Module|Aliases|Versions)[:.]?$|^-+$'
  _top=$(module avail 2>&1 | tr ' ' '\n' \
         | grep -E '^[A-Za-z][A-Za-z0-9_.+-]*(/[A-Za-z0-9_.+-]+)?$' \
         | grep -vE "$_skip" | grep -vE "$_legend" | sort -u | head -40)
  _base=$(module avail 2>&1 | tr ' ' '\n' | sort -u)
  for _m in $_top; do
    _new=$( (module load "$_m" >/dev/null 2>&1 && module avail 2>&1) \
            | tr ' ' '\n' | sort -u | comm -13 <(echo "$_base") - 2>/dev/null \
            | grep -E '^[A-Za-z]' | grep -vE "$_legend" | head -25 )
    if [ -n "$_new" ]; then
      echo "--- after: module load $_m ---"
      echo "$_new" | tr '\n' ' '
      echo
    fi
  done
fi
echo '###END###'
""".replace("__ENV_ALLOWLIST__", " ".join(_ENV_ALLOWLIST))

# ── Cache geometry, MEASURED, because this target does not report it ────────
# On the scoring machine every standard source is empty: `lscpu` prints
# "unknown size" for L1d/L1i/L2, the sysfs `size` files are blank, and getconf
# returns 0 for every level. sysfs is also actively MISLEADING - it lists the L2
# as shared by all 48 CPUs when the part has one L2 per 12-core cluster.
#
# That matters because sizing a blocking factor to a cache is basic HPC work and
# it cannot be done against a capacity the OS will not disclose. In the previous
# campaign not one of the 87 highest-scoring GEMM candidates carried a blocking
# constant, which is consistent with having nothing to size one against.
#
# So it is measured instead of assumed: a pointer chase over growing working
# sets, whose latency is flat inside a level and steps up at each capacity
# boundary. Pointer chasing rather than strided reads, or the prefetcher hides
# the miss and the steps vanish. Measured this way the target shows 64 KiB of
# L1D and an L2 knee before 8 MiB, matching the published part - but nothing
# architecture-specific is hardcoded here, so it stays correct on another
# machine.
_CACHE_PROBE_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
  return (double)t.tv_sec+(double)t.tv_nsec*1e-9;}
int main(void){
  long line = 128;
#ifdef _SC_LEVEL1_DCACHE_LINESIZE
  long l = sysconf(_SC_LEVEL1_DCACHE_LINESIZE); if (l > 0) line = l;
#endif
  for (long kib = 8; kib <= 32768; kib *= 2) {
    long bytes = kib * 1024, n = bytes / line;
    if (n < 8) continue;
    char *buf = aligned_alloc(4096, (size_t)bytes);
    if (!buf) break;
    memset(buf, 0, (size_t)bytes);
    long *idx = malloc(sizeof(long) * n);
    if (!idx) { free(buf); break; }
    for (long i = 0; i < n; ++i) idx[i] = i;
    for (long i = n - 1; i > 0; --i) {
      long j = (long)((i * 1103515245L + 12345L) % (i + 1));
      long t = idx[i]; idx[i] = idx[j]; idx[j] = t; }
    for (long i = 0; i < n; ++i)
      *(void **)(buf + idx[i] * line) = buf + idx[(i + 1) % n] * line;
    long iters = 12L * n; if (iters < 120000L) iters = 120000L;
    if (iters > 3000000L) iters = 3000000L;
    static void *volatile sink;          /* or the loop is dead code */
    void *p = buf;
    for (long i = 0; i < n; ++i) p = *(void **)p;
    double t0 = now();
    for (long i = 0; i < iters; ++i) p = *(void **)p;
    double dt = now() - t0;
    sink = p;
    printf("%ld %.2f\n", kib, dt / (double)iters * 1e9);
    free(idx); free(buf);
  }
  return 0;}
"""


def measure_cache_geometry(timeout_s: float = 60.0) -> dict:
    """Return {'line_bytes', 'levels': [{'kib', 'ns'}...], 'l1d_kib', 'llc_kib'}.

    Best effort: returns {} when no compiler is available or anything fails. A
    missing measurement must degrade the catalogue, never break the probe.
    """
    import shutil
    import subprocess
    import tempfile

    cc = os.environ.get("ARI_PROBE_CC") or shutil.which("cc") or shutil.which("gcc")
    if not cc:
        return {}
    try:
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "cg.c")
            with open(src, "w") as fh:
                fh.write("#include <unistd.h>\n" + _CACHE_PROBE_C)
            exe = os.path.join(td, "cg")
            cp = subprocess.run([cc, "-O2", src, "-o", exe],
                                capture_output=True, text=True, timeout=timeout_s)
            if cp.returncode != 0:
                return {}
            env = dict(os.environ)
            env["OMP_NUM_THREADS"] = "1"
            r = subprocess.run([exe], capture_output=True, text=True,
                               timeout=timeout_s, env=env)
            rows = []
            for line in (r.stdout or "").splitlines():
                parts = line.split()
                if len(parts) == 2:
                    try:
                        rows.append({"kib": int(parts[0]), "ns": float(parts[1])})
                    except ValueError:
                        pass
    except Exception:
        return {}
    if len(rows) < 4:
        return {}

    out: dict = {"levels": rows}
    # os.sysconf has no cache names on this platform, but getconf does answer
    # for the LINE SIZE even where it returns 0 for every capacity - so the one
    # cache number the OS will give up is still worth taking.
    try:
        _lr = subprocess.run(["getconf", "LEVEL1_DCACHE_LINESIZE"],
                             capture_output=True, text=True, timeout=5)
        _lb = int((_lr.stdout or "0").strip() or 0)
        if _lb > 0:
            out["line_bytes"] = _lb
    except Exception:
        pass
    # A level boundary is the last size before latency rises by half again.
    knees = []
    for a, b in zip(rows, rows[1:]):
        if a["ns"] > 0 and b["ns"] > a["ns"] * 1.5:
            knees.append(a["kib"])
    if knees:
        out["l1d_kib"] = knees[0]
        out["llc_kib"] = knees[-1]
    out["knees_kib"] = knees
    return out



def detect_node_role() -> str:
    """Where is ARI running? -> 'login' | 'compute' | 'local'.

    - ``compute``: inside a SLURM allocation (``SLURM_JOB_ID`` set) — report only
      this node.
    - ``login``: SLURM tools present but NOT inside an allocation — recursively
      probe the configured partitions.
    - ``local``: no SLURM (laptop / bare host) — report only this node.
    """
    import shutil
    if os.environ.get("SLURM_JOB_ID", "").strip() or os.environ.get(
        "SLURM_JOB_PARTITION", "").strip():
        return "compute"
    if shutil.which("srun") or shutil.which("sinfo"):
        return "login"
    return "local"


def _mask_home(s: str) -> str:
    """Collapse the invoking user's home directory to ``~`` so the env catalog
    never leaks a username. The same home is reachable under more than one mount
    (e.g. ``/home/users/<u>/...`` and a work-filesystem mirror), so we mask both
    the resolved ``$HOME`` prefixes AND any absolute path segment ending in the
    username. Cluster-agnostic: everything is derived from ``$HOME`` / ``$USER``
    at runtime — no path or name is hardcoded."""
    if not s or "/" not in s:
        return s
    home = os.environ.get("HOME") or os.path.expanduser("~")
    # 1) exact home dir (raw + symlink-resolved), longest first
    cands: set[str] = set()
    if home and home not in ("/", ""):
        cands.add(home.rstrip("/"))
        try:
            cands.add(os.path.realpath(home).rstrip("/"))
        except OSError:
            pass
    for h in sorted((c for c in cands if c), key=len, reverse=True):
        s = s.replace(h, "~")
    # 2) any other mount of the same home: a path ending in ``/<user>``
    user = os.environ.get("USER") or (Path(home).name if home else "")
    if user and len(user) >= 2:
        s = re.sub(r"/[\w./-]*?/" + re.escape(user) + r"(?=/|$|\b)", "~", s)
    return s


def _mask_home_deep(obj: Any) -> Any:
    """Recursively apply :func:`_mask_home` to every string in a catalog value."""
    if isinstance(obj, str):
        return _mask_home(obj)
    if isinstance(obj, dict):
        return {k: _mask_home_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_home_deep(v) for v in obj]
    return obj


def _squeeze(s: str) -> str:
    """Strip layout padding from a RAW DIAGNOSTIC DUMP (lscpu / numactl / free /
    module avail): drop blank lines, drop trailing spaces, and collapse runs of
    2+ spaces to one. Measured: ~22% off the catalog's string payload (lscpu
    alone is column-padded to ~26 spaces per label).

    Only ever apply this to those dumps. Runs of 2+ spaces are pure column
    alignment there, and single spaces — which separate the ISA tokens on the
    lscpu ``Flags:`` line the agent reads for AVX-512 — are preserved. It must
    NOT be used on ``run_bash`` output, where leading indentation and column
    position ARE meaning (a gcc ``^~~~`` caret stops pointing at the offending
    token; source echoed via ``sed``/``cat`` loses its structure).

    Applied BEFORE the size caps below, so more real content survives the cap.
    """
    if not s:
        return s
    lines = [ln.rstrip() for ln in s.splitlines() if ln.strip()]
    return re.sub(r"[ \t]{2,}", " ", "\n".join(lines))


def _parse_probe_output(text: str) -> dict:
    """Parse the delimited ``_PROBE_SCRIPT`` stdout into a structured env dict."""
    if not text or "###END###" not in text:
        return {}
    sections: dict[str, list[str]] = {}
    cur: str | None = None
    for line in text.splitlines():
        m = re.match(r"^###(\w+)###$", line.strip())
        if m:
            cur = m.group(1)
            if cur != "END":
                sections[cur] = []
            continue
        if cur and cur != "END":
            sections[cur].append(line)

    def _first(name: str) -> str:
        return (sections.get(name) or [""])[0].strip()

    env: dict[str, Any] = {}
    if _first("ARCH"):
        env["arch"] = _first("ARCH")
    if _first("CPU"):
        env["cpu_model"] = _first("CPU")
    try:
        env["threads"] = int(_first("THREADS"))
    except ValueError:
        pass
    try:
        env["mem_total_kb"] = int(_first("MEM_KB"))
    except ValueError:
        pass
    # Rich detail (raw): full lscpu (sockets/cores/cache/flags/ISA/MHz + NUMA
    # CPU map), NUMA topology + per-node memory, and memory breakdown. Kept raw
    # + capped so the agent has the fine-grained specs without brittle parsing.
    _detail = _squeeze("\n".join(sections.get("CPU_DETAIL", [])).strip())
    if _detail:
        env["cpu_detail"] = _detail[:4000]
    _numa = _squeeze("\n".join(sections.get("NUMA", [])).strip())
    if _numa:
        env["numa"] = _numa[:2000]
    _memd = _squeeze("\n".join(sections.get("MEM_DETAIL", [])).strip())
    if _memd:
        env["mem_detail"] = _memd[:1000]
    comps: dict[str, str] = {}
    for ln in sections.get("COMPILERS", []):
        if ":" in ln:
            k, _, v = ln.partition(":")
            if k.strip():
                comps[k.strip()] = v.strip()
    if comps:
        env["compilers"] = comps
    gpus = [g.strip() for g in sections.get("GPU", []) if g.strip()]
    if gpus:
        env["gpus"] = gpus
    # PRESENCE-only toolchain env vars (names, no values). The agent echoes the
    # specific ones it needs; values never enter the up-front catalog.
    present = [v.strip() for v in sections.get("ENV_PRESENT", []) if v.strip()]
    if present:
        env["env_present"] = present
    mod = _squeeze("\n".join(sections.get("MODULES", [])).strip())
    if mod:
        # Cap to keep the injected catalog bounded; the agent re-runs
        # `module avail` on the actual compute node for the authoritative list.
        # Raised for the second tier: on a hierarchical tree the "after: module
        # load X" sections are where the compilers actually are, and at 8000 they
        # were the part that got cut — which left the catalog listing entry
        # modules and no toolchain, the exact failure the recursion fixes.
        env["modules_avail"] = mod[:24000]
    # Strip any username-bearing home path (e.g. a broken conda mpicc wrapper
    # echoes its full ~/miniconda/bin path) before the env reaches the agent.
    return _mask_home_deep(env)


def local_env() -> dict:
    """Probe ONLY the local node (compute / local role). Best-effort."""
    try:
        proc = subprocess.run(
            ["bash", "-c", _PROBE_SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        env = _parse_probe_output(proc.stdout)
    except Exception:
        return {}
    # Cache capacities, measured, because this target reports none. Rendered as
    # a short human-readable line rather than raw rows: the agent needs "how big
    # is L1 / the last level" to size a blocking factor, not a latency table.
    # Off via ARI_PROBE_CACHE=0; a failure just omits the key.
    if os.environ.get("ARI_PROBE_CACHE", "1") not in ("0", "false", "False"):
        try:
            g = measure_cache_geometry()
        except Exception:
            g = {}
        if g:
            bits = []
            if g.get("line_bytes"):
                bits.append(f"line {g['line_bytes']} B")
            if g.get("l1d_kib"):
                bits.append(f"L1d ~{g['l1d_kib']} KiB")
            if g.get("llc_kib") and g.get("llc_kib") != g.get("l1d_kib"):
                bits.append(f"last level ~{g['llc_kib']} KiB")
            if g.get("knees_kib"):
                bits.append("capacity steps at "
                            + ", ".join(f"{k} KiB" for k in g["knees_kib"]))
            if bits:
                # Say WHY it is measured only when it is actually true here.
                # The scoring target reports nothing, but the login node's sysfs
                # does have the sizes, and asserting otherwise there would be a
                # false statement in the agent's own catalogue.
                _os_silent = True
                try:
                    _sz = pathlib.Path(
                        "/sys/devices/system/cpu/cpu0/cache/index0/size")
                    _os_silent = not (_sz.is_file() and _sz.read_text().strip())
                except Exception:
                    pass
                env["cache_measured"] = "; ".join(bits) + (
                    "  (measured by pointer chase; this machine's lscpu, sysfs and"
                    " getconf all report the capacities as unknown)"
                    if _os_silent else "  (measured by pointer chase)")
    return env


def probe_partition_env(partition: str, timeout_s: int) -> dict | None:
    """srun the probe on ONE node of ``partition`` (login role). Best-effort.

    Returns the parsed env dict, or None when the partition is unreachable /
    the queue wait exceeds ``timeout_s`` (caller records it as skipped). The
    srun run-limit is fixed short (the probe is a few seconds); ``timeout_s``
    governs how long we wait in the queue before giving up.
    """
    try:
        proc = subprocess.run(
            ["srun", "-p", partition, "-N", "1", "-n", "1", "-t", "00:02:00",
             "bash", "-c", _PROBE_SCRIPT],
            capture_output=True, text=True, timeout=max(10, timeout_s),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if "###END###" not in (proc.stdout or ""):
        return None
    parsed = _parse_probe_output(proc.stdout)
    return parsed or None


def build_env_catalog(checkpoint_dir: Path | str | None = None) -> dict:
    """Node-aware environment catalog. Behaviour depends on the launch node:

    - login   -> ALWAYS this login node's own env (the agent may compile/run
      here directly), PLUS an srun-probe of each partition in
      ``ARI_PROBE_PARTITIONS`` (per-partition, so a fully HETEROGENEOUS cluster
      is captured), waiting at most ``ARI_PROBE_TIMEOUT_S`` seconds per
      partition. Cached to ``<checkpoint>/heterogeneous_env.json``.
    - compute -> ONLY this node's env (we are already inside the allocation).
    - local   -> ONLY this node's env.

    Returns ``{"role", "nodes": {label: env}, ...}``; never raises.
    """
    role = detect_node_role()
    if role in ("compute", "local"):
        _label = os.environ.get("SLURM_JOB_PARTITION", "").strip() or "local"
        return {"role": role, "nodes": {_label: local_env()}}

    # login: probe each configured partition (one node each).
    parts = [p.strip() for p in os.environ.get(
        "ARI_PROBE_PARTITIONS", "").split(",") if p.strip()]
    try:
        timeout_s = int(os.environ.get("ARI_PROBE_TIMEOUT_S", "120"))
    except ValueError:
        timeout_s = 120

    cache_path: Path | None = None
    if checkpoint_dir is not None:
        cache_path = Path(checkpoint_dir) / "heterogeneous_env.json"
        if cache_path.is_file():
            try:
                return json.loads(cache_path.read_text())
            except (OSError, json.JSONDecodeError):
                pass

    # ALWAYS report the login node's own env first: it is a real execution
    # target (the agent may build/run here rather than submit to a partition),
    # so a login run with no configured partitions still returns a useful
    # catalog instead of an empty one. Hostname is never captured, so no leak.
    nodes: dict[str, Any] = {"local (login node)": local_env()}
    for part in parts:
        env = probe_partition_env(part, timeout_s)
        nodes[part] = env if env is not None else {
            "status": "skipped (unreachable or queue wait > "
                      f"ARI_PROBE_TIMEOUT_S={timeout_s}s)"
        }
    catalog = {
        "role": "login",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "probed_partitions": parts,
        "probe_timeout_s": timeout_s,
        "nodes": nodes,
    }
    # Cache only a catalog whose every node was really probed. A node that came
    # back as ``status: skipped`` is a TRANSIENT failure (queue wait / busy), and
    # the read path above returns the cache verbatim with no TTL — persisting a
    # placeholder would keep that partition "dead" for the rest of the run. Note
    # the cache saves the probe (an srun per partition), not the payload: the
    # tool returns the same catalog either way.
    _all_probed = all(
        not (isinstance(_e, dict) and _e.get("status")) for _e in nodes.values()
    )
    if cache_path is not None and _all_probed:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
        except Exception:
            pass
    return catalog


def shell_capture_snippet(
    *,
    executor: str = "slurm",
) -> str:
    """Return a portable bash snippet that writes `_run_env.json` in $PWD.

    Used at the *top* of an sbatch script — runs on the compute node, captures
    that node's environment (not the submitting agent's). The snippet writes
    JSON via a heredoc; it never errors-out the surrounding script (errors are
    silently swallowed via `|| true`).
    """
    return rf"""
# ── ari run-env capture (auto-injected) ────────────────────────────────────
{{
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  hn="$(hostname 2>/dev/null || echo unknown)"
  jid="${{SLURM_JOB_ID:-}}"
  part="${{SLURM_JOB_PARTITION:-}}"
  nodelist="${{SLURM_JOB_NODELIST:-}}"
  cpu_model="$(lscpu 2>/dev/null | awk -F: '/^Model name/{{sub(/^ +/,"",$2); print $2; exit}}')"
  cpu_threads="$(lscpu 2>/dev/null | awk -F: '/^CPU\(s\)/{{print $2; exit}}' | tr -d ' ')"
  cpu_mhz="$(lscpu 2>/dev/null | awk -F: '/^CPU max MHz/{{print $2; exit}}' | tr -d ' ')"
  cpu_arch="$(lscpu 2>/dev/null | awk -F: '/^Architecture/{{print $2; exit}}' | tr -d ' ')"
  mem_kb="$(awk '/MemTotal/{{print $2; exit}}' /proc/meminfo 2>/dev/null)"
  gxx_v="$(g++ --version 2>/dev/null | head -1)"
  py_v="$(python3 --version 2>/dev/null)"
  cat > _run_env.json <<JSON_EOF
{{
  "captured_at": "$ts",
  "executor": "{executor}",
  "hostname": "$hn",
  "slurm_job_id": "$jid",
  "slurm_partition": "$part",
  "slurm_nodelist": "$nodelist",
  "cpu_info": {{
    "model": "$cpu_model",
    "threads": ${{cpu_threads:-0}},
    "mhz": ${{cpu_mhz:-0}},
    "arch": "$cpu_arch"
  }},
  "mem_total_kb": ${{mem_kb:-0}},
  "compilers": {{
    "g++": "$gxx_v",
    "python3": "$py_v"
  }}
}}
JSON_EOF
}} 2>/dev/null || true
# ── end run-env capture ───────────────────────────────────────────────────
"""
