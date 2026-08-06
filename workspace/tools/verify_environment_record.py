"""Does the environment record survive a REAL scoring, and does drift get caught?

WHY A COMPUTE NODE. The unit tests call `measurement_environment()` directly and
pin its shape. They cannot show that a real `measure_node()` carries the record
all the way into the result it writes, nor that two scorings taken under
different settings actually produce different digests. Those are the two claims
the design rests on, and both are properties of a run, not of a function.

WHAT IT DOES. Scores the frozen reference twice on the same node -- once with
`XOS_MMM_L_PAGING_POLICY` unset, once set -- writes each full result, then runs
`check_environment_drift.py` over the pair. Three things must hold:

  1. each result carries a measurement_environment with a digest,
  2. the two digests differ, because the conditions differed,
  3. the drift checker reports exactly that, and exits nonzero.

A test suite can assert (1) in the abstract. Only a real scoring shows the record
reaching the file, and only a real pair shows the checker firing on it.

USAGE (from a batch job on a compute node)
    python verify_environment_record.py --task stencil
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
VAR = "XOS_MMM_L_PAGING_POLICY"


def score(task: str, reps: int, out: pathlib.Path) -> dict:
    """One real scoring of the frozen reference, written out whole."""
    # Through the registry: an environment record proved against an unverified
    # harness proves nothing about the harness that scores. See _harness_access.
    os.environ.setdefault("ARI_WORKSPACE", str(REPO / "workspace"))
    sys.path.insert(0, str(REPO / "workspace/tools"))
    from _harness_access import verified_harness
    harness, H = verified_harness(task)
    with tempfile.TemporaryDirectory() as td:
        wd = pathlib.Path(td, "w")
        wd.mkdir()
        H.seed_work_dir(str(wd))
        ref = (pathlib.Path(H.kernels_dir()) / f"reference_{task}.c").read_text()
        (wd / f"candidate_{task}.c").write_text(ref)
        # measure() applies the manifest's [measure_kwargs], so the scored size
        # is not restated here (it used to be, as a literal n=20000/k=64).
        r = harness.measure(str(wd), reps=reps)
    out.write_text(json.dumps(r, indent=1, default=str))
    return r


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="stencil")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    root = pathlib.Path(args.out) if args.out else (
        REPO / "workspace/checkpoints/environment_record_verification")
    failures: list[str] = []

    digests = {}
    for label, value in (("unset", None), ("demand", "demand:demand:demand")):
        d = root / label
        d.mkdir(parents=True, exist_ok=True)
        os.environ.pop(VAR, None)
        if value is not None:
            os.environ[VAR] = value
        r = score(args.task, args.reps, d / "result.json")

        env = r.get("measurement_environment")
        if not isinstance(env, dict) or not env.get("sha256"):
            failures.append(
                f"[{label}] the result carries no environment digest. The "
                f"harness computed one in the unit tests but it is not reaching "
                f"the written result, which is the only copy anyone can audit.")
            print(f"  {label:8s} NO RECORD")
            continue
        digests[label] = env["sha256"]
        seen = env["variables"].get(VAR)
        print(f"  {label:8s} digest {env['sha256'][:16]}  {VAR}={seen!r}")
        if seen != value:
            failures.append(
                f"[{label}] {VAR} was {value!r} during the scoring but the "
                f"record says {seen!r}. A record that does not match the "
                f"conditions is worse than no record.")

    os.environ.pop(VAR, None)

    if len(digests) == 2 and digests["unset"] == digests["demand"]:
        failures.append(
            f"the two scorings ran under different settings of {VAR} -- the "
            f"variable measured at 5.9x on this task -- and produced the SAME "
            f"digest. Equal digests are what licenses comparing two runs, so "
            f"this one would license a comparison that is not valid.")

    print()
    checker = REPO / "workspace/tools/check_environment_drift.py"
    proc = subprocess.run([sys.executable, str(checker), str(root)],
                          capture_output=True, text=True)
    print(proc.stdout, end="")
    print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 1:
        failures.append(
            f"the drift checker exited {proc.returncode} on a pair that was "
            f"deliberately measured under two different settings; it must exit "
            f"1. A checker that does not fire here would pass a drifted "
            f"campaign silently, which is the whole failure it exists to catch.")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASS: the record reaches a real result, the digest moves with the "
          f"conditions, and the checker fires. Written under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
