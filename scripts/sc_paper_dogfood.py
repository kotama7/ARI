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
    code_only: bool = False,
) -> None:
    """Pipe the generated rubric into judge_submission.

    When ``submission_dir`` is supplied (a real PaperBench Step 2
    executed submission directory), the judge grades against it;
    otherwise an empty tempdir is used and ``Result Analysis`` leaves
    cannot score (which is the correct behaviour — empty submission
    means no reproduction was performed).

    ``paper_audit_mode`` swaps the vendor's submission-oriented
    TASK_CATEGORY_QUESTIONS to paper-audit flavors (see
    ``ari-skill-paper-re/src/_paperbench_bridge.py``). Required for
    paper_audit-mode templates so leaves phrased as "X is identifiable
    in the paper" are graded correctly.

    ``code_only`` prunes the rubric to Code Development leaves only
    (vendor :meth:`TaskNode.code_only`). Use when Stage 2 was skipped
    so the grader's scope matches the agent's instructions (Stage 1
    code_only=True). Mutually exclusive with ``paper_audit_mode``.
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
              f"code_only={code_only}  "
              f"submission={submission_dir} (files: {files or '<empty>'})")
        graded = await judge_submission(
            paper_md=paper_text,
            rubric=rubric_node,
            submission_dir=submission_dir,
            reproduce_log="",
            judge_model=judge_model,
            paper_audit_mode=paper_audit_mode,
            code_only=code_only,
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
    ap.add_argument("--paper-audit-mode", action="store_true",
                    help="Patch vendor SimpleJudge's TASK_CATEGORY_QUESTIONS "
                         "to paper-audit-flavored questions during judge "
                         "(see ari-skill-paper-re/src/_paperbench_bridge.py). "
                         "Without this, the vendor's submission-oriented "
                         "questions cap the score around 0.3 for paper_audit "
                         "mode templates. Auto-enabled when "
                         "--rubric-template is a paper_audit template. "
                         "MUTUALLY EXCLUSIVE with --with-reproduction: paper-"
                         "audit-mode is for paper-only grading where there is "
                         "no executed submission to grade against.")
    # ── PaperBench Stage 1 / Stage 2 (real execution) ──
    # These drive bridge.rollout_submission / bridge.reproduce_submission.
    # They are the legitimate counterpart to the deleted (off-protocol)
    # --with-reproduce-plan flag; the submission_dir grading uses below
    # comes from real agent rollout + real reproduce.sh execution, NOT
    # from an LLM transcribing paper numbers.
    ap.add_argument("--with-rollout", action="store_true",
                    help="Stage 1: drive a PaperBench-style BasicAgent rollout "
                         "via bridge.rollout_submission to write reproduce.sh "
                         "into <out>/submission/. Requires --rollout-model "
                         "or env ARI_MODEL_REPLICATOR.")
    ap.add_argument("--rollout-model", default="",
                    help="LLM for the Stage 1 agent. Empty = inherit "
                         "ARI_MODEL_REPLICATOR env or fall back to --judge-model.")
    ap.add_argument("--rollout-time-limit-sec", type=int, default=3600,
                    help="Wall-clock budget for Stage 1 (default 1 h for "
                         "dogfood; PaperBench upstream BasicAgent default is "
                         "12 h, IterativeAgent up to 36 h).")
    ap.add_argument("--rollout-sandbox", default="local",
                    help="Stage 1 sandbox_kind: local | apptainer | slurm. "
                         "Default 'local' (host filesystem). 'slurm' assumes "
                         "ari is already inside an allocation (host exec, "
                         "no container — a one-shot warning is emitted).")
    ap.add_argument("--rollout-container-image", default="",
                    help="Stage 1 container image (SIF path or docker://... "
                         "URI). Only used when --rollout-sandbox=apptainer.")
    ap.add_argument("--iterative-agent", action="store_true",
                    help="Stage 1: switch to PaperBench's IterativeAgent "
                         "variant (paper §5.3): no submit-tool early "
                         "termination, step-by-step prompting.")
    ap.add_argument("--module-loads", default="",
                    help="Comma-separated Lmod module names to pre-load "
                         "before spawning the agent's subprocess (e.g., "
                         "`system/ai-l40s,nvhpc`). The bridge runs "
                         "`bash -lc \"module load $X1 $X2; env -0\"` in a "
                         "probe subprocess and merges the resulting env "
                         "diff into the agent's env, so the agent's "
                         "bash/python tools inherit nvcc / mpicc / hdf5 / "
                         "etc on PATH from the start. Without this the "
                         "agent has to discover and `module load` "
                         "interactively (often fails to — see SC41406 "
                         "dogfood). Best-effort: silently skipped if "
                         "module command is unavailable.")
    ap.add_argument("--blacklist-urls", default="",
                    help="Comma-separated URLs/domains the agent must NOT "
                         "fetch during Stage 1 rollout (forbidden URLs / "
                         "resources). Plumbed through to "
                         "bridge.rollout_submission(blacklist_urls=...). "
                         "Note: ARI lifts the vendor's default paper-codebase "
                         "blacklist (see bridge `_install_blacklist_lift_patch`); "
                         "use this flag to ADD specific URLs the agent should "
                         "still avoid (e.g., a competitor's proprietary "
                         "dataset, a downstream evaluation server). Example: "
                         "`--blacklist-urls https://github.com/foo/bar,"
                         "https://example.com/secret-dataset`.")
    ap.add_argument("--with-reproduction", action="store_true",
                    help="Stage 2: execute the submission's reproduce.sh in "
                         "the chosen sandbox via bridge.reproduce_submission "
                         "and feed the executed submission to the judge. "
                         "Implies --with-rollout if not also passed (cannot "
                         "execute a non-existent reproduce.sh). MUTUALLY "
                         "EXCLUSIVE with --paper-audit-mode.")
    ap.add_argument("--reproduce-sandbox", default="local",
                    help="Stage 2 sandbox_kind: local | docker | apptainer | "
                         "singularity | slurm. Default 'local'.")
    ap.add_argument("--reproduce-container-image", default="",
                    help="Stage 2 container image. For sandbox=docker an "
                         "image:tag; for apptainer/singularity an .sif path "
                         "or docker://... URI. When empty, falls back to "
                         "ARI_PHASE1_DOCKER_IMAGE / "
                         "ARI_PHASE1_APPTAINER_IMAGE env or ubuntu:24.04.")
    ap.add_argument("--reproduce-time-limit-sec", type=int, default=1800,
                    help="Wall-clock budget for Stage 2 reproduce.sh "
                         "(default 30 min for dogfood).")
    ap.add_argument("--reproduce-partition", default="",
                    help="Stage 2 SLURM partition (only when "
                         "--reproduce-sandbox=slurm).")
    ap.add_argument("--reproduce-gpus-per-task", type=int, default=0,
                    help="Stage 2 SLURM --gpus-per-task (will fail loud at "
                         "submit if the cluster has no GRES configured; set "
                         "env ARI_SLURM_ALLOW_NO_GRES=1 to silently drop).")
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

    # Stage 1 (agent rollout) + Stage 2 (reproduce.sh execution) — the
    # legitimate PaperBench 3-stage protocol. Without these flags, the
    # judge below runs against an empty submission, so Result Analysis
    # category leaves will score 0 — that is the correct behaviour when
    # nothing was actually reproduced.
    submission_dir: Path | None = None

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

    # --with-reproduction is for grading an *executed* submission; paper-
    # audit mode flips the judge's prompt to grade the paper itself. The
    # two are mutually exclusive — using both would feed an executed
    # reproduction to a judge asking "is the paper specific enough?",
    # which is meaningless.
    if args.with_reproduction and paper_audit_mode:
        print(
            "error: --with-reproduction is mutually exclusive with "
            "--paper-audit-mode (and with paper_audit rubric templates "
            f"such as {rubric_template_id!r}). Drop one of:\n"
            "  - --paper-audit-mode (and switch to a non-paper-audit "
            "rubric template) to grade an executed submission\n"
            "  - --with-reproduction to grade the paper itself for "
            "describability",
            file=sys.stderr,
        )
        return 2

    # --with-reproduction needs a populated submission_dir; if the user
    # did not also pass --with-rollout, we have no reproduce.sh to run.
    if args.with_reproduction and not args.with_rollout:
        print(
            "[hint] --with-reproduction passed without --with-rollout; "
            "enabling --with-rollout (cannot execute a non-existent "
            "reproduce.sh)"
        )
        args.with_rollout = True

    if args.with_rollout:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent / "ari-skill-paper-re" / "src"))
        from _paperbench_bridge import rollout_submission  # type: ignore
        submission_dir = out_dir / "submission"
        rollout_model = (
            args.rollout_model
            or os.environ.get("ARI_MODEL_REPLICATOR")
            or args.judge_model
        )
        print(f"\n[stage1] rollout: model={rollout_model} "
              f"sandbox={args.rollout_sandbox} "
              f"image={args.rollout_container_image or '<none>'} "
              f"time_limit={args.rollout_time_limit_sec}s "
              f"iterative={args.iterative_agent} → {submission_dir}/")
        rollout_res = asyncio.run(rollout_submission(
            paper_md=paper_text,
            work_dir=submission_dir,
            agent_model=rollout_model,
            time_limit_sec=args.rollout_time_limit_sec,
            iterative_agent=args.iterative_agent,
            sandbox_kind=args.rollout_sandbox,
            container_image=args.rollout_container_image,
            blacklist_urls=[
                u.strip() for u in (args.blacklist_urls or "").split(",")
                if u.strip()
            ] or None,
            module_loads=[
                m.strip() for m in (args.module_loads or "").split(",")
                if m.strip()
            ] or None,
        ))
        print(f"[stage1] populated={rollout_res.get('populated')} "
              f"agent_runtime_sec={rollout_res.get('agent_runtime_sec')} "
              f"files={rollout_res.get('files') or []}")
        for w in rollout_res.get("warnings") or []:
            print(f"  warn: {w}")

    if args.with_reproduction:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent / "ari-skill-paper-re" / "src"))
        from _paperbench_bridge import reproduce_submission  # type: ignore
        assert submission_dir is not None  # set above when --with-rollout
        print(f"\n[stage2] reproduce: sandbox={args.reproduce_sandbox} "
              f"image={args.reproduce_container_image or '<none>'} "
              f"time_limit={args.reproduce_time_limit_sec}s "
              f"partition={args.reproduce_partition or '<none>'} "
              f"gpus_per_task={args.reproduce_gpus_per_task} "
              f"→ {submission_dir}/")
        try:
            reproduce_res = asyncio.run(reproduce_submission(
                submission_dir=submission_dir,
                sandbox_kind=args.reproduce_sandbox,
                container_image=args.reproduce_container_image,
                time_limit_sec=args.reproduce_time_limit_sec,
                partition=args.reproduce_partition,
                gpus_per_task=args.reproduce_gpus_per_task,
            ))
        except RuntimeError as e:
            print(f"[stage2.error] {e}", file=sys.stderr)
            return 1
        print(f"[stage2] executed={reproduce_res.get('executed')} "
              f"exit_code={reproduce_res.get('exit_code')} "
              f"elapsed_sec={reproduce_res.get('elapsed_sec')} "
              f"log={reproduce_res.get('reproduce_log_path')}")

    # Auto-enable judge code_only when Stage 2 was skipped — the agent
    # was told to "only write code" (Stage 1 code_only=True is the ARI
    # default per _compute/local_pbtask.py:166-175), and grading
    # Code Execution / Result Analysis leaves against an empty
    # submission would systematically zero them via the vendor's
    # ``reproduce.sh failed to modify or create any files`` safeguard.
    # paper_audit_mode and code_only are mutually exclusive (the bridge
    # asserts) — paper_audit wins when both would apply (the user
    # explicitly picked a paper_audit template / flag).
    code_only = (
        args.with_rollout
        and not args.with_reproduction
        and not paper_audit_mode
    )
    if code_only:
        print(
            "[hint] --with-rollout without --with-reproduction → judge will run "
            "in code_only mode (rubric pruned to Code Development leaves only) "
            "to match the Stage 1 'write code, do not execute' instruction. "
            "Pass --with-reproduction to grade against an executed submission."
        )

    if args.judge_dryrun:
        asyncio.run(run_judge_dryrun(
            envelope, paper_text, args.judge_model,
            submission_dir=submission_dir,
            paper_audit_mode=paper_audit_mode,
            code_only=code_only,
        ))

    print(f"\n[done] artifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
