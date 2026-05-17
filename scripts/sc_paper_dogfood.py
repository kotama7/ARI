#!/usr/bin/env python3
"""End-to-end dogfood: feed an external SC paper PDF through PaperBench-format
rubric generation (and optional judge dry-run).

Reproduces what the GUI's import → wizard → run flow *should* eventually do,
but without the GUI: read a PDF, call ``generate_rubric_async`` from
``ari-skill-replicate``, optionally pipe the rubric into ``judge_submission``
from ``ari-skill-paper-re`` against an empty submission, and print results
so a human can eyeball whether the rubric and the judge make sense on
externally-imported SC papers.

Usage:

    # arXiv:
    python scripts/sc_paper_dogfood.py --arxiv 2404.14193

    # local PDF:
    python scripts/sc_paper_dogfood.py --pdf /path/to/cuSZ-i.pdf

    # with two-stage rubric generation + judge dry-run:
    python scripts/sc_paper_dogfood.py --arxiv 2404.14193 --two-stage --judge-dryrun

Environment:
    ARI_MODEL_RUBRIC_GEN   model for rubric generation (default: gpt-5-mini)
    OPENAI_API_KEY         required when using openai/* models
    ARI_MODEL_JUDGE        model for judge_submission (default: gpt-5-mini)

The script auto-loads ``.env`` from the repo root if present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Add skill src directories to sys.path so we can import the production modules
# directly (no editable install required).
for _src in [REPO / "ari-skill-replicate" / "src", REPO / "ari-skill-paper-re" / "src"]:
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


def _load_dotenv() -> None:
    """Minimal .env loader (no python-dotenv dependency)."""
    env_path = REPO / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _arxiv_to_pdf(arxiv_id: str, dest: Path) -> Path:
    """Download arXiv PDF to ``dest`` and return the path."""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    print(f"[fetch] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ari-dogfood/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())
    return dest


def _pdf_to_text(
    pdf: Path,
    image_dir: Path | None = None,
    *,
    image_size_limit: float = 0.01,
    image_dpi: int = 150,
) -> str:
    """Convert ``pdf`` to markdown text.

    Primary path: ``pymupdf4llm.to_markdown`` with ``write_images=True`` so
    figures end up as PNGs on disk and the returned markdown carries
    ``![](images/img-N.png)`` references. The multimodal judge expander
    in ``ari-skill-paper-re/src/_litellm_completer.py`` resolves those
    references at API-call time, so a single multimodal judge call sees
    both the body text and the rendered figures — no separate VLM
    pipeline needed.

    ``image_size_limit`` is pymupdf4llm's **minimum** image size as a
    fraction of page dimensions: anything smaller than
    ``image_size_limit * page_dim`` on either axis is filtered out.
    Default 0.01 (1% of page) is permissive and captures small inline
    figures + sub-figures + table images; raise toward 0.10 to keep
    only large headline figures.

    Three-tier fallback (AI-Scientist-v2 style) so we still get *some*
    text on encrypted / damaged PDFs::

        pymupdf4llm.to_markdown → pymupdf.get_text → pdftotext -layout
    """
    try:
        import pymupdf4llm  # type: ignore
        kwargs: dict = {"write_images": image_dir is not None}
        if image_dir is not None:
            image_dir.mkdir(parents=True, exist_ok=True)
            kwargs["image_path"] = str(image_dir)
            kwargs["image_format"] = "png"
            kwargs["dpi"] = image_dpi
            kwargs["image_size_limit"] = image_size_limit
        md = pymupdf4llm.to_markdown(str(pdf), **kwargs)
        if md and len(md) >= 100:
            return md
        raise RuntimeError("pymupdf4llm returned too little text")
    except Exception as e1:
        print(f"[pdf.warn] pymupdf4llm failed: {e1}; falling back to pymupdf")
    try:
        import pymupdf  # type: ignore
        doc = pymupdf.open(str(pdf))
        text = "".join(page.get_text() for page in doc)
        if text and len(text) >= 100:
            return text
        raise RuntimeError("pymupdf returned too little text")
    except Exception as e2:
        print(f"[pdf.warn] pymupdf failed: {e2}; falling back to pdftotext")
    res = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, check=True,
    )
    return res.stdout.decode("utf-8", errors="replace")


def _print_rubric_tree(node: dict, depth: int = 0, weight_prefix: float = 1.0) -> None:
    indent = "  " * depth
    name = node.get("category", node.get("requirements", "?"))[:80]
    w = float(node.get("weight", 0.0))
    if "sub_tasks" in node and node["sub_tasks"]:
        print(f"{indent}├ [{w:.3f}] {name}")
        for child in node["sub_tasks"]:
            _print_rubric_tree(child, depth + 1, weight_prefix * w)
    else:
        kind = node.get("task_category", node.get("kind", "?"))
        print(f"{indent}└ [{w:.3f}] {kind}: {name}")


def _walk_leaves(node: dict, weight_prefix: float = 1.0):
    if node.get("sub_tasks"):
        for child in node["sub_tasks"]:
            yield from _walk_leaves(child, weight_prefix * float(node.get("weight", 1.0)))
    else:
        yield node, weight_prefix * float(node.get("weight", 1.0))


async def run_rubric(paper_text: str, out_dir: Path, *, two_stage: bool,
                     target_leaves: int, model: str,
                     rubric_template: str | None = None) -> dict:
    from generator import generate_rubric_async  # type: ignore

    out_path = out_dir / "rubric.json"
    print(f"[rubric] model={model or '<default>'} two_stage={two_stage} "
          f"target_leaves={target_leaves or '<auto>'} "
          f"template={rubric_template or '<generic>'}")
    res = await generate_rubric_async(
        paper_text=paper_text,
        output_path=str(out_path),
        target_leaf_count=target_leaves,
        model=model,
        two_stage=two_stage,
        paperbench_rubric_id=rubric_template,
    )
    return res


async def run_judge_dryrun(
    rubric_envelope: dict,
    paper_text: str,
    judge_model: str,
    submission_dir: Path | None = None,
    paper_audit_mode: bool = False,
) -> None:
    """Pipe the generated rubric into judge_submission.

    When ``submission_dir`` is supplied (e.g. from --with-reproduce-plan
    Step 4 output), the judge sees a real reproduction package; otherwise
    an empty tempdir is used and ``Result Analysis`` leaves cannot score.

    ``paper_audit_mode`` swaps the vendor's submission-oriented
    TASK_CATEGORY_QUESTIONS to paper-audit flavors (see
    ``ari-skill-paper-re/src/_paperbench_bridge.py``). Required for
    paper_audit-mode templates to break the structural ceiling.
    """
    from _paperbench_bridge import judge_submission, task_node_from_dict  # type: ignore

    rubric_dict = rubric_envelope.get("rubric") or rubric_envelope
    rubric_node = task_node_from_dict(rubric_dict)

    own_tmp = None
    if submission_dir is None:
        own_tmp = tempfile.TemporaryDirectory()
        submission_dir = Path(own_tmp.name) / "submission"
        submission_dir.mkdir()
        (submission_dir / "reproduce.log").write_text("(empty — dogfood dry-run)\n")
    try:
        files = sorted(p.name for p in submission_dir.iterdir()) if submission_dir.is_dir() else []
        print(f"[judge] model={judge_model}  paper_audit_mode={paper_audit_mode}  "
              f"submission={submission_dir} (files: {files or '<empty>'})")
        graded = await judge_submission(
            paper_md=paper_text,
            rubric=rubric_node,
            submission_dir=submission_dir,
            reproduce_log="",
            judge_model=judge_model,
            paper_audit_mode=paper_audit_mode,
        )
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()

    print(f"\n[judge.results] per-leaf scores (submission_dir={submission_dir}):")
    leaves_seen = 0
    score_sum = 0.0
    for leaf in _walk_graded_leaves(graded):
        leaves_seen += 1
        s = float(getattr(leaf, "score", 0.0) or 0.0)
        score_sum += s
        name = (getattr(leaf, "requirements", "") or getattr(leaf, "category", ""))[:70]
        print(f"  score={s:.2f}  {name}")
    print(f"\n[judge.summary] leaves={leaves_seen}  mean_score={score_sum / max(leaves_seen, 1):.3f}")


def _walk_graded_leaves(graded):
    if getattr(graded, "sub_tasks", None):
        for child in graded.sub_tasks:
            yield from _walk_graded_leaves(child)
    else:
        yield graded


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(
        description="Dogfood an external SC paper through PaperBench-format rubric + judge.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf", type=Path, help="Local PDF path.")
    src.add_argument("--arxiv", help="arXiv ID (e.g. 2404.14193).")
    ap.add_argument("--two-stage", action="store_true",
                    help="Use two-stage rubric generation (skeleton → subtrees).")
    ap.add_argument("--target-leaves", type=int, default=0,
                    help="Target leaf count (0 = auto from paper length).")
    ap.add_argument("--rubric-template", default="",
                    help="Venue template id under ari-core/config/paperbench_rubrics/ "
                         "(e.g. 'sc' for HPC paper audit per "
                         "HPC PaperBench audit research plan §5 Step 3). "
                         "Empty = bundled generic prompt (back-compat).")
    ap.add_argument("--image-size-limit", type=float, default=0.01,
                    help="pymupdf4llm minimum image size as fraction of page "
                         "(default: 0.01 = 1%% of page; lower captures more, "
                         "raise toward 0.10 for only large headline figures).")
    ap.add_argument("--image-dpi", type=int, default=150,
                    help="Rendered PNG DPI for figures (default 150).")
    ap.add_argument("--max-images", type=int, default=40,
                    help="Cap on multimodal images attached per judge message "
                         "(env override: ARI_MULTIMODAL_MAX_IMAGES).")
    ap.add_argument("--paper-extras", type=Path, nargs="*", default=[],
                    help="Additional PDFs to concatenate to the main paper "
                         "(typical use: AD/AE Appendix downloaded from "
                         "ACM DL or SC's reproducibility page). Each extra "
                         "is converted to MD via pymupdf4llm with images "
                         "into the same images/ dir, then appended to the "
                         "main paper.md with a '## Appendix: <basename>' "
                         "header so the judge can distinguish them. "
                         "Used to test HPC PaperBench audit research plan "
                         "hypothesis 2 (paper-only vs +AD vs +AD/AE).")
    ap.add_argument("--rubric-model", default=os.environ.get("ARI_MODEL_RUBRIC_GEN", ""),
                    help="LLM model for rubric gen. Default: env ARI_MODEL_RUBRIC_GEN.")
    ap.add_argument("--judge-dryrun", action="store_true",
                    help="After rubric gen, run judge_submission on an empty submission.")
    ap.add_argument("--judge-model", default=os.environ.get("ARI_MODEL_JUDGE", "gpt-5-mini"),
                    help="LLM model for judge.grade_leaf. Default: gpt-5-mini.")
    ap.add_argument("--with-reproduce-plan", action="store_true",
                    help="HPC PaperBench audit research plan §5 Step 4: ask the LLM "
                         "to generate a reproduction package (reproduce_plan.md "
                         "/ verification_code.py / install_commands.txt / "
                         "reproduce.log) from the paper, write it to "
                         "<out>/submission/, then pass that as submission_dir "
                         "to judge_submission. Unblocks Result Analysis "
                         "category leaves that would otherwise score 0 on an "
                         "empty submission.")
    ap.add_argument("--reproduce-plan-model", default="",
                    help="LLM model for the Step 4 generator. Empty = inherit "
                         "ARI_MODEL_REPRODUCE_PLAN env or ARI_MODEL_REPLICATE.")
    ap.add_argument("--paper-audit-mode", action="store_true",
                    help="Patch vendor SimpleJudge's TASK_CATEGORY_QUESTIONS "
                         "to paper-audit-flavored questions during judge "
                         "(see ari-skill-paper-re/src/_paperbench_bridge.py). "
                         "Without this, the vendor's submission-oriented "
                         "questions cap the score around 0.3 for paper_audit "
                         "mode templates. Auto-enabled when "
                         "--rubric-template is a paper_audit template.")
    ap.add_argument("--out", type=Path, default=Path("/tmp/sc_paper_dogfood"),
                    help="Output dir for rubric.json + paper.txt.")
    args = ap.parse_args()

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.arxiv:
        pdf_path = _arxiv_to_pdf(args.arxiv, out_dir / f"{args.arxiv}.pdf")
    else:
        pdf_path = args.pdf
        if not pdf_path.is_file():
            print(f"error: --pdf path not found: {pdf_path}", file=sys.stderr)
            return 2

    print(f"[pdf] {pdf_path}  ({pdf_path.stat().st_size:,} bytes)")
    image_dir = out_dir / "images"
    paper_text = _pdf_to_text(
        pdf_path,
        image_dir=image_dir,
        image_size_limit=args.image_size_limit,
        image_dpi=args.image_dpi,
    )
    n_images_main = len(list(image_dir.glob("*.png"))) if image_dir.is_dir() else 0
    print(f"[pdf] {len(paper_text):,} chars extracted → main "
          f"({n_images_main} figure PNGs at size_limit={args.image_size_limit}, "
          f"dpi={args.image_dpi})")
    # Optional AD/AE concat (HPC PaperBench audit research plan hypothesis 2).
    for extra in (args.paper_extras or []):
        extra = Path(extra)
        if not extra.is_file():
            print(f"[pdf.warn] --paper-extras {extra} not found, skipping")
            continue
        extra_md = _pdf_to_text(
            extra,
            image_dir=image_dir,
            image_size_limit=args.image_size_limit,
            image_dpi=args.image_dpi,
        )
        n_images_total = len(list(image_dir.glob("*.png")))
        new_imgs = n_images_total - n_images_main
        paper_text += (
            f"\n\n## Appendix: {extra.stem}\n\n_(concatenated by "
            f"sc_paper_dogfood.py --paper-extras)_\n\n{extra_md}"
        )
        print(f"[pdf+extra] {extra.name}: {len(extra_md):,} chars, "
              f"+{new_imgs} figure PNGs (total {n_images_total})")
        n_images_main = n_images_total
    (out_dir / "paper.md").write_text(paper_text)
    print(f"[pdf] final paper.md = {len(paper_text):,} chars → "
          f"{out_dir / 'paper.md'}")
    # Propagate max_images to the multimodal expander in
    # ari-skill-paper-re/src/_litellm_completer.py via env (the expander
    # reads ARI_MULTIMODAL_MAX_IMAGES at module import time).
    os.environ["ARI_MULTIMODAL_MAX_IMAGES"] = str(args.max_images)

    rubric_template_id = args.rubric_template.strip() or None
    # paper_audit mode (sc.yaml, future neurips.yaml, …) requires two_stage —
    # the loader enforces this but it's friendlier to flip the flag here so
    # casual `--rubric-template sc` invocations don't surface an error.
    if rubric_template_id and not args.two_stage:
        print(f"[hint] --rubric-template {rubric_template_id!r} implies --two-stage; enabling")
        args.two_stage = True
    rubric_res = asyncio.run(run_rubric(
        paper_text=paper_text,
        out_dir=out_dir,
        two_stage=args.two_stage,
        target_leaves=args.target_leaves,
        model=args.rubric_model,
        rubric_template=rubric_template_id,
    ))

    if "error" in rubric_res:
        print(f"\n[rubric.error] {rubric_res['error']}", file=sys.stderr)
        if rubric_res.get("warnings"):
            for w in rubric_res["warnings"]:
                print(f"  warn: {w}", file=sys.stderr)
        return 1

    print(f"\n[rubric.result] {json.dumps({k: v for k, v in rubric_res.items() if k != 'envelope'}, indent=2, ensure_ascii=False)}")
    rubric_path = Path(rubric_res["rubric_path"])
    envelope = json.loads(rubric_path.read_text())
    rubric_dict = envelope.get("rubric") or envelope

    # PaperBench format uses absolute integer weights at every node; the
    # normalisation to a [0, 1] aggregate score happens inside
    # aggregate_graded_tree at judge time. So we surface raw leaf counts +
    # the direct-children weight distribution, not "Σwᵢ should equal 1".
    leaves = list(_walk_leaves(rubric_dict))
    print(f"\n[rubric.tree] {rubric_path}")
    _print_rubric_tree(rubric_dict)
    direct_children = rubric_dict.get("sub_tasks") or []
    print(f"\n[rubric.summary] leaves={len(leaves)}  "
          f"direct_children={len(direct_children)}  "
          f"top_weights={[int(c.get('weight', 0)) for c in direct_children]}")

    # Step 4 (HPC PaperBench audit research plan §5): LLM-generated reproduction
    # package. Writes 4 artifacts to <out>/submission/ so the vendor
    # SimpleJudge's Result Analysis branch has evidence to grade against.
    submission_dir: Path | None = None
    if args.with_reproduce_plan:
        from reproduce_plan import generate_reproduce_plan_async  # type: ignore
        submission_dir = out_dir / "submission"
        print(f"\n[step4] generating reproduction package → {submission_dir}/")
        rp_res = asyncio.run(generate_reproduce_plan_async(
            paper_text=paper_text,
            output_dir=str(submission_dir),
            model=args.reproduce_plan_model,
            paperbench_rubric_id=rubric_template_id,
        ))
        if "error" in rp_res:
            print(f"[step4.error] {rp_res['error']}")
            if rp_res.get("warnings"):
                for w in rp_res["warnings"]:
                    print(f"  warn: {w}")
            return 1
        print(f"[step4] model={rp_res['model']}  wrote: "
              f"{', '.join(rp_res['files'])}")
        if rp_res.get("warnings"):
            for w in rp_res["warnings"]:
                print(f"  warn: {w}")

    # Detect paper_audit mode from the loaded template (auto-enable the
    # vendor prompt patch when the user picked a paper_audit YAML).
    paper_audit_mode = bool(args.paper_audit_mode)
    if rubric_template_id and not paper_audit_mode:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent / "ari-skill-replicate" / "src"))
            from rubric_template import load_paperbench_rubric  # type: ignore
            _t = load_paperbench_rubric(rubric_template_id)
            if _t.mode == "paper_audit":
                paper_audit_mode = True
                print(f"[hint] rubric-template {rubric_template_id!r} is mode=paper_audit; "
                      "enabling --paper-audit-mode automatically")
        except Exception as e:
            print(f"[warn] could not auto-detect template mode: {e}")

    if args.judge_dryrun:
        asyncio.run(run_judge_dryrun(
            envelope, paper_text, args.judge_model,
            submission_dir=submission_dir,
            paper_audit_mode=paper_audit_mode,
        ))

    print(f"\n[done] artifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
