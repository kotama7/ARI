#!/usr/bin/env python3
"""Run the fixed post-hoc rubric panel on one final manuscript.

This is deliberately separate from the co-evolving ``paper_reviewer`` and
from the in-loop ``review_report.json``.  It writes the dedicated
``panel_review_report.json`` consumed by the P1 paper metric.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_SKILL_ROOT = REPO_ROOT / "ari-skill-paper"
ARI_CORE_ROOT = REPO_ROOT / "ari-core"


def _decision(review: dict) -> str:
    return str((review or {}).get("decision") or "").strip()


def build_panel_report(spec: dict, reviews: list[dict], *, model: str) -> dict:
    """Pure report constructor shared with offline tests."""

    rubrics = [str(r) for r in (spec.get("rubrics") or ())]
    ensemble = int(spec.get("num_reviews_ensemble", 1) or 1)
    seed = spec.get("seed")
    return {
        "schema_version": 1,
        "panel": {
            "rubrics": sorted(rubrics),
            "num_reviews_ensemble": ensemble,
            "seed": seed,
        },
        "sampling": {
            "requested_seed": seed,
            "seed_semantics": "best_effort_provider_dependent",
        },
        "model": str(model or ""),
        "panel_reviews": [dict(r) for r in reviews],
    }


async def run_panel(checkpoint_dir: Path, spec: dict) -> dict:
    """Execute rubric × ensemble-member reviews with requested member seeds.

    Each request is assigned a stable seed for provenance.  Whether the seed
    controls sampling is provider- and CLI-backend-dependent.
    """

    sys.path.insert(0, str(PAPER_SKILL_ROOT))
    sys.path.insert(0, str(ARI_CORE_ROOT))
    from ari.rqgm.evaluation.conditions import panel_disjointness_violations
    from ari.rqgm.paper_archive import read_paper_draft_archive
    from src import server as paper_server

    ckpt = Path(checkpoint_dir)
    tex = ckpt / "full_paper.tex"
    pdf = ckpt / "full_paper.pdf"
    if not tex.is_file():
        raise RuntimeError(f"final manuscript not found: {tex}")
    rubrics = [str(r) for r in (spec.get("rubrics") or ())]
    ensemble = max(1, int(spec.get("num_reviews_ensemble", 1) or 1))
    base_seed = int(spec.get("seed", 0) or 0)
    lineage = {
        str(r.get("reviewer_prompt_hash") or "")
        for r in read_paper_draft_archive(ckpt)
        if r.get("reviewer_prompt_hash")
    }
    problems = panel_disjointness_violations(
        spec,
        reviewer_prompt_lineage=lineage,
        panel_input_ids=["final_manuscript"],
    )
    if problems:
        raise RuntimeError("panel is not disjoint: " + "; ".join(problems))

    reviews: list[dict] = []
    old_seed = os.environ.get("ARI_PANEL_SEED")
    try:
        member = 0
        for rubric in rubrics:
            for index in range(ensemble):
                os.environ["ARI_PANEL_SEED"] = str(base_seed + member)
                member += 1
                result = await paper_server.review_compiled_paper(
                    tex_path=str(tex),
                    pdf_path=str(pdf) if pdf.is_file() else "",
                    rubric_id=rubric,
                    num_reviews_ensemble=1,
                )
                decision = _decision(result)
                if not decision:
                    raise RuntimeError(
                        f"{rubric} panel member {index} returned no decision: "
                        f"{result.get('error') or 'unknown review failure'}"
                    )
                reviews.append({
                    **dict(result),
                    "rubric_id": rubric,
                    "panel_member": index,
                    "seed": base_seed + member - 1,
                })
    finally:
        if old_seed is None:
            os.environ.pop("ARI_PANEL_SEED", None)
        else:
            os.environ["ARI_PANEL_SEED"] = old_seed
    return build_panel_report(
        spec,
        reviews,
        model=paper_server._get_model("rubric"),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checkpoint_dir", type=Path)
    parser.add_argument(
        "--spec-json", required=True,
        help="JSON object with rubrics, num_reviews_ensemble, seed",
    )
    args = parser.parse_args(argv)
    spec = json.loads(args.spec_json)
    report = asyncio.run(run_panel(args.checkpoint_dir, spec))
    out = args.checkpoint_dir / "panel_review_report.json"
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
