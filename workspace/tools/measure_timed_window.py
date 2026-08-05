"""WHERE inside the timed window does a task's measurement noise live?

THE REVIEW POINT THIS ANSWERS. KATAGIRI asked for problem settings whose results
do not wander. `measure_resolution_band.py` says HOW WIDE the band is; it cannot
say WHICH PART of the measurement is wide, and without that the only available
remedy is "raise the rep count", which does not help when the noisy component is
a fixed cost that the median cannot average away.

WHAT IT DOES. It builds the SCORED binary — the harness's own `<task>_main.c`
plus the frozen reference kernel, through the harness's own `_compile_kernel`,
so the flags cannot drift from the scored ones — and runs it directly against a
real problem file, reading the same internal timer (`timing.bin`) the harness
credits. That timer excludes the problem read, the output write and process
spawn, so anything it sees is inside the kernel call.

Varying the stencil's sweep count separates the two components:

    t(nt) = a + b * nt        a = allocation + first touch (FIXED)
                              b = cost of one sweep

and running many processes at a SMALL nt, where the sweeps are a couple of
percent of the measurement, isolates `a`'s own spread. On this machine that is
what the stencil's band turned out to be: per-sweep cost reproduces to 0.03%
from nt=1 to nt=240, while at nt=1 the 100-process range is 33.9-52.0 ms, a 34%
spread in the fixed term alone.

WHY NOT A RE-IMPLEMENTATION. A standalone program replicating the reference's
allocation, first touch and sweeps failed to reproduce the effect in 50
processes across two versions, and that failure was misread as a refutation. It
was not: the scored driver already holds 268 MB (`u0` read from the problem
file, `u` filled with NaN) when the kernel allocates 268 MB more, and the cost
of allocation and first touch depends on the process's existing footprint. A
probe that does not reproduce the context does not refute anything. Hence this
tool runs the real binary and never re-implements it.

USAGE
    python measure_timed_window.py --task stencil --nt 1,30,120,240 --reps 20
    python measure_timed_window.py --task stencil --nt 1 --reps 100   # isolate `a`
"""
import argparse
import json
import os
import pathlib
import statistics
import struct
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]


def _harness(task: str):
    sys.path.insert(0, str(REPO / "ari-core"))
    sys.path.insert(0, str(REPO / "workspace/harnesses" / task))
    os.environ.setdefault("ARI_WORKSPACE", str(REPO / "workspace"))
    return __import__(f"{task}_harness")


def _write_problem(path: pathlib.Path, H, nx: int, ny: int, nz: int, nt: int, seed: int):
    """The problem file the scored driver reads: 4 ints then nx*ny*nz doubles."""
    import numpy as np
    u0 = H.gen_problem((nx, ny, nz, nt), seed=seed)[0]
    with path.open("wb") as fh:
        fh.write(struct.pack("4i", nx, ny, nz, nt))
        fh.write(np.ascontiguousarray(u0, dtype=np.float64).tobytes())


def _fit(points: dict[int, float]) -> tuple[float, float]:
    """Least squares a + b*nt over the medians."""
    xs = sorted(points)
    n = len(xs)
    if n < 2:
        return (points[xs[0]], 0.0) if xs else (0.0, 0.0)
    sx = sum(xs); sy = sum(points[x] for x in xs)
    sxx = sum(x * x for x in xs); sxy = sum(x * points[x] for x in xs)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return (sy - b * sx) / n, b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="stencil", choices=("stencil",),
                    help="only stencil has a sweep count to vary")
    ap.add_argument("--shape", default="256,256,256",
                    help="nx,ny,nz; the scored grid by default")
    ap.add_argument("--nt", default="1,30,120,240")
    ap.add_argument("--reps", type=int, default=20, help="processes per nt")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    H = _harness(args.task)
    nx, ny, nz = (int(v) for v in args.shape.split(","))
    nts = [int(v) for v in args.nt.split(",")]

    results: dict[int, list[float]] = {}
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        wd = td / "wd"; wd.mkdir()
        H.seed_work_dir(str(wd))
        out_td = td / "build"; out_td.mkdir()
        # The harness's own compile path, so the flags are the scored ones.
        exe = H._compile_kernel("reference", str(wd), str(out_td))
        if isinstance(exe, (tuple, list)):
            exe = exe[0]
        print(f"built {exe}")
        print(f"reference cflags: {' '.join(H._REFERENCE_CFLAGS)}")

        for nt in nts:
            prob = td / f"problem_nt{nt}.bin"
            _write_problem(prob, H, nx, ny, nz, nt, args.seed)
            vals = []
            for _ in range(args.reps):
                r = subprocess.run([str(exe), str(prob), str(td / "u.bin"),
                                    str(td / "t.bin")],
                                   capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    continue
                vals.append(struct.unpack("d", (td / "t.bin").read_bytes()[:8])[0] * 1e3)
            results[nt] = vals
            if vals:
                med = statistics.median(vals)
                dev = sorted(abs(v - med) for v in vals)
                p95 = dev[max(0, int(0.95 * len(dev)) - 1)]
                print(f"  nt={nt:<4d} n={len(vals):<4d} median {med:9.3f} ms  "
                      f"range {min(vals):8.3f}-{max(vals):8.3f}  "
                      f"p95|x-med| {p95 / med * 100:5.2f}%")

    med = {nt: statistics.median(v) for nt, v in results.items() if v}
    a, b = _fit(med)
    print()
    if len(med) >= 2:
        print(f"fit: t = {a:.3f} ms + {b:.4f} ms * nt")
        for nt in sorted(med):
            f = a + b * nt
            print(f"   nt={nt:<4d} measured {med[nt]:9.3f}  fit {f:9.3f}  "
                  f"resid {(med[nt] - f) / med[nt] * 100:+6.2f}%")
        print()
        print("`a` is allocation + parallel first touch INSIDE the timed window;")
        print("`b` is one sweep. Compare the p95 spread at the smallest nt (mostly")
        print("`a`) with the largest (mostly `b`): whichever is wider is the")
        print("component the band is made of, and raising the rep count only helps")
        print("for the one the median can average away.")
    else:
        print("need at least two nt values to separate the fixed term from the sweeps")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/timed_window")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"timed_window_{args.task}.json"
    dst.write_text(json.dumps(
        {"task": args.task, "shape": [nx, ny, nz], "reps": args.reps,
         "samples_ms": {str(k): v for k, v in results.items()},
         "fit_fixed_ms": a, "fit_per_sweep_ms": b}, indent=1))
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
