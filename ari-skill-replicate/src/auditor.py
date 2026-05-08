"""Rubric auditor: deterministic + LLM-assisted leaf quality flags."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from manifest import add_audit_metadata

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DEFAULT_MODEL = "anthropic/claude-opus-4-7"
REGEN_THRESHOLD = 0.20  # >20% leaves flagged → regen_recommended

# Operationalized "vague qualifier" tokens. Match whole words, case-insensitive.
VAGUE_TOKENS = (
    "appropriate",
    "appropriately",
    "well-organized",
    "well organized",
    "well-structured",
    "well structured",
    "well-",
    "clearly",
    "clear",
    "good",
    "proper",
    "properly",
    "reasonable",
    "reasonably",
    "decent",
    "nice",
)

VAGUE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in VAGUE_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _model() -> str:
    return (
        os.environ.get("ARI_MODEL_RUBRIC_AUDIT")
        or os.environ.get("ARI_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
        or DEFAULT_MODEL
    )


def _api_base() -> str | None:
    ari = os.environ.get("ARI_LLM_API_BASE")
    if ari is not None:
        return ari or None
    legacy = os.environ.get("LLM_API_BASE", "")
    if legacy:
        return legacy
    if _model().startswith("ollama"):
        return "http://127.0.0.1:11434"
    return None


# ─── traversal helpers ──────────────────────────────────────────────────


def iter_leaves(node: dict):
    """Depth-first iterator over leaves (sub_tasks empty)."""
    children = node.get("sub_tasks") or []
    if not children:
        yield node
        return
    for c in children:
        yield from iter_leaves(c)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


# ─── deterministic checks ───────────────────────────────────────────────


def detect_vague_qualifier(requirements: str) -> bool:
    return bool(VAGUE_RE.search(requirements or ""))


def detect_no_paper_evidence(leaf: dict, paper_text: str) -> bool:
    """True iff the leaf's verbatim quote is NOT a substring of the paper."""
    rfp = leaf.get("rationale_from_paper") or {}
    quote = rfp.get("quote") or ""
    if not quote.strip():
        return True
    paper_norm = _normalize_text(paper_text)
    return _normalize_text(quote) not in paper_norm


def detect_duplicates(leaves: list[dict]) -> set[str]:
    """Return the ids of leaves whose normalized requirements are duplicates."""
    seen: dict[str, str] = {}  # normalized text -> first id
    dup_ids: set[str] = set()
    for n in leaves:
        key = _normalize_text(n.get("requirements") or "")
        if not key:
            continue
        if key in seen:
            dup_ids.add(n["id"])
            dup_ids.add(seen[key])
        else:
            seen[key] = n.get("id", "")
    return dup_ids


def _add_flag(node: dict, flag: str) -> None:
    flags = node.get("flags") or []
    if flag not in flags:
        flags.append(flag)
    node["flags"] = flags


# ─── LLM-assisted check ─────────────────────────────────────────────────


def _render_audit_prompt(leaf: dict) -> str:
    tmpl = (PROMPTS_DIR / "rubric_audit.md").read_text()
    leaf_view = {k: leaf.get(k) for k in (
        "id", "requirements", "weight", "task_category",
        "finegrained_task_category", "rationale_from_paper",
    )}
    return tmpl.replace("{LEAF_JSON}", json.dumps(leaf_view, ensure_ascii=False, indent=2))


async def _llm_audit_leaf(prompt: str, model: str, timeout: int) -> dict:
    import litellm

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "timeout": timeout,
    }
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    raw = resp.choices[0].message.content or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    s, e = raw.find("{"), raw.rfind("}") + 1
    if s < 0 or e <= s:
        return {}
    try:
        return json.loads(raw[s:e])
    except json.JSONDecodeError:
        return {}


# ─── orchestrator ───────────────────────────────────────────────────────


async def audit_rubric_async(
    *,
    rubric_path: str,
    paper_text: str,
    auditor_model: str = "",
    timeout_sec: int = 60,
    llm_call=None,  # injection for tests; signature: (prompt) -> dict
) -> dict:
    """Audit rubric in-place. Mutates the rubric file, returns a summary."""
    chosen_model = auditor_model or _model()
    path = Path(rubric_path)
    rubric = json.loads(path.read_text())

    root = rubric.get("rubric")
    if not isinstance(root, dict):
        return {"error": "rubric envelope missing 'rubric' root"}

    leaves = list(iter_leaves(root))
    by_flag: dict[str, int] = {
        "vague_qualifier": 0,
        "no_paper_evidence": 0,
        "duplicate": 0,
        "unverifiable": 0,
    }

    # ── deterministic ──
    dup_ids = detect_duplicates(leaves)
    for leaf in leaves:
        req = leaf.get("requirements") or ""
        if detect_vague_qualifier(req):
            _add_flag(leaf, "vague_qualifier")
            by_flag["vague_qualifier"] += 1
        if paper_text and detect_no_paper_evidence(leaf, paper_text):
            _add_flag(leaf, "no_paper_evidence")
            by_flag["no_paper_evidence"] += 1
        if leaf.get("id") in dup_ids:
            _add_flag(leaf, "duplicate")
            by_flag["duplicate"] += 1

    # ── LLM-assisted ──
    if llm_call is not None or chosen_model:
        call = llm_call or (lambda p: _llm_audit_leaf(p, chosen_model, timeout_sec))
        for leaf in leaves:
            prompt = _render_audit_prompt(leaf)
            try:
                verdict = await call(prompt)
            except Exception as e:
                log.warning("auditor LLM failed for leaf %s: %s", leaf.get("id"), e)
                continue
            if not isinstance(verdict, dict):
                continue
            if verdict.get("vague_qualifier") and "vague_qualifier" not in (leaf.get("flags") or []):
                _add_flag(leaf, "vague_qualifier")
                by_flag["vague_qualifier"] += 1
            if verdict.get("unverifiable") and "unverifiable" not in (leaf.get("flags") or []):
                _add_flag(leaf, "unverifiable")
                by_flag["unverifiable"] += 1

    flagged = sum(1 for n in leaves if n.get("flags"))
    flags_count = sum(by_flag.values())
    add_audit_metadata(rubric, auditor_model=chosen_model, flags_count=flags_count)
    path.write_text(json.dumps(rubric, indent=2, ensure_ascii=False))

    regen_recommended = (flagged / max(1, len(leaves))) > REGEN_THRESHOLD
    return {
        "audited_path": str(path),
        "flags_count": flags_count,
        "by_flag": by_flag,
        "leaves_total": len(leaves),
        "leaves_flagged": flagged,
        "regen_recommended": regen_recommended,
        "auditor_model": chosen_model,
    }


def audit_rubric_sync(**kwargs: Any) -> dict:
    return asyncio.run(audit_rubric_async(**kwargs))
