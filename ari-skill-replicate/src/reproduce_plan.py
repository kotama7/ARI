"""Step 4 reproduction-package generator.

Reads a paper (and optional AD/AE Appendix concatenation) and asks an
LLM to produce four artifacts that downstream paper-audit judges can
consume:

  - ``reproduce_plan.md``     — step-by-step reconstruction guide with
                                  per-experiment reproducibility category.
  - ``verification_code.py``  — Python stubs that cross-check paper claims
                                  against simulated execution output.
  - ``install_commands.txt``  — concrete shell commands extracted from
                                  the paper / AD / AE.
  - ``reproduce.log``         — a simulated execution log built from the
                                  paper's own reported numbers, so the
                                  vendor SimpleJudge's "Result Analysis"
                                  branch has evidence to grade against.

Generality
~~~~~~~~~~

The bundled ``prompts/reproduce_plan.md`` is domain-agnostic. Venue
specifics (HPC SLURM params, NeurIPS hyperparameter checklist, Nature
wet-lab protocol categories, etc.) come from
``ari-core/config/paperbench_rubrics/<id>.yaml``'s
``prompt_overrides.reproduce_plan_hint`` field via the same
``{VENUE_HINT}`` placeholder used by the rubric generator. No
HPC-specific text lives in this module or its prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from rubric_template import (
    PaperBenchRubricTemplate,
    build_skeleton_venue_hint,
    load_paperbench_rubric,
)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_PATH = PROMPTS_DIR / "reproduce_plan.md"

DEFAULT_MODEL_ENV_VARS = (
    "ARI_MODEL_REPRODUCE_PLAN",
    "ARI_MODEL_REPLICATE",
    "ARI_LLM_MODEL",
    "LLM_MODEL",
)
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TEMPERATURE = 0.0
JSON_RETRY_LIMIT = 3

# Order matters — writes to disk under these basenames.
OUTPUT_FILES = (
    ("reproduce_plan_md", "reproduce_plan.md"),
    ("verification_code_py", "verification_code.py"),
    ("install_commands_txt", "install_commands.txt"),
    ("reproduce_log_sim", "reproduce.log"),
)


# ── prompt rendering ──────────────────────────────────────────────────────


def _render_prompt(paper_text: str, template: PaperBenchRubricTemplate | None) -> str:
    tmpl = PROMPT_PATH.read_text(encoding="utf-8")
    if template:
        venue_hint = _build_reproduce_plan_hint(template)
    else:
        venue_hint = ""
    return tmpl.replace("{VENUE_HINT}", venue_hint).replace("{PAPER_TEXT}", paper_text)


def _build_reproduce_plan_hint(template: PaperBenchRubricTemplate) -> str:
    """Compose the venue-conditioned hint block injected into the prompt.

    Mirrors ``build_skeleton_venue_hint`` but pulls the
    ``prompt_overrides.reproduce_plan_hint`` field (or falls back to
    ``system_hint`` so the user can keep their YAML minimal). When both
    are empty, returns an empty string and the bundled prompt runs
    verbatim.
    """
    hint = (
        template.prompt_overrides.reproduce_plan_hint
        or template.prompt_overrides.system_hint
        or ""
    ).strip()
    if not hint:
        return ""
    return (
        "=================================================================\n"
        f"VENUE OVERRIDE: {template.venue} (reproduce-plan generator)\n"
        "=================================================================\n\n"
        f"{hint}\n\n"
        "Apply this venue-specific guidance in addition to the GLOBAL\n"
        "RULES below. When the venue mandates an audit category not\n"
        "present in the default list, add it to the per-experiment\n"
        "`Reproducibility category` field.\n\n"
        "=================================================================\n"
    )


# ── JSON extraction (shared with generator.py shape) ─────────────────────


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_envelope(raw: str) -> str:
    raw = _THINK_RE.sub("", raw).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()


def _extract_json_object(raw: str) -> dict | None:
    raw = _strip_envelope(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try outermost balanced braces
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _model() -> str:
    for env in DEFAULT_MODEL_ENV_VARS:
        v = os.environ.get(env)
        if v:
            return v
    return DEFAULT_MODEL


def _api_base() -> str | None:
    v = os.environ.get("ARI_LLM_API_BASE") or os.environ.get("LLM_API_BASE")
    return v.strip() or None if v else None


async def _llm_call(prompt: str, model: str, temperature: float, timeout_sec: int) -> str:
    """Provider-neutral chat call via LiteLLM (same envelope as generator.py)."""
    import litellm  # type: ignore

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "timeout": timeout_sec,
        # 4 multi-KB artifacts fit comfortably in 32K output; without this,
        # LiteLLM's default cap can truncate the last field and the LLM
        # emits a short placeholder.
        "max_tokens": 32768,
    }
    api_base = _api_base()
    if api_base:
        kwargs["api_base"] = api_base
    resp = await litellm.acompletion(**kwargs)
    return resp.choices[0].message.content or ""


# ── public API ────────────────────────────────────────────────────────────


async def generate_reproduce_plan_async(
    *,
    paper_text: str,
    output_dir: str,
    model: str = "",
    temperature: float = DEFAULT_TEMPERATURE,
    timeout_sec: int = 600,
    llm_call=None,  # injection point for tests
    paperbench_rubric_id: str | None = None,
) -> dict:
    """Generate the Step 4 reproduction package from a paper.

    Writes four files under ``output_dir``:

      reproduce_plan.md
      verification_code.py
      install_commands.txt
      reproduce.log

    These mirror what a fictional ``submission_dir`` would contain after a
    successful reproduction; pass ``output_dir`` as ``submission_dir`` to
    ``judge_submission`` so the vendor SimpleJudge's ``Result Analysis``
    branch has evidence to grade against.

    Returns ``{"output_dir", "files", "model", "warnings"}`` on success
    or ``{"error", ...}`` on terminal failure.
    """
    if not paper_text:
        return {"error": "empty paper_text"}
    template: PaperBenchRubricTemplate | None = None
    if paperbench_rubric_id:
        template = load_paperbench_rubric(paperbench_rubric_id)

    chosen_model = model or _model()
    prompt = _render_prompt(paper_text, template)
    call = llm_call or (lambda p: _llm_call(p, chosen_model, temperature, timeout_sec))

    warnings: list[str] = []
    parsed: dict | None = None
    for attempt in range(1, JSON_RETRY_LIMIT + 1):
        try:
            raw = await call(prompt)
        except Exception as e:
            warnings.append(f"attempt {attempt}: LLM call failed: {e}")
            continue
        parsed = _extract_json_object(raw)
        if parsed is None:
            warnings.append(f"attempt {attempt}: could not parse JSON envelope")
            continue
        missing = [k for k, _ in OUTPUT_FILES if k not in parsed]
        if missing:
            warnings.append(
                f"attempt {attempt}: missing keys {missing} in envelope"
            )
            parsed = None
            continue
        # Content-quality validation: each field needs at least ~150 chars
        # of meaningful content. The LLM sometimes emits a placeholder
        # string when it hits its internal output limit while serialising
        # a long field — we treat that as a retry-worthy partial response.
        too_short = [
            k for k, _ in OUTPUT_FILES
            if len(str(parsed.get(k) or "").strip()) < 150
        ]
        if too_short:
            warnings.append(
                f"attempt {attempt}: fields {too_short} are too short "
                f"(likely truncated or placeholder) — retrying"
            )
            parsed = None
            continue
        break

    if parsed is None:
        return {
            "error": "reproduce_plan generation failed after retries",
            "warnings": warnings,
            "model": chosen_model,
        }

    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for key, fname in OUTPUT_FILES:
        body = str(parsed.get(key) or "").rstrip() + "\n"
        path = out / fname
        path.write_text(body, encoding="utf-8")
        written[fname] = str(path)

    return {
        "output_dir": str(out),
        "files": written,
        "model": chosen_model,
        "warnings": warnings,
        "paperbench_rubric_id": paperbench_rubric_id or "",
    }


def generate_reproduce_plan_sync(**kwargs: Any) -> dict:
    """Synchronous wrapper for tests / non-async callers."""
    return asyncio.run(generate_reproduce_plan_async(**kwargs))
