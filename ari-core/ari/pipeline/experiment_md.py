"""experiment.md helpers (Phase 3C).

Pure functions extracted from the legacy ``ari/pipeline.py``:

- :func:`parse_metric_from_experiment_md` — pull the primary metric
  token from the ``Metrics:`` line of an experiment.md.
- :func:`_extract_plan_sections` — split a VirSci ``experiment_plan``
  into ``(tag, title, body)`` tuples (Markdown header / §-tag / bare
  numbered fallback).
- :func:`_build_auto_append_block` — render the auto-append block for
  ``checkpoint/experiment.md``.
- :func:`_promote_plan_to_experiment_md` — idempotently append the
  VirSci-derived plan block to a checkpoint's experiment.md.

The pipeline package's ``__init__.py`` re-exports these names so
existing ``from ari.pipeline import _extract_plan_sections`` paths
keep working.
"""

from __future__ import annotations

import re
from pathlib import Path


_AUTO_APPEND_BEGIN = "<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->"
_AUTO_APPEND_END = "<!-- END AUTO-APPENDED -->"


def parse_metric_from_experiment_md(text: str) -> str:
    """Parse the primary metric from an experiment.md ``Metrics:`` line.

    Used as the last-resort source for ``evaluation_criteria.json`` when the
    user pre-supplies an experiment description and the agent never invokes
    ``generate_ideas``. Returns the first metric token, e.g. ``"GB/s"`` from
    ``"Metrics: GB/s, GFlops/s"``. Returns ``""`` when no Metrics line is found.
    """
    if not text:
        return ""
    m = re.search(r"(?im)^\s*Metrics?\s*[:\-]\s*(.+)$", text)
    if not m:
        return ""
    raw = m.group(1).strip()
    first = re.split(r"[,\s]+", raw, maxsplit=1)[0].strip(" .;")
    return first


def _extract_plan_sections(plan_text: str) -> list[tuple[str, str, str]]:
    """Split a VirSci experiment_plan into (tag, title, body) tuples.

    Heading variants recognised, in priority order:

      1.  ``### N) Title``           — Markdown H3 with numbered prefix.
                                       VirSci's preferred top-level format.
      2.  ``## N) Title`` or ``# N)`` — other Markdown header levels.
      3.  ``§N Title`` / ``§N) Title``— legacy ARI-internal anchor.
      4.  ``N) Title`` / ``N. Title`` — bare-numbered enumeration at the
                                        line start (used inside narrative).

    Why priority matters: VirSci often emits Markdown headers ``### 1)
    Implementation plan`` AND, deeper inside the body, sub-step lists
    like ``1. Baseline kernel skeleton``. A naive regex that accepts only
    bare-numbered lines picks up the sub-steps and **silently swallows
    the top-level structure**, so callers see e.g. five "ablation step"
    entries instead of the actual five major sections (Implementation,
    Modeling, Validation, Ablation, Reproducibility).

    The fix: try the strongest pattern first (Markdown header) and only
    fall back to bare numbering when nothing strong was found.
    """
    if not plan_text or not plan_text.strip():
        return []

    # Strongest signal first: Markdown headers (H1/H2/H3) carrying a
    # numbered or §-tagged title. ``###`` wins because that's how
    # VirSci formats top-level plan sections in v0.6.x.
    md_pattern = re.compile(
        r"^\s*#{1,3}\s+(?:§\s*(?P<sym>\d+)|(?P<num>\d+))"
        r"\s*[\)\.\:]\s*(?P<title>.+?)\s*$",
        re.MULTILINE,
    )
    md_matches = list(md_pattern.finditer(plan_text))
    if md_matches:
        matches = md_matches
    else:
        # Fallback to bare numbering / §-tag at line start.
        bare_pattern = re.compile(
            r"^\s*(?:§\s*(?P<sym>\d+)|(?P<num>\d+))\s*[\)\.\:]\s*"
            r"(?P<title>.+?)\s*$",
            re.MULTILINE,
        )
        matches = list(bare_pattern.finditer(plan_text))
    if not matches:
        return [("§1", "Plan", plan_text.strip())]
    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        idx = m.group("sym") or m.group("num") or str(i + 1)
        tag = f"§{idx}"
        title = m.group("title").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_text)
        body = plan_text[start:end].strip()
        out.append((tag, title, body))
    return out


def _build_auto_append_block(idea_data: dict, mode: str = "index_only") -> str:
    """Render the auto-append block for checkpoint experiment.md.

    mode:
      - "index_only" (default): selected idea + §-tag titles + alternatives
      - "full"               : selected idea + plan §bodies + alternatives
      - "off"                : returns "" (caller should skip writing)
    """
    if mode == "off":
        return ""
    ideas = idea_data.get("ideas") or []
    if not ideas:
        return ""
    best = ideas[0]
    title = (best.get("title") or "").strip()
    score = best.get("overall_score", "")
    plan = (best.get("experiment_plan") or "").strip()
    sections = _extract_plan_sections(plan)

    lines: list[str] = [_AUTO_APPEND_BEGIN, "## Selected research idea"]
    lines.append(f"{title} (ideas[0], score {score})")

    if mode == "full":
        lines.append("")
        lines.append("## Detailed experiment plan")
        for tag, sec_title, body in sections:
            lines.append(f"### {tag} {sec_title}")
            lines.append(body)
            lines.append("")
    else:  # index_only
        lines.append("")
        lines.append("## Plan sections (full text in idea.json)")
        for tag, sec_title, _body in sections:
            lines.append(f"  {tag} {sec_title}")

    if len(ideas) > 1:
        lines.append("")
        lines.append("## Alternatives considered (not pursued in this run)")
        for i, alt in enumerate(ideas[1:], start=1):
            alt_title = (alt.get("title") or "").strip().replace("\n", " ")[:200]
            alt_score = alt.get("overall_score", "")
            lines.append(f"- ideas[{i}] (score {alt_score}): {alt_title}")

    lines.append(_AUTO_APPEND_END)
    return "\n".join(lines)


def _promote_plan_to_experiment_md(
    checkpoint_dir: str | Path, idea_data: dict, mode: str = "index_only"
) -> bool:
    """Append a VirSci-derived plan block to checkpoint/experiment.md.

    Idempotent: when the auto-append marker is already present, this is a
    no-op. The user's source experiment.md is never touched — only the
    in-checkpoint copy is enriched.

    Returns True iff the file was modified.
    """
    if mode == "off":
        return False
    ckpt = Path(checkpoint_dir)
    exp_md = ckpt / "experiment.md"
    text = exp_md.read_text() if exp_md.exists() else ""
    if _AUTO_APPEND_BEGIN in text:
        return False  # already promoted; idempotent
    block = _build_auto_append_block(idea_data, mode=mode)
    if not block:
        return False
    new_text = (text.rstrip() + "\n\n" + block + "\n") if text else (block + "\n")
    exp_md.write_text(new_text)
    return True
