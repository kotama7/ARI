#!/usr/bin/env python3
"""Run the credential-free portion of PaperBench upstream compatibility.

This deliberately does not claim official-runner parity.  Full parity also
requires the pinned dataset, container, rollout model, reproduction substrate,
and official judge execution.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC = PACKAGE_ROOT / "src"
for path in (PACKAGE_ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _digest(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git_commit(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def main() -> int:
    inventory_path = PACKAGE_ROOT / "paperbench_patches.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected_commit = str(inventory["upstream"]["commit"])
    vendor = PACKAGE_ROOT / "vendor" / "paperbench"
    observed_commit = _git_commit(vendor)
    checks: list[dict] = []

    source_passed = observed_commit == expected_commit
    checks.append(
        {
            "check_id": "pinned-upstream-source",
            "status": "passed" if source_passed else "failed",
            "evidence_digest": _digest(
                {
                    "inventory": inventory,
                    "observed_commit": observed_commit,
                }
            ),
            "detail": f"expected={expected_commit}; observed={observed_commit or 'unavailable'}",
        }
    )

    api_passed = False
    reference_passed = False
    negative_passed = False
    api_detail = ""
    try:
        import _paperbench_bridge as bridge

        api_passed = all(
            value.__module__.startswith("paperbench.")
            for value in (bridge.TaskNode, bridge.GradedTaskNode, bridge.SimpleJudge)
        )

        def graded(score: float):
            leaf = bridge.GradedTaskNode(
                id="leaf",
                requirements="credential-free deterministic control",
                weight=1,
                sub_tasks=(),
                score=score,
                valid_score=True,
                explanation="control",
                task_category="Code Development",
                judge_metadata=None,
            )
            return bridge.GradedTaskNode(
                id="root",
                requirements="root",
                weight=1,
                sub_tasks=(leaf,),
                score=score,
                valid_score=True,
                explanation="",
                task_category=None,
                judge_metadata=None,
            )

        reference = bridge.aggregate_graded_tree(graded(1.0))
        negative = bridge.aggregate_graded_tree(graded(0.0))
        reference_passed = reference["ors_score"] == 1.0
        negative_passed = negative["ors_score"] == 0.0
        api_detail = (
            f"reference_score={reference['ors_score']}; "
            f"negative_score={negative['ors_score']}"
        )
    except Exception as exc:
        api_detail = f"{type(exc).__name__}: {exc}"

    for check_id, passed in (
        ("upstream-api-symbols", api_passed),
        ("deterministic-reference-aggregation", reference_passed),
        ("deterministic-negative-aggregation", negative_passed),
    ):
        checks.append(
            {
                "check_id": check_id,
                "status": "passed" if passed else "failed",
                "evidence_digest": _digest(
                    {
                        "check_id": check_id,
                        "commit": observed_commit,
                        "detail": api_detail,
                    }
                ),
                "detail": api_detail,
            }
        )

    checks.sort(key=lambda item: item["check_id"])
    report = {
        "schema_version": "ari.paperbench-upstream-compatibility/v1",
        "scope": "api-and-deterministic-aggregation-only",
        "source_repository": inventory["upstream"]["repository"],
        "source_revision": observed_commit,
        "inventory_digest": _digest(inventory),
        "checks": checks,
        "compatibility_passed": all(item["status"] == "passed" for item in checks),
        "official_runner_parity": False,
        "official_runner_status": "not_available",
        "external_prerequisites": [
            "pinned PaperBench dataset revision and digest",
            "pinned network-isolated container digest",
            "scoped rollout and judge model credentials",
            "official rollout-reproduction-judge execution",
            "reference and wrong-submission end-to-end controls",
            "ARI normalized-result comparison against official output",
        ],
    }
    report["report_digest"] = _digest(report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["compatibility_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
