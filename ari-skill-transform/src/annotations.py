"""Stochastic interpretation layer for ``ScienceDataV1``.

The model sees only canonical node-report/source selections.  Its response is
stored content-addressably and is always marked ``claim_eligible=false`` by the
core contract; it cannot mutate or contribute values to raw/derived sections.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import litellm

from ari.public.science_data import (
    ScienceArtifactRefV1,
    ScienceInterpretationV1,
    canonical_science_digest,
)


MAX_RAW_RESPONSE_BYTES = 1024 * 1024
INTERPRETATION_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "science_interpretation.md"
)


def build_interpretation_prompt(report_blob: str, source_blob: str) -> str:
    """Render the versioned static analyst prompt with bounded evidence."""

    template = INTERPRETATION_PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("__ARI_NODE_REPORTS__", report_blob[:14_000]).replace(
        "__ARI_SELECTED_SOURCE__", source_blob[:16_000]
    )


def robust_extract_json(raw: str) -> dict[str, Any]:
    """Extract one JSON object without treating malformed prose as success."""

    if not raw:
        raise ValueError("empty response")
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text).strip()
    candidates: list[str] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
            else:
                if current == '"':
                    in_string = True
                elif current == "{":
                    depth += 1
                elif current == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start : end + 1])
                        break
    last_error: Exception | None = None
    for candidate in sorted(candidates, key=len, reverse=True):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"could not extract a JSON object: {last_error}")


def _provider(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[0]
    return (os.environ.get("ARI_BACKEND") or "unspecified").strip().lower()


def _checkpoint_and_workspace(nodes_json_path: str) -> tuple[Path, Path]:
    checkpoint = Path(nodes_json_path).expanduser().resolve(strict=True).parent
    workspace = (
        checkpoint.parent.parent
        if checkpoint.parent.name == "checkpoints"
        else checkpoint.parent
    )
    return checkpoint, workspace


def _store_raw_response(nodes_json_path: str, payload: bytes) -> ScienceArtifactRefV1:
    checkpoint, workspace = _checkpoint_and_workspace(nodes_json_path)
    hex_digest = hashlib.sha256(payload).hexdigest()
    relative_checkpoint = (
        Path("artifacts")
        / "transform-interpretation"
        / "sha256"
        / hex_digest[:2]
        / f"{hex_digest}.txt"
    )
    destination = checkpoint / relative_checkpoint
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError("content-address collision for transform interpretation")
    else:
        temporary = destination.with_name(destination.name + f".tmp-{os.getpid()}")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    try:
        relative = destination.relative_to(workspace).as_posix()
    except ValueError:
        relative = relative_checkpoint.as_posix()
    return ScienceArtifactRefV1(
        relative_path=relative,
        digest="sha256:" + hex_digest,
        media_type="text/plain; charset=utf-8",
        role="transform-model-raw-response",
        size_bytes=len(payload),
    )


def unavailable_interpretation(
    *, raw_digest: str, kind: str, message: str
) -> ScienceInterpretationV1:
    return ScienceInterpretationV1.create(
        status="unavailable",
        input_raw_digest=raw_digest,
        error_kind=kind,
        error_message=message,
    )


async def annotate_science_data(
    *,
    nodes_json_path: str,
    raw_digest: str,
    prompt: str | None,
    model: str,
    api_base: str = "",
    report_driven: bool,
) -> ScienceInterpretationV1:
    """Return an immutable, non-authoritative annotation record."""

    if not prompt or not report_driven:
        return unavailable_interpretation(
            raw_digest=raw_digest,
            kind="node-report-unavailable",
            message=(
                "Canonical node reports are required for interpretation; "
                "trace/source fallback is available only through the offline legacy converter."
            ),
        )
    prompt_digest = canonical_science_digest(prompt)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "metadata": {
            "skill": "transform",
            "tool": "nodes_to_science_data",
            "report_driven": True,
            "prompt_chars": len(prompt),
            "prompt_digest": prompt_digest,
            "raw_digest": raw_digest,
        },
    }
    if api_base:
        kwargs["api_base"] = api_base
    try:
        response = await litellm.acompletion(**kwargs)
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        return ScienceInterpretationV1.create(
            status="unavailable",
            input_raw_digest=raw_digest,
            prompt_digest=prompt_digest,
            model=model,
            model_revision=os.environ.get("ARI_MODEL_TRANSFORM_REVISION") or None,
            provider=_provider(model),
            error_kind="model-call-failed",
            error_message=f"{type(exc).__name__}: {exc}"[:4096],
        )
    payload = raw.encode("utf-8", errors="replace")
    if len(payload) > MAX_RAW_RESPONSE_BYTES:
        return ScienceInterpretationV1.create(
            status="invalid",
            input_raw_digest=raw_digest,
            prompt_digest=prompt_digest,
            model=model,
            model_revision=os.environ.get("ARI_MODEL_TRANSFORM_REVISION") or None,
            provider=_provider(model),
            error_kind="model-response-too-large",
            error_message=f"response exceeded {MAX_RAW_RESPONSE_BYTES} bytes",
        )
    raw_artifact = _store_raw_response(nodes_json_path, payload)
    try:
        parsed = robust_extract_json(raw)
        context = parsed.get("experiment_context")
        protocol = parsed.get("evaluation_protocol")
        overview = parsed.get("implementation_overview")
        if context is None and "experiment_context" not in parsed:
            raise ValueError("response lacks experiment_context")
        if not isinstance(context, dict):
            raise ValueError("experiment_context must be an object")
        if protocol is not None and not isinstance(protocol, dict):
            raise ValueError("evaluation_protocol must be an object")
        if overview is not None and not isinstance(overview, dict):
            raise ValueError("implementation_overview must be an object")
        return ScienceInterpretationV1.create(
            status="ok",
            input_raw_digest=raw_digest,
            prompt_digest=prompt_digest,
            model=model,
            model_revision=os.environ.get("ARI_MODEL_TRANSFORM_REVISION") or None,
            provider=_provider(model),
            sampling={"temperature": "provider-default", "top_p": "provider-default"},
            evaluation_protocol=dict(protocol or {}),
            experiment_context=dict(context),
            implementation_overview=dict(overview) if overview is not None else None,
            raw_response_artifact=raw_artifact,
        )
    except Exception as exc:
        return ScienceInterpretationV1.create(
            status="invalid",
            input_raw_digest=raw_digest,
            prompt_digest=prompt_digest,
            model=model,
            model_revision=os.environ.get("ARI_MODEL_TRANSFORM_REVISION") or None,
            provider=_provider(model),
            raw_response_artifact=raw_artifact,
            error_kind="schema-invalid-model-response",
            error_message=f"{type(exc).__name__}: {exc}"[:4096],
        )


__all__ = [
    "INTERPRETATION_PROMPT_PATH",
    "MAX_RAW_RESPONSE_BYTES",
    "annotate_science_data",
    "build_interpretation_prompt",
    "robust_extract_json",
    "unavailable_interpretation",
]
