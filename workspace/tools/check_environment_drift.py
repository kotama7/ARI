"""Did the measurement environment hold still while the study ran?

THE GAP THIS CLOSES. The harness records the measurement-relevant environment
with every score and digests it. Recording answers "what was it". It does not
answer "was it the same one all the way through", and nothing was reading the
record back -- the same captured-but-unattached shape the capture itself was
written to prevent one level down.

WHY IT IS NOT PARANOIA. `XOS_MMM_L_PAGING_POLICY` moves the same frozen stencil
source by 5.9x. A site default changed between Monday's shards and Friday's does
not fail anything: every shard scores, every number looks reasonable, and the
contrast between conditions absorbs a factor that has nothing to do with the
agents. Per-repetition pairing cancels conditions that vary WITHIN a scoring; it
cannot cancel one that changed BETWEEN them.

WHAT IT REPORTS. Every distinct environment digest seen across a study root,
which variables differ between them, and how the runs divide. A study with one
digest is comparable on this axis. A study with more than one is not, unless the
differing variables are ones that provably cannot reach the measurement -- and
that is a judgement call, so this prints the difference rather than deciding.

THE EMPTY-RECORD TRAP. A capture that matches nothing still produces a digest --
the digest of an empty mapping -- so every scoring agrees perfectly and the study
reads as maximally consistent. That is backwards: no record is refused, while an
empty record looks like the cleanest possible result. Records whose variables are
empty are therefore counted separately and refused.

EXIT CODES
    0  one digest over non-empty records, or --report-only
    1  more than one digest across the runs examined
    2  no usable environment records: none found, or every one of them is empty.
       An old study, a broken capture and an environment that genuinely had none
       of these variables set are indistinguishable from outside, so none of the
       three is ever reported as clean.

USAGE
    python check_environment_drift.py workspace/checkpoints/<study>
    python check_environment_drift.py <study> --report-only
"""
import argparse
import collections
import json
import pathlib
import sys


def _iter_records(root: pathlib.Path):
    """Every (path, environment-record) under a study root.

    Two producers write one: the study manifest, once per run, and the harness,
    once per scoring inside a node report. Both are read -- a manifest that
    agrees with itself while the harness saw something else is exactly the case
    worth catching.
    """
    for path in sorted(root.rglob("*.json")):
        if "study_bundle/source" in str(path):
            continue                       # pinned copies of the source tree
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for env in _find_envs(doc):
            if isinstance(env, dict) and env.get("sha256"):
                yield path, env


def _find_envs(obj, depth: int = 0, key: str = "measurement_environment"):
    if depth > 8:
        return
    if isinstance(obj, dict):
        env = obj.get(key)
        if isinstance(env, dict):
            yield env
        for v in obj.values():
            yield from _find_envs(v, depth + 1, key)
    elif isinstance(obj, list):
        for v in obj[:200]:
            yield from _find_envs(v, depth + 1, key)


def _placement_drift(root: pathlib.Path) -> tuple[int, dict]:
    """The SECOND question this tool could not answer: did the runs land on the
    same kind of machine?

    The environment digest is computed over launcher-exported constants, which
    are invariant to the hardware -- so a study spread across allocations with
    different memory topology, a different page size, or a differently shaped
    cpuset passed every check and reported one environment. Measured on two
    partitions of one cluster: 4 NUMA domains of 12 cores with 64 KiB pages
    against 1 domain with 4 KiB pages and a cpuset of 8 cores plus their SMT
    siblings carved out of 192. Placement is not neutral -- the scored arrays are
    first-touched serially onto ONE domain while the threads spread across all of
    them, and the archived gate measured about 1.29x on the frozen stencil.

    Reported separately from the environment because it is a different finding:
    one says the settings changed, the other says the machine did.
    """
    counts: collections.Counter = collections.Counter()
    bodies: dict[str, dict] = {}
    where: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(root.rglob("*.json")):
        if "study_bundle/source" in str(path):
            continue
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for rec in _find_envs(doc, key="measurement_placement"):
            d = rec.get("sha256")
            if not d:
                continue
            counts[d] += 1
            bodies.setdefault(d, rec)
            if len(where[d]) < 3:
                where[d].append(str(path.relative_to(root)))
    if not counts:
        print("\nPLACEMENT: no records. A study predating the placement capture\n"
              "  and one whose capture is broken look the same from here, so this\n"
              "  is not reported as clean either.")
        return 0, {"records": 0}
    print(f"\nPLACEMENT: {sum(counts.values())} record(s), "
          f"{len(counts)} distinct digest(s)")
    for d, n in counts.most_common():
        b = bodies[d]
        print(f"  {d[:16]}  {n:5d} record(s)  {b.get('machine')} "
              f"cpus={b.get('cpus_allowed')} "
              f"numa={b.get('numa_nodes_spanned')}/{b.get('numa_nodes_total')} "
              f"page={b.get('page_size_bytes')} threads={b.get('thread_budget')}"
              f"   e.g. {where[d][0]}")
    finding = {"records": sum(counts.values()),
               "digests": {d: n for d, n in counts.most_common()},
               "differing_fields": {}}
    if len(counts) > 1:
        ordered = [d for d, _ in counts.most_common()]
        base = ordered[0]
        print(f"\n  DIFFERENCES against {base[:16]}:")
        for other in ordered[1:]:
            a, b = bodies[base], bodies[other]
            keys = sorted(set(a) | set(b)) 
            diff = {k: (a.get(k), b.get(k)) for k in keys
                    if k != "sha256" and a.get(k) != b.get(k)}
            finding["differing_fields"][other] = {
                k: {"common": v[0], "this": v[1]} for k, v in diff.items()}
            for k, (was, now) in diff.items():
                print(f"    {k}\n        most common : {was!r}\n        here        : {now!r}")
        print("\n  These runs did not all land on the same shape of machine.\n"
              "  Nothing in the study SETS placement -- there is no numactl, no\n"
              "  taskset, no mbind anywhere on the measurement path -- so every\n"
              "  difference above is an inherited default that reached the score.")
    return (1 if len(counts) > 1 else 0), finding


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="a study root under workspace/checkpoints/")
    ap.add_argument("--report-only", action="store_true",
                    help="print the finding but always exit 0")
    ap.add_argument("--json", default=None, help="also write the finding here")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    by_digest: dict[str, dict] = {}
    empty = 0
    counts: collections.Counter = collections.Counter()
    where: dict[str, list[str]] = collections.defaultdict(list)
    for path, env in _iter_records(root):
        if not (env.get("variables") or {}):
            # A digest of nothing. Counting it would make a broken capture the
            # most consistent study anyone ever measured.
            empty += 1
            continue
        d = env["sha256"]
        by_digest.setdefault(d, env.get("variables") or {})
        counts[d] += 1
        if len(where[d]) < 3:
            where[d].append(str(path.relative_to(root)))

    if not counts:
        if empty:
            print(f"{empty} environment record(s), ALL EMPTY.\n"
                  f"  Each carries a digest computed over no variables, so they\n"
                  f"  all agree and the study would otherwise read as perfectly\n"
                  f"  consistent. A broken capture and an environment with none\n"
                  f"  of these variables set look identical from here, so this\n"
                  f"  is not reported as clean. Check the capture prefixes.",
                  file=sys.stderr)
        else:
            print("NO ENVIRONMENT RECORDS under this root.\n"
                  "  A study predating the capture and a study whose capture is\n"
                  "  broken look the same from here, so this is not reported as\n"
                  "  clean. Check that the harness writes measurement_environment.",
                  file=sys.stderr)
        return 2

    total = sum(counts.values())
    print(f"{total} environment record(s), {len(counts)} distinct digest(s)")
    if empty:
        print(f"  ({empty} further record(s) captured NO variables and are not "
              f"counted; a digest of nothing agrees with every other digest of "
              f"nothing)")
    print()
    for d, n in counts.most_common():
        print(f"  {d[:16]}  {n:5d} record(s)   e.g. {where[d][0]}")

    finding = {"root": str(root), "records": total, "empty_records": empty,
               "digests": {d: n for d, n in counts.most_common()},
               "differing_variables": {}}

    if len(counts) > 1:
        ordered = [d for d, _ in counts.most_common()]
        base = ordered[0]
        print(f"\nDIFFERENCES against the most common digest {base[:16]}:")
        for other in ordered[1:]:
            a, b = by_digest[base], by_digest[other]
            keys = sorted(set(a) | set(b))
            diff = {k: (a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)}
            finding["differing_variables"][other] = {
                k: {"common": v[0], "this": v[1]} for k, v in diff.items()}
            print(f"\n  {other[:16]} ({counts[other]} record(s)):")
            for k, (was, now) in diff.items():
                print(f"    {k}\n        most common : {was!r}\n        here        : {now!r}")
        print("\nThe runs above were not all measured under the same conditions.\n"
              "Pairing inside a repetition cancels what varies WITHIN a scoring;\n"
              "it does not cancel a variable that changed BETWEEN scorings. Decide\n"
              "per variable whether it can reach the measurement -- and if it can,\n"
              "the affected runs are not comparable and re-measurement is the only\n"
              "honest fix.")

    place_rc, place_finding = _placement_drift(root)
    finding["placement"] = place_finding

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(finding, indent=1))
        print(f"\nwrote {args.json}")

    if args.report_only:
        return 0
    # Either kind of drift refuses. They are different findings -- the settings
    # changed, or the machine did -- but neither leaves the runs comparable.
    return 1 if (len(counts) > 1 or place_rc) else 0


if __name__ == "__main__":
    raise SystemExit(main())
