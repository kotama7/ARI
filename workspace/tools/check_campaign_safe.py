"""Is it safe to edit right now, and is the running campaign still intact?

WHY THIS EXISTS. A campaign freezes 524 source files at submit time. Every worker
recomputes that digest when it finishes and the collector recomputes it again, so
changing ANY of those files mid-run discards the run's analysis -- the worker
exits RC=86 and the collector refuses to aggregate. It happened twice on
2026-08-03: once from editing the manuscript (which was pinned, and is not any
more), once from patching a submit script while nine shards were in flight. In
both cases the science had completed and was thrown away.

The check is two questions that are easy to get wrong from memory:

  1. Has anything pinned changed since the campaign was launched? If yes the
     campaign is ALREADY lost and there is no point waiting for it.
  2. Is a given path pinned? `workspace/tools/` and `report_temp/` are not, so
     they can be edited freely during a run; almost everything else cannot.

USAGE
    python check_campaign_safe.py ROOT
    python check_campaign_safe.py ROOT --can-edit report_temp/paper_ja.tex workspace/tools/x.py
"""
import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def _fingerprint(manifest: dict) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="campaign root holding launch_contract.json")
    ap.add_argument("--can-edit", nargs="*", default=[],
                    help="paths to classify as safe or pinned")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO))
    from workspace.run_handoff_ablation import study_source_manifest

    contract_path = pathlib.Path(args.root) / "launch_contract.json"
    if not contract_path.is_file():
        print(f"not a campaign root: {args.root}", file=sys.stderr)
        return 2
    contract = json.loads(contract_path.read_text())
    pinned_then = contract["files"]
    now = study_source_manifest()
    fp_now = _fingerprint(now)
    fp_then = contract["study_source_fingerprint"]

    changed = sorted(k for k in set(now) & set(pinned_then) if now[k] != pinned_then[k])
    added = sorted(set(now) - set(pinned_then))
    removed = sorted(set(pinned_then) - set(now))

    print(f"campaign  : {args.root}")
    print(f"contract  : {fp_then[:24]}")
    print(f"current   : {fp_now[:24]}")
    if fp_now == fp_then:
        print("status    : INTACT -- the campaign's provenance still verifies")
    else:
        print("status    : DRIFTED -- every shard will fail its post-run check")
        for k in changed:
            print(f"  CHANGED {k}")
        for k in added:
            print(f"  ADDED   {k}")
        for k in removed:
            print(f"  REMOVED {k}")
        print()
        print("Restore those files to the recorded bytes, or accept that this")
        print("campaign's analysis is lost and relaunch.")

    for path in args.can_edit:
        rel = str(pathlib.Path(path))
        safe = rel not in now
        print(f"{'SAFE   ' if safe else 'PINNED '} {rel}"
              + ("" if safe else "   <- editing this discards the campaign"))

    return 0 if fp_now == fp_then else 1


if __name__ == "__main__":
    raise SystemExit(main())
