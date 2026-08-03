"""Rubric generator: paper text -> PaperBench TaskNode-format rubric envelope."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import jsonschema

from categories import normalize_rubric_node
from manifest import compute_paper_sha256, compute_prompt_sha256, freeze
from rubric_template import (
    PaperBenchRubricTemplate,
    build_skeleton_venue_hint,
    load_paperbench_rubric,
)
from provenance import (
    ModelCallBudgetExceeded,
    ProvenanceRecorder,
    RepairLedger,
)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "replication_rubric.schema.json"

DEFAULT_MODEL = "gemini/gemini-2.5-pro"
JSON_RETRY_LIMIT = 3
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_MODEL_CALLS = 64
DEFAULT_SUBTREE_CONCURRENCY = 4


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


def _provider(model: str) -> str:
    explicit = os.environ.get("ARI_MODEL_RUBRIC_GEN_PROVIDER", "").strip()
    if explicit:
        return explicit
    return model.split("/", 1)[0] if "/" in model else "unknown"


def _model_revision() -> str | None:
    return os.environ.get("ARI_MODEL_RUBRIC_GEN_REVISION", "").strip() or None


def compute_target_leaf_count(paper_text: str) -> int:
    """PaperBench density (~1 leaf / 75 words), bounded to [50, 400]."""
    word_count = len(paper_text.split())
    target = word_count // 75
    return max(50, min(400, target))


def _render_skeleton_prompt(
    paper_text: str,
    target_leaves: int,
    template: PaperBenchRubricTemplate | None = None,
) -> str:
    tmpl = (PROMPTS_DIR / "skeleton.md").read_text()
    venue_hint = build_skeleton_venue_hint(template) if template else ""
    return (
        tmpl.replace("{VENUE_HINT}", venue_hint)
        .replace("{TARGET_LEAVES}", str(target_leaves))
        .replace("{PAPER_TEXT}", paper_text)
    )


def _render_subtree_prompt(
    paper_text: str,
    parent_requirements: str,
    target_leaves: int,
    template: PaperBenchRubricTemplate | None = None,
) -> str:
    tmpl = (PROMPTS_DIR / "subtree.md").read_text()
    # The leaf_style override only applies to the subtree pass — paper_audit
    # rubrics need leaves phrased as YES/NO audit questions, not as commands
    # the submission performs.
    if template:
        leaf_style = (template.prompt_overrides.leaf_style or "").strip()
        if leaf_style:
            venue_hint = (
                "=================================================================\n"
                f"VENUE OVERRIDE: {template.venue}  (subtree leaf style)\n"
                "=================================================================\n\n"
                f"{leaf_style}\n\n"
                "=================================================================\n"
            )
        else:
            venue_hint = ""
    else:
        venue_hint = ""
    # Replace PARENT_REQUIREMENTS first; it appears twice in the template
    # (the explicit scope block and inside the OUTPUT FORMAT example).
    return (
        tmpl.replace("{VENUE_HINT}", venue_hint)
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


def _extract_json_object(
    raw: str, repair_notes: list[str] | None = None
) -> dict | None:
    """Best-effort JSON object extraction from a model response."""
    original = raw
    raw = _strip_thinking_and_fences(raw)
    if repair_notes is not None and raw != original.strip():
        repair_notes.append(
            "removed model thinking or Markdown fences before JSON parsing"
        )

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
        if repair_notes is not None:
            repair_notes.append(
                "removed invalid LaTeX backslash escapes before JSON parsing"
            )
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
                    obj = _try_parse(candidate[start : i + 1])
                    if obj is not None:
                        if repair_notes is not None:
                            repair_notes.append(
                                "extracted the outermost JSON object from model prose"
                            )
                        return obj
                    break
    return None


def _ensure_uuid(
    node: Any,
    path: str = "root",
    seen: set[str] | None = None,
) -> None:
    """Recursively force stable UUID identities without random repair."""
    if not isinstance(node, dict):
        return
    seen = seen if seen is not None else set()
    nid = node.get("id")
    try:
        if not isinstance(nid, str):
            raise ValueError
        uuid.UUID(nid)
        if nid in seen:
            raise ValueError
    except (ValueError, AttributeError):
        identity_payload = json.dumps(
            {
                "path": path,
                "requirements": node.get("requirements", ""),
                "weight": node.get("weight", 1),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        node["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, identity_payload))
    seen.add(node["id"])
    if "weight" in node:
        try:
            node["weight"] = int(node["weight"])
        except (TypeError, ValueError):
            node["weight"] = 1
    children = node.get("sub_tasks") or []
    for index, c in enumerate(children):
        _ensure_uuid(c, f"{path}/{index}", seen)
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
            for k in (
                "task_category",
                "finegrained_task_category",
                "rationale_from_paper",
            ):
                if k in child and not node.get(k):
                    node[k] = child[k]
        else:
            for k in (
                "task_category",
                "finegrained_task_category",
                "rationale_from_paper",
            ):
                node.pop(k, None)
        # Loop: the merged node may itself be a single-child non-leaf now.
    for c in node.get("sub_tasks") or []:
        _collapse_single_child_chains(c)


_LEAF_ONLY_FIELDS = (
    "task_category",
    "finegrained_task_category",
    "rationale_from_paper",
)


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


async def _call_and_parse(
    call,
    prompt: str,
    label: str,
    parse_repairs: list[tuple[str, str, str, dict]],
) -> tuple[dict | None, str]:
    """Single LLM call with JSON extraction. Returns (parsed, error_msg)."""
    try:
        raw = await call(prompt, label)
    except ModelCallBudgetExceeded as exc:
        return None, f"model-call budget exhausted: {exc}"
    except Exception as e:
        return None, f"LLM call failed: {e}"
    notes: list[str] = []
    parsed = _extract_json_object(raw, notes)
    if parsed is None:
        return None, "could not parse JSON"
    for note in notes:
        parse_repairs.append((label, note, raw, copy.deepcopy(parsed)))
    return parsed, ""


async def _call_with_retry(
    call,
    prompt: str,
    label: str,
    parse_repairs: list[tuple[str, str, str, dict]],
) -> tuple[dict | None, list[str]]:
    """Retry wrapper around _call_and_parse. Returns (parsed, errors)."""
    errors: list[str] = []
    for attempt in range(1, JSON_RETRY_LIMIT + 1):
        parsed, err = await _call_and_parse(
            call,
            prompt,
            f"{label}.attempt-{attempt}",
            parse_repairs,
        )
        if parsed is not None:
            return parsed, errors
        errors.append(f"{label} attempt {attempt}: {err}")
        if "budget exhausted" in err:
            break
    return None, errors


def _extract_subtree_budgets(skeleton_root: dict, default_total: int) -> list[int]:
    """Read per-child generation budgets without mutating model output.

    The hints disappear when populated subtrees replace skeleton stubs. Failed
    stubs are pruned during preparation, so every persisted mutation remains
    visible in the repair ledger.
    """
    children = skeleton_root.get("sub_tasks") or []
    n = max(1, len(children))
    even = max(8, default_total // n)
    budgets: list[int] = []
    for c in children:
        budgets.append(int(c.get("target_subtree_leaves", even) or even))
    return budgets


async def _generate_subtree(
    call,
    paper_text: str,
    parent_node: dict,
    target_leaves: int,
    parse_repairs: list[tuple[str, str, str, dict]],
    template: PaperBenchRubricTemplate | None = None,
) -> tuple[dict | None, list[str]]:
    """Generate one populated subtree for a single d2 node."""
    prompt = _render_subtree_prompt(
        paper_text=paper_text,
        parent_requirements=parent_node.get("requirements", ""),
        target_leaves=target_leaves,
        template=template,
    )
    parsed, errors = await _call_with_retry(
        call,
        prompt,
        label=f"subtree-{parent_node.get('id', '?')[:8]}",
        parse_repairs=parse_repairs,
    )
    if parsed is None:
        return None, errors
    # The model returns a TaskNode (the parent populated). Validate shape.
    if not isinstance(parsed.get("sub_tasks"), list) or not parsed["sub_tasks"]:
        errors.append(
            f"subtree for '{parent_node.get('requirements', '?')[:50]}' came back empty"
        )
        return None, errors
    return parsed, errors


def _prune_invalid_leaves(
    node: dict,
    dropped: list[dict] | None = None,
    path: str = "root",
) -> tuple[int, int]:
    """Drop leaves whose ``quote`` or ``requirements`` violate the schema's
    minLength=10. Recursively prune internal nodes that become childless.

    Returns (leaves_dropped, internal_dropped).
    """
    leaves_dropped = 0
    internal_dropped = 0
    children = node.get("sub_tasks") or []
    kept: list[dict] = []
    for index, c in enumerate(children):
        ld, idr = _prune_invalid_leaves(c, dropped, f"{path}/{index}")
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
            if dropped is not None:
                dropped.append(
                    {"path": f"{path}/{len(kept)}", "node": copy.deepcopy(c)}
                )
            continue
        kept.append(c)
    node["sub_tasks"] = kept
    return leaves_dropped, internal_dropped


def _normalized_text_with_positions(text: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    in_space = False
    for index, character in enumerate(text):
        if character.isspace():
            if normalized and not in_space:
                normalized.append(" ")
                positions.append(index)
            in_space = True
            continue
        for lowered in character.casefold():
            normalized.append(lowered)
            positions.append(index)
        in_space = False
    if normalized and normalized[-1] == " ":
        normalized.pop()
        positions.pop()
    return "".join(normalized), positions


def _paper_span(paper_text: str, quote: str) -> tuple[int, int, str] | None:
    direct = paper_text.find(quote)
    if direct >= 0:
        return direct, direct + len(quote), quote
    normalized_paper, positions = _normalized_text_with_positions(paper_text)
    normalized_quote, _ = _normalized_text_with_positions(quote)
    start = normalized_paper.find(normalized_quote)
    if start < 0 or not normalized_quote:
        return None
    end_position = start + len(normalized_quote) - 1
    original_start = positions[start]
    original_end = positions[end_position] + 1
    return original_start, original_end, paper_text[original_start:original_end]


def _default_verification(node: dict, expected_artifacts: list[str]) -> dict:
    category = node.get("task_category")
    requirement = re.sub(r"\s+", " ", str(node.get("requirements") or "")).strip()
    if category == "Code Development":
        return {"kind": "artifact", "relative_path": "reproduce.sh"}
    if category == "Result Analysis" and expected_artifacts:
        return {"kind": "artifact", "relative_path": expected_artifacts[0]}
    return {
        "kind": "log-pattern",
        "relative_path": "reproduce.log",
        "pattern": requirement[:512],
    }


def _bind_leaf_contracts(
    node: dict,
    *,
    paper_text: str,
    paper_sha256: str,
    expected_artifacts: list[str],
    dropped: list[dict],
    path: str = "root",
) -> bool:
    """Bind exact paper spans and structured checks; prune ungrounded leaves."""

    children = node.get("sub_tasks") or []
    if children:
        kept: list[dict] = []
        for index, child in enumerate(children):
            child_path = f"{path}/{index}"
            if _bind_leaf_contracts(
                child,
                paper_text=paper_text,
                paper_sha256=paper_sha256,
                expected_artifacts=expected_artifacts,
                dropped=dropped,
                path=child_path,
            ):
                kept.append(child)
            else:
                dropped.append({"path": child_path, "node": copy.deepcopy(child)})
        node["sub_tasks"] = kept
        return bool(kept)

    rationale = node.get("rationale_from_paper") or {}
    external = (
        rationale.get("external_prerequisite") if isinstance(rationale, dict) else None
    )
    if isinstance(external, dict):
        description = str(external.get("description") or "").strip()
        source = str(external.get("source") or "").strip()
        if len(description) < 10 or len(source) < 3:
            return False
        node["evidence_span"] = {
            "kind": "external-prerequisite",
            "description": description,
            "source": source,
        }
    else:
        quote = str(rationale.get("quote") or "") if isinstance(rationale, dict) else ""
        section = (
            str(rationale.get("section") or "") if isinstance(rationale, dict) else ""
        )
        span = _paper_span(paper_text, quote)
        if span is None or not section.strip():
            return False
        start, end, exact_quote = span
        rationale["quote"] = exact_quote
        node["rationale_from_paper"] = rationale
        node["evidence_span"] = {
            "kind": "paper-span",
            "section": section,
            "quote": exact_quote,
            "start_char": start,
            "end_char": end,
            "paper_sha256": paper_sha256,
        }
    return True


def _bind_verification_targets(node: dict, expected_artifacts: list[str]) -> int:
    children = node.get("sub_tasks") or []
    if children:
        return sum(
            _bind_verification_targets(child, expected_artifacts) for child in children
        )
    if isinstance(node.get("verification"), dict):
        return 0
    node["verification"] = _default_verification(node, expected_artifacts)
    return 1


def _prepare_generated_envelope(
    parsed: dict,
    *,
    paper_text: str,
    ledger: RepairLedger,
    warning_prefix: str,
) -> tuple[dict | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(parsed.get("rubric"), dict):
        return None, [f"{warning_prefix}: missing 'rubric' root"]

    before = copy.deepcopy(parsed)
    if not isinstance(parsed.get("reproduce_contract"), dict):
        parsed["reproduce_contract"] = {
            "script_path": "reproduce.sh",
            "max_runtime_sec": 21600,
        }
    contract = parsed["reproduce_contract"]
    contract.setdefault("script_path", "reproduce.sh")
    contract.setdefault("max_runtime_sec", 21600)
    ledger.record(
        action="default-field",
        target=warning_prefix,
        before=before,
        after=parsed,
        reason="added only required reproduce-contract defaults",
    )

    root = parsed["rubric"]
    before_root = copy.deepcopy(root)
    _ensure_uuid(root)
    ledger.record(
        action="identity-normalize",
        target=f"{warning_prefix}/rubric",
        before=before_root,
        after=root,
        reason="replaced invalid IDs deterministically and coerced integer weights",
    )

    dropped_invalid: list[dict] = []
    before_root = copy.deepcopy(root)
    leaves_dropped, internal_dropped = _prune_invalid_leaves(
        root,
        dropped_invalid,
    )
    if leaves_dropped or internal_dropped:
        warnings.append(
            f"{warning_prefix} pruned {leaves_dropped} leaves and "
            f"{internal_dropped} internal nodes with short requirements/evidence"
        )
        ledger.record(
            action="invalid-prune",
            target=f"{warning_prefix}/rubric",
            before=before_root,
            after=root,
            reason="removed nodes below the schema's minimum evidence/requirement length",
            dropped=dropped_invalid,
        )

    before_root = copy.deepcopy(root)
    category_warnings = normalize_rubric_node(root)
    if category_warnings:
        warnings.extend(f"category normalize: {item}" for item in category_warnings)
        ledger.record(
            action="category-normalize",
            target=f"{warning_prefix}/rubric",
            before=before_root,
            after=root,
            reason="mapped model categories to PaperBench's closed vocabulary",
        )

    before_root = copy.deepcopy(root)
    _collapse_single_child_chains(root)
    ledger.record(
        action="structure-collapse",
        target=f"{warning_prefix}/rubric",
        before=before_root,
        after=root,
        reason="collapsed ungraded single-child wrapper chains",
    )

    before_root = copy.deepcopy(root)
    stripped = _strip_leaf_fields_from_non_leaves(root)
    if stripped:
        ledger.record(
            action="leaf-field-strip",
            target=f"{warning_prefix}/rubric",
            before=before_root,
            after=root,
            reason="removed leaf-only metadata from non-leaf nodes",
        )

    expected = list(contract.get("expected_artifacts") or [])
    paper_sha = compute_paper_sha256(paper_text)
    dropped_evidence: list[dict] = []
    before_root = copy.deepcopy(root)
    if not _bind_leaf_contracts(
        root,
        paper_text=paper_text,
        paper_sha256=paper_sha,
        expected_artifacts=expected,
        dropped=dropped_evidence,
    ):
        return None, [f"{warning_prefix}: no leaf has exact paper/external evidence"]
    ledger.record(
        action="evidence-bind",
        target=f"{warning_prefix}/rubric",
        before=before_root,
        after=root,
        reason="bound each retained leaf to an exact paper span or explicit external prerequisite",
        dropped=dropped_evidence or None,
    )
    if dropped_evidence:
        warnings.append(
            f"{warning_prefix} pruned {len(dropped_evidence)} nodes without exact evidence"
        )

    before_root = copy.deepcopy(root)
    inferred = _bind_verification_targets(root, expected)
    if inferred:
        ledger.record(
            action="verification-bind",
            target=f"{warning_prefix}/rubric",
            before=before_root,
            after=root,
            reason=f"added {inferred} structured verification targets absent from model output",
        )
    return parsed, warnings


async def _generate_hierarchical(
    *,
    paper_text: str,
    target_total_leaves: int,
    call,
    subtree_concurrency: int = 4,
    parse_repairs: list[tuple[str, str, str, dict]] | None = None,
    template: PaperBenchRubricTemplate | None = None,
) -> tuple[dict | None, list[str]]:
    """Two-pass generation: skeleton → parallel subtrees → merge.

    Returns (envelope, errors). Envelope is unfrozen and unnormalized;
    caller must run normalize_rubric_node() and freeze().
    """
    errors: list[str] = []

    # ── Pass 1: skeleton ──
    skel_prompt = _render_skeleton_prompt(
        paper_text, target_total_leaves, template=template
    )
    parse_repairs = parse_repairs if parse_repairs is not None else []
    skeleton, skel_errs = await _call_with_retry(
        call,
        skel_prompt,
        label="skeleton",
        parse_repairs=parse_repairs,
    )
    errors.extend(skel_errs)
    if skeleton is None:
        return None, errors

    if not isinstance(skeleton.get("rubric"), dict):
        errors.append("skeleton missing 'rubric' root")
        return None, errors
    root = skeleton["rubric"]
    children = root.get("sub_tasks") or []
    if not children:
        errors.append("skeleton produced 0 direct children")
        return None, errors

    budgets = _extract_subtree_budgets(root, target_total_leaves)

    # ── Pass 2: subtrees in parallel ──
    sem = asyncio.Semaphore(subtree_concurrency)

    async def _one(index: int, child: dict) -> tuple[dict, dict | None, list[str]]:
        async with sem:
            budget = budgets[index]
            sub, errs = await _generate_subtree(
                call,
                paper_text,
                child,
                budget,
                parse_repairs,
                template=template,
            )
            return child, sub, errs

    results = await asyncio.gather(*[_one(i, c) for i, c in enumerate(children)])

    # ── Merge ──
    merged_children: list[dict] = []
    for child, sub, errs in results:
        errors.extend(errs)
        if sub is None:
            # Keep the skeleton stub so the rubric still loads, but warn.
            errors.append(
                f"subtree for '{child.get('requirements', '?')[:50]}' fell back to skeleton stub"
            )
            merged_children.append(child)
            continue
        # Subtree's root REPLACES the skeleton child (preserving id/weight from skeleton).
        if child.get("id"):
            sub["id"] = child["id"]
        sub["weight"] = child.get("weight", sub.get("weight", 1))
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
    paperbench_rubric_id: str | None = None,
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    subtree_concurrency: int = DEFAULT_SUBTREE_CONCURRENCY,
    provider: str = "",
    model_revision: str | None = None,
) -> dict:
    """Core async generator. ``llm_call`` (kwarg) overrides the litellm call.

    ``paperbench_rubric_id`` selects a venue-conditioned template from
    ``ari-core/config/paperbench_rubrics/<id>.yaml``. ``None`` (default)
    preserves the original prompt verbatim. Mirrors the
    ``ari-skill-paper`` venue-rubric pattern.

    Returns a result dict with ``rubric_path``, ``rubric_sha256``,
    ``leaves_count``, ``depth``, ``category_breakdown``, and ``warnings``.
    """
    if not paper_text:
        return {"error": "empty paper_text", "warnings": ["empty paper_text"]}
    if not output_path:
        return {"error": "output_path is required", "warnings": []}
    if not 1 <= int(max_model_calls) <= 256:
        return {"error": "max_model_calls must be in [1, 256]", "warnings": []}
    if not 1 <= int(subtree_concurrency) <= 16:
        return {"error": "subtree_concurrency must be in [1, 16]", "warnings": []}
    target = target_leaf_count or compute_target_leaf_count(paper_text)
    chosen_model = model or _model()
    chosen_provider = provider.strip() or _provider(chosen_model)
    chosen_revision = model_revision or _model_revision()
    strategy = "hierarchical-v2"
    resolved_quality = "calibrated"

    template: PaperBenchRubricTemplate | None = None
    if paperbench_rubric_id:
        template = load_paperbench_rubric(paperbench_rubric_id)

    base_call = llm_call or (
        lambda p: _llm_call(p, chosen_model, temperature, timeout_sec)
    )
    recorder = ProvenanceRecorder(
        output_path=output_path,
        model=chosen_model,
        provider=chosen_provider,
        model_revision=chosen_revision,
        max_model_calls=int(max_model_calls),
    )
    ledger = RepairLedger(recorder)

    async def call(rendered_prompt: str, label: str) -> str:
        return await recorder.invoke(
            label=label,
            prompt=rendered_prompt,
            call=base_call,
        )

    last_errors: list[str] = []
    env: dict | None = None
    parse_repairs: list[tuple[str, str, str, dict]] = []

    # ── Calibrated path: skeleton → parallel subtrees → merge ──
    parsed, errs = await _generate_hierarchical(
        paper_text=paper_text,
        target_total_leaves=target,
        call=call,
        subtree_concurrency=int(subtree_concurrency),
        parse_repairs=parse_repairs,
        template=template,
    )
    last_errors.extend(errs)
    budget_exhausted = any(
        "budget exhausted" in error.casefold() for error in last_errors
    )
    if parsed is not None and not budget_exhausted:
        prepared, preparation_warnings = _prepare_generated_envelope(
            parsed,
            paper_text=paper_text,
            ledger=ledger,
            warning_prefix="hierarchical",
        )
        last_errors.extend(preparation_warnings)
        prompt = _render_skeleton_prompt(paper_text, target, template=template)
        if prepared is not None:
            partial_failures = sorted(
                error
                for error in last_errors
                if "subtree" in error
                and (
                    "failed" in error
                    or "empty" in error
                    or "fell back" in error
                    or "budget" in error
                )
            )
            for label, note, raw, parsed_value in sorted(parse_repairs):
                ledger.record(
                    action="json-sanitize",
                    target=label,
                    before=raw,
                    after=parsed_value,
                    reason=note,
                )
            frozen = freeze(
                prepared,
                generator_model=chosen_model,
                prompt=prompt,
                paper_text=paper_text,
                temperature=temperature,
                seed=seed,
                provider=chosen_provider,
                model_revision=chosen_revision,
                strategy=strategy,
                quality_profile=resolved_quality,
                max_model_calls=int(max_model_calls),
                subtree_concurrency=int(subtree_concurrency),
                calls=recorder.calls(),
                partial_failures=partial_failures,
                repair_ledger=ledger.document(),
            )
            schema_errs = _validate_envelope(frozen)
            if schema_errs:
                last_errors.append(f"hierarchical schema errors: {schema_errs}")
            else:
                env = frozen

    warnings: list[str] = []
    if env is None:
        return {
            "error": "rubric generation failed after retries",
            "warnings": last_errors,
            "model": chosen_model,
            "provider": chosen_provider,
            "target_leaf_count": target,
            "model_calls": recorder.calls(),
        }

    summary = _summarize(env)
    if summary["leaves_count"] < max(10, target // 4):
        warnings.append(
            f"only {summary['leaves_count']} leaves produced (target {target})"
        )
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
        "model_revision": chosen_revision,
        "provider": chosen_provider,
        "strategy": strategy,
        "quality_profile": resolved_quality,
        "model_call_count": len(recorder.calls()),
        "partial_failures": env["generator"]["partial_failures"],
        "repair_action_count": len(env["repair_ledger"]["actions"]),
        "prompt_sha256": compute_prompt_sha256(prompt),
        "warnings": warnings,
    }


def generate_rubric_sync(**kwargs: Any) -> dict:
    """Synchronous wrapper for tests / non-async callers."""
    return asyncio.run(generate_rubric_async(**kwargs))
