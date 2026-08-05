"""Absolute GF/s for EVERY run in a campaign, not just for the reference.

THE REVIEW POINT THIS ANSWERS. KATAGIRI asked whether the code is actually
performing. `measure_absolute_performance.py` answers that for one source you
hand it -- which in practice meant the frozen reference, because that is the
denominator every score is quoted against. It cannot answer the question the
campaign is actually about: how fast is the code the AGENTS produced, per arm.

WHY THIS NEEDS ITS OWN TOOL. The aggregate a run persists is `speedup`, a ratio,
and `final_measurement.json`'s `evaluation_cases[*].measurements` keeps only
that. The absolute times survive one level down, in
`measurement_audit.cases[shape][*].measurements.candidate_credited_seconds`
(and `reference_internal_seconds` beside it), so GF/s is recoverable but nobody
was recovering it. A ratio of 0.86 is compatible with 300 GF/s and with 3 GF/s.

FLOP COUNTS. gemm is 2*n*m*p and the 7-point stencil is 8 flops per interior
point per sweep, both derivable from the family name. SpMM is NOT: its flop
count is 2*nnz*k and nnz depends on the generated matrix, which the family name
("banded", "power_law", ...) does not carry. SpMM rows therefore report time
only, and say so, rather than guessing an nnz.

TWO DENOMINATORS, both measured on this machine (see measure_fma_ceiling.c and
measure_clock.c): the FMA ceiling a hand-written SVE-intrinsic loop reaches, and
the architectural peak. The contract forbids intrinsics, so the ceiling is the
honest bound for anything an agent can write, and the peak is context.

USAGE
    python aggregate_flops.py                       # everything under workspace/experiments
    python aggregate_flops.py --root <matrix_root>  # one campaign's shards
    python aggregate_flops.py --by arm --out DIR
"""
import argparse
import glob
import json
import pathlib
import re
import statistics

REPO = pathlib.Path(__file__).resolve().parents[2]

_RUN_DIR = re.compile(r"^(\d{14})_(gemm|spmm|stencil)_([a-z_]+)_seed(\d+)$")


def _case_flops(task: str, name: str) -> float | None:
    """Flops for a scored case, from its family name; None when not derivable."""
    try:
        if task == "gemm":
            n, m, p = (int(x) for x in name.split("x"))
            return 2.0 * n * m * p
        if task == "stencil":
            dims, _, nt = name.partition("t")
            nx, ny, nz = (int(x) for x in dims.split("x"))
            return 8.0 * (nx - 2) * (ny - 2) * (nz - 2) * int(nt)
    except Exception:
        return None
    return None  # spmm: nnz is not in the family name


def _iter_runs(root: pathlib.Path):
    """Yield (task, arm, seed, final_measurement dict) for every run under root."""
    for path in sorted(root.glob("*/final_measurement.json")):
        m = _RUN_DIR.match(path.parent.name)
        if not m:
            continue
        try:
            yield m.group(2), m.group(3), int(m.group(4)), json.loads(path.read_text())
        except Exception:
            continue
    # A campaign root holds SHARDS, not runs: each shard keeps a manifest whose
    # `run_dir` points back into workspace/experiments. Globbing under the root
    # for final_measurement.json therefore finds nothing, which is silent and
    # reads exactly like "this campaign produced no data".
    for man in sorted(root.glob("shards/*/*/seed_*/manifest.jsonl")):
        for line in man.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                fm = (rec.get("final_measurement") or {}).get("path")
                if not fm:
                    fm = str(pathlib.Path(rec["run_dir"]) / "final_measurement.json")
                yield (rec["task"], rec["arm"], int(rec.get("seed", 0)),
                       json.loads(pathlib.Path(fm).read_text()))
            except Exception:
                continue


def _rows(task: str, arm: str, seed: int, doc: dict, ceiling: float, peak: float):
    audit = (doc.get("measurement_audit") or {}).get("cases") or {}
    for name in sorted(audit):
        cand, ref = [], []
        for rec in audit[name] or []:
            meas = rec.get("measurements") or {}
            c = meas.get("candidate_credited_seconds")
            r = meas.get("reference_internal_seconds")
            if isinstance(c, (int, float)) and c > 0:
                cand.append(c)
            if isinstance(r, (int, float)) and r > 0:
                ref.append(r)
        if not cand:
            continue
        fl = _case_flops(task, name)
        tc = statistics.median(cand)
        tr = statistics.median(ref) if ref else None
        row = {"task": task, "arm": arm, "seed": seed, "case": name,
               "candidate_ms": tc * 1e3,
               "reference_ms": tr * 1e3 if tr else None,
               "n_reps": len(cand)}
        if fl is not None:
            row["candidate_gflops"] = fl / tc * 1e-9
            row["frac_ceiling"] = row["candidate_gflops"] / ceiling
            row["frac_peak"] = row["candidate_gflops"] / peak
            if tr:
                row["reference_gflops"] = fl / tr * 1e-9
        yield row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None,
                    help="campaign root or an experiments dir "
                         "(default workspace/experiments)")
    ap.add_argument("--by", default="arm", choices=("arm", "case", "run"),
                    help="aggregation level for the summary")
    ap.add_argument("--ceiling-gfs", type=float, default=2534.0,
                    help="measured FMA ceiling; re-measure with measure_fma_ceiling.c")
    ap.add_argument("--peak-gfs", type=float, default=3070.0,
                    help="cores x clock x lanes x 2 flop x 2 FMA pipes, clock MEASURED")
    ap.add_argument("--latex", action="store_true",
                    help="also emit table rows for the manuscript")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.root) if args.root else (REPO / "workspace/experiments")
    if not root.is_dir():
        print(f"no such directory: {root}")
        return 1

    rows = []
    for task, arm, seed, doc in _iter_runs(root):
        rows.extend(_rows(task, arm, seed, doc, args.ceiling_gfs, args.peak_gfs))
    if not rows:
        print(f"no runs with a measurement_audit under {root}")
        return 1

    print(f"root = {root}")
    print(f"measured FMA ceiling {args.ceiling_gfs:.0f} GF/s   "
          f"architectural peak {args.peak_gfs:.0f} GF/s "
          f"({args.ceiling_gfs / args.peak_gfs * 100:.1f}% of peak)")
    print(f"{len(rows)} scored cases from "
          f"{len({(r['task'], r['arm'], r['seed']) for r in rows})} runs")
    print()

    keyfn = {"arm": lambda r: (r["task"], r["arm"]),
             "case": lambda r: (r["task"], r["case"]),
             "run": lambda r: (r["task"], r["arm"], r["seed"])}[args.by]

    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(keyfn(r), []).append(r)

    head = {"arm": ("task", "arm"), "case": ("task", "case"),
            "run": ("task", "arm/seed")}[args.by]
    print(f"{head[0]:9s} {head[1]:28s} {'n':>4s} {'cand GF/s':>10s} {'ref GF/s':>9s} "
          f"{'of ceiling':>11s} {'of peak':>9s} {'cand ms':>9s}")
    for key in sorted(groups):
        g = groups[key]
        withg = [r for r in g if "candidate_gflops" in r]
        label = "/".join(str(k) for k in key[1:])
        ms = statistics.median(r["candidate_ms"] for r in g)
        if not withg:
            # SpMM: report time, and say why there is no GF/s rather than invent one.
            print(f"{key[0]:9s} {label:28s} {len(g):>4d} {'n/a':>10s} {'n/a':>9s} "
                  f"{'n/a':>11s} {'n/a':>9s} {ms:9.2f}   (nnz not in the family name)")
            continue
        vals = sorted(r["candidate_gflops"] for r in withg)
        cg = statistics.median(vals)
        rg = [r["reference_gflops"] for r in withg if "reference_gflops" in r]
        print(f"{key[0]:9s} {label:28s} {len(g):>4d} {cg:10.1f} "
              f"{(statistics.median(rg) if rg else float('nan')):9.1f} "
              f"{cg / args.ceiling_gfs * 100:10.1f}% {cg / args.peak_gfs * 100:8.1f}% "
              f"{ms:9.2f}   [{vals[0]:.0f}-{vals[-1]:.0f}]")

    print()
    print("A low fraction is not by itself a verdict on the search: the contract")
    print("forbids intrinsics, so what a candidate can reach is bounded by the")
    print("compiler's auto-vectoriser, which on this machine emits few or no SVE")
    print("FMAs. Compare the candidate column against the reference column, which")
    print("is written under the same contract, before reading it as a shortfall.")

    if args.latex:
        # Emit the rows rather than have them retyped: every number the paper
        # states about absolute performance should come from the program that
        # measured it. Transcription is where this manuscript has lost numbers
        # before.
        print()
        print("% generated by workspace/tools/aggregate_flops.py --latex")
        for key in sorted(groups):
            g = [r for r in groups[key] if "candidate_gflops" in r]
            if not g:
                continue
            vals = sorted(r["candidate_gflops"] for r in g)
            med = statistics.median(vals)
            rg = [r["reference_gflops"] for r in g if "reference_gflops" in r]
            label = "/".join(str(k) for k in key[1:]).replace("_", "\\_")
            print(f"\\texttt{{{key[0]}}} & {label} & {len(g)} & "
                  f"{med:.0f} & {vals[0]:.0f}--{vals[-1]:.0f} & "
                  f"{(statistics.median(rg) if rg else float('nan')):.0f} & "
                  f"{med / args.ceiling_gfs * 100:.1f}\\,\\% \\\\")

    out_dir = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/flops_aggregate")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "flops_aggregate.json"
    dst.write_text(json.dumps(
        {"root": str(root), "ceiling_gfs": args.ceiling_gfs,
         "peak_gfs": args.peak_gfs, "rows": rows}, indent=1))
    print(f"\nwrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
