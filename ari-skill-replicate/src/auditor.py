"""Independent, artifact-backed deterministic and LLM rubric audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import jsonschema

from manifest import compute_paper_sha256, verify
from provenance import ProvenanceRecorder, canonical_sha256

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "replication_rubric.schema.json"
)
AUDIT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "replication_rubric_audit.schema.json"
)

DEFAULT_MODEL = "anthropic/claude-opus-4-7"
REGEN_THRESHOLD = 0.20
DEFAULT_MAX_MODEL_CALLS = 400

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
    r"\b(" + "|".join(re.escape(token) for token in VAGUE_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _model() -> str:
    return (
        os.environ.get("ARI_MODEL_RUBRIC_AUDIT")
        or os.environ.get("ARI_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
        or DEFAULT_MODEL
    )


def _provider(model: str) -> str:
    explicit = os.environ.get("ARI_MODEL_RUBRIC_AUDIT_PROVIDER", "").strip()
    if explicit:
        return explicit
    return model.split("/", 1)[0] if "/" in model else "unknown"


def _model_revision() -> str | None:
    return os.environ.get("ARI_MODEL_RUBRIC_AUDIT_REVISION", "").strip() or None


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


def iter_leaves(node: dict):
    children = node.get("sub_tasks") or []
    if not children:
        yield node
        return
    for child in children:
        yield from iter_leaves(child)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def detect_vague_qualifier(requirements: str) -> bool:
    return bool(VAGUE_RE.search(requirements or ""))


def detect_no_paper_evidence(leaf: dict, paper_text: str) -> bool:
    evidence = leaf.get("evidence_span") or {}
    if not evidence:
        rationale = leaf.get("rationale_from_paper") or {}
        quote = str(rationale.get("quote") or "")
        return not quote or _normalize_text(quote) not in _normalize_text(paper_text)
    if evidence.get("kind") == "external-prerequisite":
        return False
    if evidence.get("kind") != "paper-span":
        return True
    start = evidence.get("start_char")
    end = evidence.get("end_char")
    quote = evidence.get("quote")
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not isinstance(quote, str)
    ):
        return True
    return not (0 <= start < end <= len(paper_text) and paper_text[start:end] == quote)


def detect_duplicates(leaves: list[dict]) -> set[str]:
    """Flag exact and near-identical requirements deterministically."""

    duplicate_ids: set[str] = set()
    for index, left in enumerate(leaves):
        left_text = _normalize_text(str(left.get("requirements") or ""))
        left_tokens = _tokens(left_text)
        if not left_text:
            continue
        for right in leaves[index + 1 :]:
            right_text = _normalize_text(str(right.get("requirements") or ""))
            right_tokens = _tokens(right_text)
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / len(union) if union else 0.0
            if left_text == right_text or similarity >= 0.92:
                duplicate_ids.update(
                    (str(left.get("id") or ""), str(right.get("id") or ""))
                )
    return duplicate_ids


def _render_audit_prompt(leaf: dict) -> str:
    template = (PROMPTS_DIR / "rubric_audit.md").read_text()
    leaf_view = {
        key: leaf.get(key)
        for key in (
            "id",
            "requirements",
            "weight",
            "task_category",
            "finegrained_task_category",
            "rationale_from_paper",
            "evidence_span",
            "verification",
        )
    }
    return template.replace(
        "{LEAF_JSON}",
        json.dumps(leaf_view, ensure_ascii=False, indent=2),
    )


async def _llm_audit_raw(prompt: str, model: str, timeout: int) -> str:
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
    response = await litellm.acompletion(**kwargs)
    return response.choices[0].message.content or ""


def _parse_verdict(raw: str) -> dict:
    value = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```\s*$", "", value)
    start, end = value.find("{"), value.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("auditor response contains no JSON object")
    parsed = json.loads(value[start:end])
    if not isinstance(parsed, dict):
        raise ValueError("auditor response JSON is not an object")
    return parsed


def _validate_document(document: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator(schema).validate(document)


def _verify_artifact(base: Path, artifact: dict, label: str) -> None:
    root = base.resolve()
    candidate = (root / str(artifact.get("relative_path") or "")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} artifact escapes the rubric workspace") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} artifact is missing")
    payload = candidate.read_bytes()
    if len(payload) != artifact.get("size_bytes") or hashlib.sha256(
        payload
    ).hexdigest() != artifact.get("sha256"):
        raise ValueError(f"{label} artifact bytes differ from rubric provenance")


def _verify_generator_provenance(rubric_file: Path, rubric: dict) -> None:
    generator = rubric.get("generator") or {}
    calls = generator.get("calls") or []
    prompt_digests: set[str] = set()
    for call in calls:
        label = f"generator {call['label']}"
        _verify_artifact(rubric_file.parent, call["prompt"], f"{label} prompt")
        prompt_digests.add(call["prompt"]["sha256"])
        if call.get("raw_response") is not None:
            _verify_artifact(
                rubric_file.parent,
                call["raw_response"],
                f"{label} raw response",
            )
        call_payload = dict(call)
        stored_call_digest = call_payload.pop("call_sha256")
        if canonical_sha256(call_payload) != stored_call_digest:
            raise ValueError(f"{label} call digest differs from rubric provenance")

    strategy = generator.get("strategy")
    if strategy == "legacy-v1-offline-migration":
        if generator.get("source_artifact") is None:
            raise ValueError("legacy rubric migration has no source artifact")
    else:
        if generator.get("prompt_sha256") not in prompt_digests:
            raise ValueError(
                "generator prompt digest has no matching artifact-backed model call"
            )
    source_artifact = generator.get("source_artifact")
    if source_artifact is not None:
        _verify_artifact(rubric_file.parent, source_artifact, "generator source")

    ledger = rubric.get("repair_ledger") or {}
    actions = ledger.get("actions") or []
    if [item.get("sequence") for item in actions] != list(range(len(actions))):
        raise ValueError("rubric repair sequence is not contiguous")
    declared = {
        canonical_sha256(artifact) for artifact in ledger.get("dropped_artifacts") or []
    }
    referenced = {
        canonical_sha256(action["dropped_artifact"])
        for action in actions
        if action.get("dropped_artifact") is not None
    }
    if declared != referenced:
        raise ValueError("rubric repair artifact index differs from repair actions")
    for artifact in ledger.get("dropped_artifacts") or []:
        _verify_artifact(rubric_file.parent, artifact, "rubric repair")


async def audit_rubric_async(
    *,
    rubric_path: str,
    paper_text: str,
    auditor_model: str = "",
    output_path: str = "",
    timeout_sec: int = 60,
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    llm_call=None,
) -> dict:
    """Write a separate audit report; the frozen rubric is never mutated."""

    chosen_model = auditor_model or _model()
    chosen_provider = _provider(chosen_model)
    chosen_revision = _model_revision()
    rubric_file = Path(rubric_path).resolve()
    rubric = json.loads(rubric_file.read_text())
    _validate_document(rubric, SCHEMA_PATH)
    if not verify(rubric):
        raise ValueError("rubric digest verification failed")
    if compute_paper_sha256(paper_text) != rubric.get("paper_sha256"):
        raise ValueError("audit paper text differs from the generated rubric input")
    _verify_generator_provenance(rubric_file, rubric)
    root = rubric.get("rubric")
    if not isinstance(root, dict):  # schema already enforces this
        raise ValueError("rubric envelope missing 'rubric' root")

    audit_path = (
        Path(output_path).resolve()
        if output_path
        else rubric_file.with_suffix(rubric_file.suffix + ".audit.json")
    )
    recorder = ProvenanceRecorder(
        output_path=str(audit_path),
        model=chosen_model,
        provider=chosen_provider,
        model_revision=chosen_revision,
        max_model_calls=max_model_calls,
    )

    leaves = list(iter_leaves(root))
    duplicate_ids = detect_duplicates(leaves)
    findings: dict[str, set[str]] = {str(leaf.get("id")): set() for leaf in leaves}
    for leaf in leaves:
        leaf_id = str(leaf.get("id"))
        if detect_vague_qualifier(str(leaf.get("requirements") or "")):
            findings[leaf_id].add("vague_qualifier")
        if detect_no_paper_evidence(leaf, paper_text):
            findings[leaf_id].add("no_paper_evidence")
        if leaf_id in duplicate_ids:
            findings[leaf_id].add("duplicate")

    generator = rubric.get("generator") or {}
    generator_identity = {
        "model": generator.get("model"),
        "model_revision": generator.get("model_revision"),
        "provider": generator.get("provider"),
    }
    auditor_identity = {
        "model": chosen_model,
        "model_revision": chosen_revision,
        "provider": chosen_provider,
    }
    independence_status = (
        "not-independent"
        if generator_identity == auditor_identity
        else "independent-model"
    )

    async def base_call(prompt: str) -> str:
        if llm_call is None:
            return await _llm_audit_raw(prompt, chosen_model, timeout_sec)
        result = await llm_call(prompt)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
        if not isinstance(result, str):
            raise TypeError(
                "auditor test/provider call returned neither text nor object"
            )
        return result

    llm_success = 0
    llm_failures = 0
    for leaf in leaves:
        leaf_id = str(leaf.get("id"))
        prompt = _render_audit_prompt(leaf)
        try:
            raw = await recorder.invoke(
                label=f"leaf-{leaf_id}",
                prompt=prompt,
                call=base_call,
            )
            verdict = _parse_verdict(raw)
            llm_success += 1
        except Exception as exc:
            llm_failures += 1
            log.warning("auditor LLM failed for leaf %s: %s", leaf_id, exc)
            continue
        if verdict.get("vague_qualifier"):
            findings[leaf_id].add("vague_qualifier")
        if verdict.get("unverifiable"):
            findings[leaf_id].add("unverifiable")

    finding_rows = [
        {"leaf_id": leaf_id, "flags": sorted(flags)}
        for leaf_id, flags in sorted(findings.items())
        if flags
    ]
    by_flag = {
        flag: sum(flag in flags for flags in findings.values())
        for flag in (
            "vague_qualifier",
            "no_paper_evidence",
            "duplicate",
            "unverifiable",
        )
    }
    flagged = len(finding_rows)
    report: dict[str, Any] = {
        "schema_version": "ari.replication-rubric-audit/v2",
        "rubric_sha256": rubric["rubric_sha256"],
        "paper_sha256": rubric["paper_sha256"],
        "deterministic": {
            "leaves_total": len(leaves),
            "leaves_flagged": flagged,
            "by_flag": by_flag,
            "findings": finding_rows,
        },
        "llm_review": {
            "status": (
                "completed"
                if llm_success == len(leaves)
                else "partial"
                if llm_success
                else "unavailable"
            ),
            "independence_status": independence_status,
            "generator_identity": generator_identity,
            "auditor_identity": auditor_identity,
            "successful_calls": llm_success,
            "failed_calls": llm_failures,
            "calls": recorder.calls(),
        },
        "regen_recommended": (flagged / max(1, len(leaves))) > REGEN_THRESHOLD,
    }
    report["report_sha256"] = canonical_sha256(report)
    _validate_document(report, AUDIT_SCHEMA_PATH)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return {
        "audit_path": str(audit_path),
        "report_sha256": report["report_sha256"],
        "flags_count": sum(by_flag.values()),
        "by_flag": by_flag,
        "leaves_total": len(leaves),
        "leaves_flagged": flagged,
        "regen_recommended": report["regen_recommended"],
        "auditor_model": chosen_model,
        "independence_status": independence_status,
        "llm_status": report["llm_review"]["status"],
    }


def audit_rubric_sync(**kwargs: Any) -> dict:
    return asyncio.run(audit_rubric_async(**kwargs))


__all__ = [
    "REGEN_THRESHOLD",
    "audit_rubric_async",
    "audit_rubric_sync",
    "detect_duplicates",
    "detect_no_paper_evidence",
    "detect_vague_qualifier",
    "iter_leaves",
]
