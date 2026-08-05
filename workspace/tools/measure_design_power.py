"""Can this design detect the effect it is looking for?

THE REVIEW POINT THIS ANSWERS. Three separate objections -- no profiler, no
A64FX-specific optimization essentials, no problem-aligned skill or harness --
all reduce to one measurable claim: the agent has no repeatable optimization
procedure, so each run lands somewhere different, and a handoff-channel effect
would be buried under that. "It isn't an experiment" is a statement about
statistical power, and power is measurable.

WHAT IT MEASURES. The study's estimand is the within-seed paired difference
between arms, so pairing removes seed-level difficulty. It cannot remove
RUN-level variance -- two arms at the same seed are still two independent draws
from whatever process the agent runs. This reports:

  sd(paired difference)   the noise the design must beat
  se at the planned n     sd / sqrt(n)
  MDE                     minimum detectable effect, 2.8*se (two-sided alpha
                          0.05, power 0.8), against the observed effect

If the observed effects sit well inside the MDE, the design cannot answer its
question at the planned sample size, and reporting a null would be reporting the
measurement rather than the phenomenon.

A LARGE sd here is itself the finding, and it is the number that justifies
equipping the agent before comparing channels rather than after.

USAGE
    python measure_design_power.py ROOT
    python measure_design_power.py ROOT --planned-n 30
"""
import argparse
import collections
import json
import math
import pathlib
import statistics

TASKS = ("gemm", "spmm", "stencil")
CONTRASTS = (("code_only", "evidence_only", "E-W"),
             ("evidence_only", "evidence_plus_reflection", "S-E"))
# two-sided alpha 0.05, power 0.8: (1.96 + 0.84) standard errors
_Z = 2.80


def load_cells(root: pathlib.Path) -> dict:
    cells = {}
    for man in root.glob("shards/*/*/seed_*/manifest.jsonl"):
        for line in man.read_text().splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except Exception:
                continue
            fm = m.get("final_measurement") or {}
            if fm.get("status") == "valid":
                cells[(m["task"], m["arm"], m["seed"])] = fm["score"]
    return cells


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--planned-n", type=int, default=30)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    cells = load_cells(root)
    if not cells:
        print(f"no valid cells under {root}")
        return 1

    rows = []
    print(f"root: {root}")
    print(f"valid cells: {len(cells)}   planned n per contrast: {args.planned_n}")
    print()
    print(f"{'task':9s} {'contrast':9s} {'n':>3s} {'effect':>8s} {'sd(diff)':>9s} "
          f"{'se@n':>7s} {'MDE':>7s} {'effect/MDE':>11s}")
    for task in TASKS:
        seeds = sorted({s for (t, _, s) in cells if t == task})
        for lo, hi, label in CONTRASTS:
            d = [cells[(task, hi, s)] - cells[(task, lo, s)] for s in seeds
                 if (task, hi, s) in cells and (task, lo, s) in cells]
            if len(d) < 2:
                print(f"{task:9s} {label:9s} {len(d):>3d}   (too few pairs)")
                continue
            eff = statistics.mean(d)
            sd = statistics.stdev(d)
            se = sd / math.sqrt(args.planned_n)
            mde = _Z * se
            rows.append({"task": task, "contrast": label, "n_pairs": len(d),
                         "effect": eff, "sd_paired": sd, "se_at_planned_n": se,
                         "mde": mde})
            print(f"{task:9s} {label:9s} {len(d):>3d} {eff:+8.3f} {sd:9.3f} "
                  f"{se:7.3f} {mde:7.3f} {abs(eff)/mde:11.2f}")

    print()
    if rows:
        worst = max(rows, key=lambda r: r["mde"] / max(abs(r["effect"]), 1e-9))
        print("An effect/MDE below 1 means the design cannot resolve the effect it")
        print("observes at the planned sample size: a null result would then be a")
        print("statement about the measurement, not about the intervention.")
        print(f"Largest shortfall: {worst['task']}/{worst['contrast']} -- observed "
              f"{worst['effect']:+.3f} against an MDE of {worst['mde']:.3f}.")
        print()
        print("sd(diff) is the quantity to attack. Pairing already removes")
        print("seed-level difficulty, so what remains is run-to-run variance in what")
        print("the agent produces -- which is what profiling feedback, architecture")
        print("specifics, and a problem-aligned procedure exist to reduce.")

    out_dir = pathlib.Path(args.out) if args.out else (
        pathlib.Path(__file__).resolve().parents[2] / "workspace/checkpoints/design_power")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "design_power.json"
    dst.write_text(json.dumps({"root": str(root), "planned_n": args.planned_n,
                               "rows": rows}, indent=1))
    print(f"\nwrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
