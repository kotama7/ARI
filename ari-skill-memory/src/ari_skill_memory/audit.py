"""Memory audit — verify that recorded provenance still matches disk.

"Memory is an index, not evidence" (PLAN §2): a claim is only as good as
the artifact it points at. This module re-hashes the artifacts referenced by
each node_report and reports, per artifact:

  - ``verified``  : file exists and (when a hash was recorded) still matches.
  - ``missing``   : referenced file is gone.
  - ``mismatch``  : file exists but its sha256 changed since recording.
  - ``unhashed``  : file exists, no recorded hash to compare against.

Run: ``python -m ari_skill_memory.audit <experiments_root> [run_id]``
(``ari memory audit`` CLI wiring is a follow-up.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .provenance import node_work_dir, refs_from_node_report, sha256_of


def audit_node_report(node_report: dict, work_dir: Path) -> list[dict]:
    """Audit every artifact ref of one node_report against ``work_dir``."""
    work_dir = Path(work_dir)
    out: list[dict] = []
    # compute_missing=False: only compare against hashes node_report actually
    # recorded; artifacts without a recorded baseline are reported "unhashed".
    for ref in refs_from_node_report(node_report, work_dir, compute_missing=False):
        abspath = work_dir / ref.path
        exists = abspath.exists()
        current = sha256_of(abspath) if exists else None
        if not exists:
            status = "missing"
        elif ref.sha256 is None:
            status = "unhashed"
        elif current == ref.sha256:
            status = "verified"
        else:
            status = "mismatch"
        out.append(
            {
                "node_id": node_report.get("node_id", ""),
                "path": ref.path,
                "role": ref.role,
                "recorded_sha256": ref.sha256,
                "current_sha256": current,
                "status": status,
            }
        )
    return out


def audit_checkpoint(experiments_root: Path, run_id: str | None = None) -> list[dict]:
    """Audit every node_report under ``experiments_root`` (optionally one run).

    Layout: ``<experiments_root>/<run_id>/<node_id>/node_report.json``.
    """
    root = Path(experiments_root)
    runs = [root / run_id] if run_id else [p for p in root.iterdir() if p.is_dir()]
    results: list[dict] = []
    for run_dir in runs:
        if not run_dir.is_dir():
            continue
        for node_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            report_path = node_dir / "node_report.json"
            try:
                report = json.loads(report_path.read_text())
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
            results.extend(audit_node_report(report, node_dir))
    return results


def summarize(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m ari_skill_memory.audit <experiments_root> [run_id]", file=sys.stderr)
        return 2
    root = Path(argv[0])
    run_id = argv[1] if len(argv) > 1 else None
    results = audit_checkpoint(root, run_id)
    print(json.dumps({"summary": summarize(results), "results": results}, ensure_ascii=False, indent=2))
    # non-zero exit if any artifact failed verification
    bad = sum(1 for r in results if r["status"] in ("missing", "mismatch"))
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
