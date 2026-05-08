"""Rubric generator: paper text -> PaperBench TaskNode-format rubric envelope."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import jsonschema

from categories import normalize_rubric_node
from manifest import compute_prompt_sha256, freeze

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "replication_rubric.schema.json"

DEFAULT_MODEL = "gemini/gemini-2.5-pro"
JSON_RETRY_LIMIT = 3
DEFAULT_TEMPERATURE = 0.0


def _model() -> str:
    return (
        os.environ.get("ARI_MODEL_RUBRIC_GEN")
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


def compute_target_leaf_count(paper_text: str) -> int:
    """PaperBench density (~1 leaf / 75 words), bounded to [50, 400]."""
    word_count = len(paper_text.split())
    target = word_count // 75
    return max(50, min(400, target))


def _load_prompt_template() -> str:
    return (PROMPTS_DIR / "adversarial_reviewer.md").read_text()


def _render_prompt(paper_text: str, target_leaves: int) -> str:
    tmpl = _load_prompt_template()
    return tmpl.replace("{TARGET_LEAVES}", str(target_leaves)).replace("{PAPER_TEXT}", paper_text)


def _render_skeleton_prompt(paper_text: str, target_leaves: int) -> str:
    tmpl = (PROMPTS_DIR / "skeleton.md").read_text()
    return tmpl.replace("{TARGET_LEAVES}", str(target_leaves)).replace("{PAPER_TEXT}", paper_text)


def _render_subtree_prompt(paper_text: str, parent_requirements: str, target_leaves: int) -> str:
    tmpl = (PROMPTS_DIR / "subtree.md").read_text()
    # Replace PARENT_REQUIREMENTS first; it appears twice in the template
    # (the explicit scope block and inside the OUTPUT FORMAT example).
    return (
        tmpl
        .replace("{PARENT_REQUIREMENTS}", parent_requirements)
        .replace("{TARGET_LEAVES}", str(target_leaves))
        .replace("{PAPER_TEXT}", paper_text)
    )


def _strip_thinking_and_fences(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()


_LATEX_ESCAPES_IN_JSON = re.compile(
    # Backslash followed by any character JSON does not accept as an escape.
    # Valid JSON escapes: \" \\ \/ \b \f \n \r \t \uXXXX. Everything else
    # (e.g. \(, \), \$, \texttt, \\(, \%, \&) is illegal in a JSON string.
    r'\\(?!["\\/bfnrtu])'
)


def _sanitize_latex_in_json(raw: str) -> str:
    """Best-effort: strip illegal backslash escapes inside JSON string values.

    LLMs that copy verbatim LaTeX into ``rationale_from_paper.quote`` produce
    output like ``"quote": "where \\(x\\)..."`` which json.loads rejects with
    ``Invalid \\escape``. This pass removes the offending backslashes,
    converting ``\\(x\\)`` → ``(x)`` and ``\\texttt{X}`` → ``texttt{X}`` so
    parsing succeeds. The substring is no longer LaTeX-faithful, but it is
    still a usable plain-text snippet for the judge prompt.
    """
    return _LATEX_ESCAPES_IN_JSON.sub("", raw)


def _extract_json_object(raw: str) -> dict | None:
    """Best-effort JSON object extraction from a model response."""
    raw = _strip_thinking_and_fences(raw)

    def _try_parse(s: str) -> dict | None:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    # Pass 1: as-is.
    obj = _try_parse(raw)
    if obj is not None:
        return obj
    # Pass 2: with LaTeX-backslash sanitation.
    sanitized = _sanitize_latex_in_json(raw)
    obj = _try_parse(sanitized)
    if obj is not None:
        return obj

    # Fallback: find outermost balanced braces in (preferentially) sanitized text.
    for candidate in (sanitized, raw):
        start = candidate.find("{")
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(candidate)):
            c = candidate[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    obj = _try_parse(candidate[start:i + 1])
                    if obj is not None:
                        return obj
                    break
    return None


def _ensure_uuid(node: Any) -> None:
    """Recursively force every node to have a valid UUID v4 string id."""
    if not isinstance(node, dict):
        return
    nid = node.get("id")
    try:
        if not isinstance(nid, str):
            raise ValueError
        uuid.UUID(nid)
    except (ValueError, AttributeError):
        node["id"] = str(uuid.uuid4())
    if "weight" in node:
        try:
            node["weight"] = int(node["weight"])
        except (TypeError, ValueError):
            node["weight"] = 1
    children = node.get("sub_tasks") or []
    for c in children:
        _ensure_uuid(c)
    node["sub_tasks"] = list(children)


def _collapse_single_child_chains(node: dict) -> None:
    """In-place: fold single-child non-leaf nodes into their child.

    Why: PaperBench SimpleJudge only grades leaves. A non-leaf with exactly
    one child is structurally degenerate — its requirement is never graded
    on its own, it just multiplies the child's weight. The LLM rubric
    generator occasionally emits these (typically a high-level claim wrapping
    a single "logged in reproduce.log" sub-criterion), losing the parent's
    actual claim.

    Collapse rule: keep the parent's id and weight; concatenate the parent's
    requirements with the child's; adopt the child's sub_tasks and any
    leaf-only metadata (task_category, finegrained_task_category,
    rationale_from_paper) the parent lacks. Iterate so chains of length > 2
    fully flatten.
    """
    if not isinstance(node, dict):
        return
    while True:
        children = node.get("sub_tasks") or []
        if len(children) != 1 or not isinstance(children[0], dict):
            break
        child = children[0]
        # Skip if the child is itself a leaf without further sub_tasks AND
        # the parent already carries its own gradeable text — collapsing is
        # still safe, but produces nicer output.
        parent_req = (node.get("requirements") or "").rstrip()
        child_req = (child.get("requirements") or "").strip()
        if parent_req and child_req and child_req not in parent_req:
            node["requirements"] = f"{parent_req} — {child_req}"
        elif child_req and not parent_req:
            node["requirements"] = child_req
        # Adopt child's structural children (may be empty → parent becomes leaf)
        node["sub_tasks"] = list(child.get("sub_tasks") or [])
        is_leaf_now = not node["sub_tasks"]
        # Leaf-only fields belong on leaves only. The grader rejects
        # non-leaves carrying ``task_category`` / ``finegrained_task_category``
        # / ``rationale_from_paper`` outright. Carry them over only when the
        # merged node ends up as a leaf; strip them otherwise so a
        # collapsed-into-non-leaf parent does not inherit them.
        if is_leaf_now:
            for k in ("task_category", "finegrained_task_category", "rationale_from_paper"):
                if k in child and not node.get(k):
                    node[k] = child[k]
        else:
            for k in ("task_category", "finegrained_task_category", "rationale_from_paper"):
                node.pop(k, None)
        # Loop: the merged node may itself be a single-child non-leaf now.
    for c in node.get("sub_tasks") or []:
        _collapse_single_child_chains(c)


_LEAF_ONLY_FIELDS = ("task_category", "finegrained_task_category", "rationale_from_paper")


def _strip_leaf_fields_from_non_leaves(node: dict) -> int:
    """Defensive: remove leaf-only fields from any non-leaf node, recursively.

    The PaperBench grader rejects non-leaves carrying ``task_category`` etc.
    The LLM occasionally emits such structures, and earlier post-processing
    passes may also leave them behind. This pass is independent of
    ``_collapse_single_child_chains`` so a structurally-correct rubric can
    still be sanitized in one place. Returns the count of stripped fields.
    """
    if not isinstance(node, dict):
        return 0
    stripped = 0
    children = node.get("sub_tasks") or []
    if children:
        for k in _LEAF_ONLY_FIELDS:
            if k in node:
                node.pop(k, None)
                stripped += 1
    for c in children:
        stripped += _strip_leaf_fields_from_non_leaves(c)
    return stripped


def _validate_envelope(env: dict) -> list[str]:
    """Return a list of jsonschema error messages, empty if valid."""
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errs = sorted(validator.iter_errors(env), key=lambda e: e.path)
    return [f"{list(e.absolute_path)}: {e.message}" for e in errs[:10]]


async def _llm_call(
    prompt: str, model: str, temperature: float | None, timeout: int
) -> str:
    import litellm

    # Some providers (e.g. gpt-5* family) reject ``temperature=0`` outright.
    # Drop unsupported params provider-side rather than 400'ing.
    litellm.drop_params = True

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": timeout,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    base = _api_base()
    if base:
        kwargs["api_base"] = base
    resp = await litellm.acompletion(**kwargs)
    return resp.choices[0].message.content or ""


def _summarize(env: dict) -> dict:
    leaves: list[dict] = []
    depth_max = [0]

    def walk(n: dict, depth: int) -> None:
        depth_max[0] = max(depth_max[0], depth)
        children = n.get("sub_tasks") or []
        if not children:
            leaves.append(n)
            return
        for c in children:
            walk(c, depth + 1)

    walk(env["rubric"], 0)
    by_cat: dict[str, int] = {}
    for n in leaves:
        cat = n.get("task_category") or "Uncategorized"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {
        "leaves_count": len(leaves),
        "depth": depth_max[0],
        "category_breakdown": by_cat,
    }


async def _call_and_parse(call, prompt: str) -> tuple[dict | None, str]:
    """Single LLM call with JSON extraction. Returns (parsed, error_msg)."""
    try:
        raw = await call(prompt)
    except Exception as e:
        return None, f"LLM call failed: {e}"
    parsed = _extract_json_object(raw)
    if parsed is None:
        return None, "could not parse JSON"
    return parsed, ""


async def _call_with_retry(call, prompt: str, label: str) -> tuple[dict | None, list[str]]:
    """Retry wrapper around _call_and_parse. Returns (parsed, errors)."""
    errors: list[str] = []
    for attempt in range(1, JSON_RETRY_LIMIT + 1):
        parsed, err = await _call_and_parse(call, prompt)
        if parsed is not None:
            return parsed, errors
        errors.append(f"{label} attempt {attempt}: {err}")
    return None, errors


def _extract_subtree_budgets(skeleton_root: dict, default_total: int) -> dict[str, int]:
    """Pop ``target_subtree_leaves`` from each direct child and return a map.

    Mutates the skeleton in place to remove the non-schema field. Children
    missing the hint get an even share of ``default_total``.
    """
    children = skeleton_root.get("sub_tasks") or []
    n = max(1, len(children))
    even = max(8, default_total // n)
    budgets: dict[str, int] = {}
    for c in children:
        nid = c.get("id") or ""
        budgets[nid] = int(c.pop("target_subtree_leaves", even) or even)
    return budgets


async def _generate_subtree(
    call, paper_text: str, parent_node: dict, target_leaves: int
) -> tuple[dict | None, list[str]]:
    """Generate one populated subtree for a single d2 node."""
    prompt = _render_subtree_prompt(
        paper_text=paper_text,
        parent_requirements=parent_node.get("requirements", ""),
        target_leaves=target_leaves,
    )
    parsed, errors = await _call_with_retry(call, prompt, label=f"subtree[{parent_node.get('id','?')[:8]}]")
    if parsed is None:
        return None, errors
    # The model returns a TaskNode (the parent populated). Validate shape.
    if not isinstance(parsed.get("sub_tasks"), list) or not parsed["sub_tasks"]:
        errors.append(f"subtree for '{parent_node.get('requirements','?')[:50]}' came back empty")
        return None, errors
    return parsed, errors


def _prune_invalid_leaves(node: dict) -> tuple[int, int]:
    """Drop leaves whose ``quote`` or ``requirements`` violate the schema's
    minLength=10. Recursively prune internal nodes that become childless.

    Returns (leaves_dropped, internal_dropped).
    """
    leaves_dropped = 0
    internal_dropped = 0
    children = node.get("sub_tasks") or []
    kept: list[dict] = []
    for c in children:
        ld, idr = _prune_invalid_leaves(c)
        leaves_dropped += ld
        internal_dropped += idr
        c_children = c.get("sub_tasks") or []
        if c_children:
            kept.append(c)
            continue
        # c is now a leaf (either originally, or after pruning).
        req = (c.get("requirements") or "").strip()
        rfp = c.get("rationale_from_paper") or {}
        quote = (rfp.get("quote") or "").strip() if isinstance(rfp, dict) else ""
        if len(req) < 10 or len(quote) < 10:
            # If c was originally an internal node that lost all children,
            # count as internal_dropped; otherwise it was an authored leaf.
            if children and not (c.get("rationale_from_paper") or {}).get("quote"):
                internal_dropped += 1
            else:
                leaves_dropped += 1
            continue
        kept.append(c)
    node["sub_tasks"] = kept
    return leaves_dropped, internal_dropped


async def _generate_two_stage(
    *,
    paper_text: str,
    target_total_leaves: int,
    call,
    subtree_concurrency: int = 4,
) -> tuple[dict | None, list[str]]:
    """Two-pass generation: skeleton → parallel subtrees → merge.

    Returns (envelope, errors). Envelope is unfrozen and unnormalized;
    caller must run normalize_rubric_node() and freeze().
    """
    errors: list[str] = []

    # ── Pass 1: skeleton ──
    skel_prompt = _render_skeleton_prompt(paper_text, target_total_leaves)
    skeleton, skel_errs = await _call_with_retry(call, skel_prompt, label="skeleton")
    errors.extend(skel_errs)
    if skeleton is None:
        return None, errors

    if not isinstance(skeleton.get("rubric"), dict):
        errors.append("skeleton missing 'rubric' root")
        return None, errors
    root = skeleton["rubric"]
    _ensure_uuid(root)
    children = root.get("sub_tasks") or []
    if not children:
        errors.append("skeleton produced 0 direct children")
        return None, errors

    budgets = _extract_subtree_budgets(root, target_total_leaves)

    # ── Pass 2: subtrees in parallel ──
    sem = asyncio.Semaphore(subtree_concurrency)

    async def _one(child: dict) -> tuple[dict, dict | None, list[str]]:
        async with sem:
            budget = budgets.get(child.get("id") or "", max(8, target_total_leaves // len(children)))
            sub, errs = await _generate_subtree(call, paper_text, child, budget)
            return child, sub, errs

    results = await asyncio.gather(*[_one(c) for c in children])

    # ── Merge ──
    merged_children: list[dict] = []
    for child, sub, errs in results:
        errors.extend(errs)
        if sub is None:
            # Keep the skeleton stub so the rubric still loads, but warn.
            errors.append(
                f"subtree for '{child.get('requirements','?')[:50]}' fell back to skeleton stub"
            )
            merged_children.append(child)
            continue
        # Subtree's root REPLACES the skeleton child (preserving id/weight from skeleton).
        sub["id"] = child.get("id") or sub.get("id") or str(uuid.uuid4())
        sub["weight"] = int(child.get("weight", sub.get("weight", 1)))
        sub["requirements"] = child.get("requirements", sub.get("requirements", ""))
        merged_children.append(sub)

    root["sub_tasks"] = merged_children
    return skeleton, errors


async def generate_rubric_async(
    *,
    paper_text: str,
    output_path: str,
    target_leaf_count: int = 0,
    model: str = "",
    temperature: float = DEFAULT_TEMPERATURE,
    seed: int | None = None,
    timeout_sec: int = 600,
    llm_call=None,  # injection point for tests
    two_stage: bool = False,
) -> dict:
    """Core async generator. ``llm_call`` (kwarg) overrides the litellm call.

    Returns a result dict with ``rubric_path``, ``rubric_sha256``,
    ``leaves_count``, ``depth``, ``category_breakdown``, and ``warnings``.
    """
    if not paper_text:
        return {"error": "empty paper_text", "warnings": ["empty paper_text"]}

    target = target_leaf_count or compute_target_leaf_count(paper_text)
    chosen_model = model or _model()
    prompt = _render_prompt(paper_text, target)

    call = llm_call or (lambda p: _llm_call(p, chosen_model, temperature, timeout_sec))

    last_errors: list[str] = []
    env: dict | None = None

    if two_stage:
        # ── Two-pass: skeleton → parallel subtrees → merge ──
        parsed, errs = await _generate_two_stage(
            paper_text=paper_text,
            target_total_leaves=target,
            call=call,
        )
        last_errors.extend(errs)
        if parsed is not None:
            if not isinstance(parsed.get("reproduce_contract"), dict):
                parsed["reproduce_contract"] = {"script_path": "reproduce.sh", "max_runtime_sec": 21600}
            rc = parsed["reproduce_contract"]
            rc.setdefault("script_path", "reproduce.sh")
            rc.setdefault("max_runtime_sec", 21600)
            _ensure_uuid(parsed["rubric"])
            ld, idr = _prune_invalid_leaves(parsed["rubric"])
            if ld or idr:
                last_errors.append(
                    f"two_stage pruned {ld} leaves and {idr} internal nodes "
                    f"with quote/requirements shorter than schema minimum"
                )
            cat_warnings = normalize_rubric_node(parsed["rubric"])
            if cat_warnings:
                last_errors.extend(f"category normalize: {w}" for w in cat_warnings)
            # Fold single-child non-leaf chains into their child so the
            # parent's claim becomes a graded leaf rather than an ungraded
            # weighting wrapper. Must run BEFORE freeze() — rubric_sha256
            # hashes the post-collapse tree.
            _collapse_single_child_chains(parsed["rubric"])
            # Defensive: ensure no non-leaf ends up carrying leaf-only
            # fields. The grader rejects them outright.
            _strip_leaf_fields_from_non_leaves(parsed["rubric"])
            # ``prompt`` is the legacy single-call template — record the
            # skeleton prompt's hash instead so provenance reflects the
            # actual primary template used.
            skel_prompt = _render_skeleton_prompt(paper_text, target)
            frozen = freeze(
                parsed,
                generator_model=chosen_model,
                prompt=skel_prompt,
                paper_text=paper_text,
                temperature=temperature,
                seed=seed,
            )
            schema_errs = _validate_envelope(frozen)
            if schema_errs:
                last_errors.append(f"two_stage schema errors: {schema_errs}")
            else:
                env = frozen
                prompt = skel_prompt  # for the prompt_sha256 result field
    else:
        for attempt in range(1, JSON_RETRY_LIMIT + 1):
            try:
                raw = await call(prompt)
            except Exception as e:
                last_errors.append(f"attempt {attempt}: LLM call failed: {e}")
                continue
            parsed = _extract_json_object(raw)
            if parsed is None:
                last_errors.append(f"attempt {attempt}: could not parse JSON")
                continue
            # Fill defaults / coerce
            if not isinstance(parsed.get("reproduce_contract"), dict):
                parsed["reproduce_contract"] = {"script_path": "reproduce.sh", "max_runtime_sec": 21600}
            rc = parsed["reproduce_contract"]
            rc.setdefault("script_path", "reproduce.sh")
            rc.setdefault("max_runtime_sec", 21600)
            if not isinstance(parsed.get("rubric"), dict):
                last_errors.append(f"attempt {attempt}: missing 'rubric' root")
                continue
            _ensure_uuid(parsed["rubric"])
            # Clamp every leaf's task/finegrained category to PaperBench's
            # closed vocabulary. Must run BEFORE freeze() — rubric_sha256 hashes
            # the post-normalization tree.
            cat_warnings = normalize_rubric_node(parsed["rubric"])
            if cat_warnings:
                last_errors.extend(f"category normalize: {w}" for w in cat_warnings)
            # Fold single-child non-leaf chains; see two-stage path above.
            _collapse_single_child_chains(parsed["rubric"])
            # Strip leaf-only fields from non-leaves; same rationale.
            _strip_leaf_fields_from_non_leaves(parsed["rubric"])
            # Freeze (adds version, paper_sha256, generator, rubric_sha256)
            frozen = freeze(
                parsed,
                generator_model=chosen_model,
                prompt=prompt,
                paper_text=paper_text,
                temperature=temperature,
                seed=seed,
            )
            errs = _validate_envelope(frozen)
            if errs:
                last_errors.append(f"attempt {attempt}: schema errors: {errs}")
                continue
            env = frozen
            break

    warnings: list[str] = []
    if env is None:
        return {
            "error": "rubric generation failed after retries",
            "warnings": last_errors,
            "model": chosen_model,
            "target_leaf_count": target,
        }

    summary = _summarize(env)
    if summary["leaves_count"] < max(10, target // 4):
        warnings.append(f"only {summary['leaves_count']} leaves produced (target {target})")
    if last_errors:
        warnings.extend(last_errors)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(env, indent=2, ensure_ascii=False))

    return {
        "rubric_path": str(out_path),
        "rubric_sha256": env["rubric_sha256"],
        "paper_sha256": env["paper_sha256"],
        "leaves_count": summary["leaves_count"],
        "depth": summary["depth"],
        "category_breakdown": summary["category_breakdown"],
        "target_leaf_count": target,
        "auto_computed_target": target_leaf_count == 0,
        "model": chosen_model,
        "prompt_sha256": compute_prompt_sha256(prompt),
        "warnings": warnings,
    }


def generate_rubric_sync(**kwargs: Any) -> dict:
    """Synchronous wrapper for tests / non-async callers."""
    return asyncio.run(generate_rubric_async(**kwargs))
