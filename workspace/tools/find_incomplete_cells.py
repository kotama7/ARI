"""Which cells of a submitted campaign did NOT finish, as array indices.

WHY THIS EXISTS. The collector refuses to analyse a partial grid — it raises
``missing matrix cells: ...`` rather than quietly reporting a subset, which is
the right call. The consequence is that ONE failed cell out of 270 blocks the
whole analysis, and nothing retries it: the LLM client backs off per call, the
pipeline stage backs off per tool call, but ``orchestrator/bfts.py`` states
plainly that "ARI does not retry failed nodes", and there is no retry above
that either. In the preliminary campaign two cells hit a terminal
``RateLimitError`` and had to be found and re-run by hand.

This finds them mechanically. A cell counts as COMPLETE only when its manifest
row exists, records ``rc == 0``, names a ``run_dir`` that exists, and points at
a ``final_measurement.json`` that is present and marked valid. Anything else —
never started, killed, out of time, terminal API error, or finished with an
unscored final measurement — is incomplete and is reported.

The array index is recovered by inverting the launcher's own arithmetic, so a
resubmission lands on exactly the same (task, arm, seed) it did the first time.

USAGE
    python find_incomplete_cells.py ROOT              # human-readable
    python find_incomplete_cells.py ROOT --indices    # "3,17,204" for sbatch --array
"""
import argparse
import json
import pathlib
import sys

TASKS = ["gemm", "spmm", "stencil"]
ARMS = ["code_only", "evidence_only", "evidence_plus_reflection"]
CELLS_PER_SEED = len(TASKS) * len(ARMS)


def cell_of_index(idx: int, seed_base: int) -> tuple[str, str, int]:
    """Transcription of submit_handoff_ablation_sbatch.sh."""
    seed = seed_base + idx // CELLS_PER_SEED
    within = idx % CELLS_PER_SEED
    return TASKS[within // 3], ARMS[(within % 3 + seed) % 3], seed


def cell_status(root: pathlib.Path, task: str, arm: str, seed: int,
                expected_fingerprint: str | None = None) -> tuple[bool, str]:
    shard = root / "shards" / task / arm / f"seed_{seed}"

    # CHECK PROVENANCE FIRST. A cell whose science completed but whose source
    # digest moved during the run exits RC=86 and is unusable, yet its manifest
    # still records rc=0 and the fingerprint captured at START -- so the manifest
    # alone cannot see the failure. source_integrity.json keeps before/after and
    # is the only place the post-run recheck survives.
    integ = shard / "source_integrity.json"
    if integ.is_file():
        try:
            d = json.loads(integ.read_text())
        except Exception as exc:
            return False, f"unreadable source_integrity.json: {exc}"
        if d.get("status") != "verified":
            return False, (f"source integrity {d.get('status')!r}: "
                           f"before={str(d.get('before'))[:12]} "
                           f"after={str(d.get('after'))[:12]}")
        if expected_fingerprint and d.get("expected") != expected_fingerprint:
            return False, "source integrity checked against a different contract"

    man = shard / "manifest.jsonl"
    if not man.is_file():
        return False, "no manifest (never started, or killed before recording)"
    rows = [json.loads(l) for l in man.read_text().splitlines() if l.strip()]
    if not rows:
        return False, "empty manifest"
    row = rows[-1]
    if row.get("rc") not in (0, "0"):
        return False, f"rc={row.get('rc')}"
    run_dir = row.get("run_dir")
    if not run_dir or not pathlib.Path(run_dir).is_dir():
        return False, f"run_dir missing: {run_dir!r}"
    fm = (row.get("final_measurement") or {})
    path = fm.get("path") or str(pathlib.Path(run_dir) / "final_measurement.json")
    if not pathlib.Path(path).is_file():
        return False, "no final_measurement.json"
    if fm.get("status") != "valid":
        return False, f"final measurement status={fm.get('status')!r} ({fm.get('reason')})"
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--indices", action="store_true",
                    help="print only a comma-separated array index list")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    contract = root / "launch_contract.json"
    if not contract.is_file():
        print(f"no launch_contract.json under {root}", file=sys.stderr)
        return 2
    c = json.loads(contract.read_text())
    seeds, seed_base = int(c["seeds"]), int(c["seed_base"])

    incomplete = []
    for idx in range(seeds * CELLS_PER_SEED):
        task, arm, seed = cell_of_index(idx, seed_base)
        ok, why = cell_status(root, task, arm, seed,
                              c.get("study_source_fingerprint"))
        if not ok:
            incomplete.append((idx, task, arm, seed, why))

    if args.indices:
        print(",".join(str(i[0]) for i in incomplete))
        return 0

    total = seeds * CELLS_PER_SEED
    print(f"root  : {root}")
    print(f"mode  : {c.get('mode')}   seeds={seeds} seed_base={seed_base}   cells={total}")
    print(f"complete   : {total - len(incomplete)}/{total}")
    print(f"incomplete : {len(incomplete)}")
    for idx, task, arm, seed, why in incomplete:
        print(f"  index {idx:>3d}  {task:<8s} {arm:<26s} seed {seed:<3d}  {why}")
    if incomplete:
        print()
        print("Resubmit exactly these with the SAME frozen design:")
        print(f"  bash workspace/submit_handoff_ablation_array.sh --resume {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
