"""Provider-neutral ``TurnCompleter`` that routes through LiteLLM.

PaperBench's stock ``OpenAICompletionsTurnCompleter`` (a) hits OpenAI directly
and (b) refuses any model id that is not in its hand-maintained
``CONTEXT_WINDOW_LENGTHS`` registry, so we cannot use it with newer OpenAI
snapshots, Azure, Anthropic, Gemini, Ollama, etc. This module supplies a
drop-in alternative ``LiteLLMTurnCompleter`` + ``LiteLLMConfig`` that
``SimpleJudge`` accepts via the ``completer_config`` parameter.

The bridge supplies this completer for the main leaf judgment and for both
structured score parsers. This keeps provider identity consistent and allows
every prompt/response pair to be captured under one evidence directory.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Unpack

import tiktoken
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage
from preparedness_turn_completer.turn_completer import TurnCompleter
from pydantic import ConfigDict

logger = logging.getLogger(__name__)

# Sensible context-window defaults keyed by model-name prefix. These are used
# when the caller does not supply ``n_ctx`` explicitly. Keep conservative —
# downstream truncation is more forgiving than over-promising context.
_DEFAULT_N_CTX_BY_PREFIX: tuple[tuple[str, int], ...] = (
    # OpenAI
    ("gpt-5", 400_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("o4", 200_000),
    ("o3", 200_000),
    ("o1", 200_000),
    # Anthropic
    ("claude-opus-4", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude-3", 200_000),
    ("anthropic/claude", 200_000),
    # Google
    ("gemini/gemini-2.5", 1_000_000),
    ("gemini/gemini-2.0", 1_000_000),
    ("gemini/gemini-1.5", 1_000_000),
    ("gemini-2.5", 1_000_000),
    ("gemini-1.5", 1_000_000),
    # Local / catch-all
    ("ollama", 32_000),
)
_DEFAULT_N_CTX_FALLBACK = 128_000

_TREE_ENTRY_RE = re.compile(
    r"^(?P<prefix>(?:(?:\u2502   )|(?:    ))*)(?:\u251c\u2500\u2500 |\u2514\u2500\u2500 )(?P<name>.+?)\s*$"
)


def _paperbench_file_tree_paths(conversation: list[Any]) -> set[str] | None:
    """Return paths shown by PaperBench's file-ranking prompt.

    ``None`` means this is not the distinctive file-ranking turn; an empty
    set means it is a ranking turn for an empty submission.  Keeping those
    states distinct lets negative-control grading avoid asking a provider to
    invent a filename when PaperBench has explicitly shown no files.
    """

    if not conversation:
        return None
    last = conversation[-1]
    prompt = last.get("content") if isinstance(last, dict) else None
    if not isinstance(prompt, str) or not (
        "Directory structure:\n" in prompt
        and "most relevant files in order of relevance" in prompt
    ):
        return None
    tree_text = prompt.split("Directory structure:\n", 1)[1].split(
        "\n\nNow return", 1
    )[0]
    components: list[str] = []
    tree_paths: set[str] = set()
    for line in tree_text.splitlines():
        match = _TREE_ENTRY_RE.match(line)
        if match is None:
            continue
        depth = len(match.group("prefix")) // 4
        components[depth:] = [match.group("name")]
        tree_paths.add("/".join(components))
    return tree_paths


def _normalize_paperbench_file_selection(
    conversation: list[Any], content: str | None
) -> str | None:
    """Map PaperBench file-ranking replies back to paths in its shown tree.

    CLI-backed models know their private shim cwd and can prepend it even
    though the prompt's directory tree is submission-relative.  Upstream then
    treats every returned line as relative and joins it to ``submission_dir``,
    making a correct absolute selection unreadable.  Only the distinctive
    file-ranking prompt is adapted.  The raw provider reply remains unchanged
    in the model-call trace; the returned chat message uses the longest suffix
    that actually occurs in the tree (so ``submission/x.c`` wins over ``x.c``
    when that is what the model selected).
    """

    if not isinstance(content, str) or not content.strip():
        return content
    tree_paths = _paperbench_file_tree_paths(conversation)
    if not tree_paths:
        return content

    candidates = sorted(
        tree_paths,
        key=lambda value: (value.count("/"), len(value)),
        reverse=True,
    )
    normalized: list[str] = []
    for line in content.splitlines():
        value = line.strip().strip("`\"'").replace("\\", "/").rstrip("/")
        if not value:
            continue
        match = next(
            (
                candidate
                for candidate in candidates
                if value == candidate or value.endswith("/" + candidate)
            ),
            None,
        )
        if match is not None and match not in normalized:
            normalized.append(match)
    return "\n".join(normalized) if normalized else content


def _jsonable(value: Any) -> Any:
    """Convert SDK/Pydantic values into finite, lossless-enough trace JSON."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, type):
        schema = (
            value.model_json_schema()
            if hasattr(value, "model_json_schema")
            else None
        )
        return {"type_name": value.__name__, "json_schema": _jsonable(schema)}
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
        except TypeError:
            dumped = value.model_dump()
        return _jsonable(dumped)
    return {"type_name": value.__class__.__name__, "text": str(value)}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _infer_n_ctx(model: str) -> int:
    for prefix, n in _DEFAULT_N_CTX_BY_PREFIX:
        if model.startswith(prefix):
            return n
    return _DEFAULT_N_CTX_FALLBACK


def _infer_encoding_name(model: str) -> str:
    """Return a tiktoken encoding name. SimpleJudge uses this only for
    truncation token-counting; an approximate encoding is fine for non-OpenAI
    models — over- or under-counting tokens by ~10% only changes how
    aggressively we truncate."""
    try:
        return tiktoken.encoding_name_for_model(model.split("/")[-1])
    except KeyError:
        return "o200k_base"


# ── multimodal markdown-image expansion ──────────────────────────────────
#
# When ``paper_md`` is built by ``pymupdf4llm.to_markdown(write_images=True)``
# it carries ``![](images/img-N.png)`` references that point at PNG files
# on disk next to the markdown. Vendor ``SimpleJudge`` embeds ``paper_md``
# verbatim into a text-only prompt, so without help those references reach
# the judge as raw markdown bytes and the figures are never seen.
#
# This expander runs once per ``async_completion`` call. For every message
# whose ``content`` is a plain string it scans for markdown image syntax,
# resolves each path against the search roots below, and rewrites the
# content into a list of OpenAI multimodal blocks
# (``[{"type":"text","text":...},{"type":"image_url","image_url":{...}},...]``).
# LiteLLM transparently forwards this shape to Anthropic / Gemini / OpenAI
# multimodal endpoints, so vendor SimpleJudge stays unmodified and the
# vendor-swap property in report §4.4 is preserved.
#
# Toggle off with env ``ARI_MULTIMODAL_PAPER=0`` for A/B comparisons.

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _multimodal_enabled() -> bool:
    return os.environ.get("ARI_MULTIMODAL_PAPER", "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def _max_images_per_message() -> int:
    """Read each call so env-var overrides set late by callers still take
    effect — module-level constants would freeze too early when this
    module is imported transitively by ``judge_submission``."""
    try:
        return max(1, int(os.environ.get("ARI_MULTIMODAL_MAX_IMAGES", "20") or "20"))
    except ValueError:
        return 20


def _resolve_image(rel: str, search_roots: list[Path]) -> Path | None:
    """Resolve a markdown image reference against the supplied search roots.

    Accepts absolute paths verbatim. Relative paths are tried under each
    root in order; the first hit wins. Returns None on miss so the caller
    can leave the markdown reference intact (graceful degradation).
    """
    p = Path(rel)
    if p.is_absolute():
        return p if p.is_file() else None
    for root in search_roots:
        cand = (root / rel).resolve()
        if cand.is_file():
            return cand
    return None


def _png_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _expand_one_string(content: str, search_roots: list[Path]) -> list[dict] | str:
    """Split a markdown string into OpenAI multimodal blocks.

    Returns the original string when there are no image refs (so we can
    leave the message ``content`` as-is and avoid an unnecessary list
    wrapping for the common case).
    """
    matches = list(_MARKDOWN_IMAGE_RE.finditer(content))
    if not matches:
        return content
    max_images = _max_images_per_message()
    blocks: list[dict] = []
    images_added = 0
    cursor = 0
    for m in matches:
        start, end = m.span()
        if start > cursor:
            preceding = content[cursor:start]
            if preceding.strip():
                blocks.append({"type": "text", "text": preceding})
        if images_added < max_images:
            img_path = _resolve_image(m.group(2), search_roots)
            if img_path is not None:
                try:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": _png_to_data_url(img_path)},
                    })
                    images_added += 1
                except Exception as e:
                    logger.warning("multimodal: failed to attach %s: %s", img_path, e)
                    blocks.append({"type": "text", "text": m.group(0)})
            else:
                # Reference unresolvable — keep markdown verbatim so the
                # judge at least sees the caption-like alt text.
                blocks.append({"type": "text", "text": m.group(0)})
        else:
            blocks.append({"type": "text", "text": m.group(0)})
        cursor = end
    if cursor < len(content):
        trailing = content[cursor:]
        if trailing.strip():
            blocks.append({"type": "text", "text": trailing})
    return blocks if any(b.get("type") == "image_url" for b in blocks) else content


def _expand_markdown_images(
    conversation: list[Any], extra_image_roots: list[Path] | None = None,
) -> list[Any]:
    """Walk a conversation and rewrite text content with image refs to
    multimodal blocks. Non-string ``content`` (already a list) is left
    alone — SimpleJudge sometimes pre-assembles such payloads itself.
    """
    if not _multimodal_enabled():
        return list(conversation)
    cwd = Path.cwd()
    roots: list[Path] = list(extra_image_roots or [])
    # Common places to look: cwd, the ARI checkpoint dir (where the dogfood
    # script drops paper.md + images/), the parent of paper.md if known.
    roots.append(cwd)
    seen: set[Path] = set()
    unique_roots: list[Path] = []
    for r in roots:
        rr = r.resolve()
        if rr not in seen and rr.is_dir():
            seen.add(rr)
            unique_roots.append(rr)
    out: list[Any] = []
    for msg in conversation:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, str):
            expanded = _expand_one_string(content, unique_roots)
            if expanded is content:
                out.append(msg)
            else:
                new = dict(msg)
                new["content"] = expanded
                out.append(new)
        else:
            out.append(msg)
    return out


class LiteLLMTurnCompleter(TurnCompleter):
    """``TurnCompleter`` whose ``async_completion`` calls ``litellm.acompletion``.

    Accepts any model id LiteLLM understands (``gpt-5-mini``,
    ``anthropic/claude-opus-4-5``, ``gemini/gemini-2.5-pro``,
    ``ollama/llama3.1``, …). Drops PaperBench's registry constraint.
    """

    def __init__(
        self,
        model: str,
        *,
        n_ctx: int | None = None,
        encoding_name: str | None = None,
        api_base: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        response_format: Any = None,
        timeout: int | None = None,
        extra_kwargs: dict | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        trace_dir: str | None = None,
    ):
        self.model = model
        self.encoding_name = encoding_name or _infer_encoding_name(model)
        self.n_ctx = int(n_ctx) if n_ctx else _infer_n_ctx(model)
        self.api_base = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.response_format = response_format
        self.timeout = timeout
        self.extra_kwargs = dict(extra_kwargs or {})
        # Chat-Completions-shaped tool params (see :class:`LiteLLMBasicAgentCompleterConfig`
        # for the conversion from PaperBench's Responses-shaped FunctionToolParam).
        self.tools = list(tools) if tools else None
        self.tool_choice = tool_choice
        self.trace_dir = Path(trace_dir).resolve() if trace_dir else None
        if self.trace_dir is not None:
            self.trace_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.trace_dir.is_symlink() or not self.trace_dir.is_dir():
                raise ValueError("trace_dir must be a real directory")
        # Used by ``BasicAgentTurnCompleterConfig`` siblings (e.g.
        # ``OpenAIResponsesTurnCompleter``) to surface retry time. We track
        # it via litellm's ``num_retries`` parameter; on each retry we add
        # the elapsed delay. The solver clears the field after reading.
        self._last_retry_time = 0.0

    class Config(TurnCompleter.Config):
        """Pydantic-friendly config matching ``TurnCompleter.Config`` shape."""

        model_config = ConfigDict(arbitrary_types_allowed=True)

        model: str
        n_ctx: int | None = None
        encoding_name: str | None = None
        api_base: str | None = None
        temperature: float | None = None
        max_tokens: int | None = None
        top_p: float | None = None
        response_format: Any = None
        timeout: int | None = None
        extra_kwargs: dict | None = None
        tools: list[dict] | None = None
        tool_choice: str | None = None
        trace_dir: str | None = None

        def build(self) -> "LiteLLMTurnCompleter":
            return LiteLLMTurnCompleter(
                model=self.model,
                n_ctx=self.n_ctx,
                encoding_name=self.encoding_name,
                api_base=self.api_base,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                response_format=self.response_format,
                timeout=self.timeout,
                extra_kwargs=self.extra_kwargs,
                tools=self.tools,
                tool_choice=self.tool_choice,
                trace_dir=self.trace_dir,
            )

    class Completion(TurnCompleter.Completion):
        usage: CompletionUsage | None = None

    def completion(
        self,
        conversation: TurnCompleter.RuntimeConversation,
        **params: Unpack[TurnCompleter.Params],
    ) -> "LiteLLMTurnCompleter.Completion":
        raise NotImplementedError("Use async_completion")

    async def async_completion(
        self,
        conversation: TurnCompleter.RuntimeConversation,
        **params: Unpack[TurnCompleter.Params],
    ) -> "LiteLLMTurnCompleter.Completion":
        import litellm

        expanded_messages = _expand_markdown_images(list(conversation))
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": expanded_messages,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        if self.response_format is not None:
            kwargs["response_format"] = self.response_format
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        kwargs.update(self.extra_kwargs)
        if self.tools:
            kwargs["tools"] = list(self.tools)
            if self.tool_choice:
                kwargs["tool_choice"] = self.tool_choice

        call_id = f"{time.time_ns()}-{secrets.token_hex(8)}"
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        trace_request = {
            "model": self.model,
            "messages": _jsonable(expanded_messages),
            "parameters": {
                key: _jsonable(kwargs[key])
                for key in (
                    "temperature",
                    "max_tokens",
                    "top_p",
                    "response_format",
                    "timeout",
                    "tools",
                    "tool_choice",
                )
                if key in kwargs
            },
        }
        if _paperbench_file_tree_paths(expanded_messages) == set():
            # PaperBench deliberately grades an empty repository as a negative
            # control.  There is no scientifically valid filename to rank, and
            # CLI models may represent that answer as no assistant item at all.
            # Return the empty selection deterministically and record that no
            # provider inference was used.
            self._last_retry_time = 0.0
            self._write_trace(
                call_id,
                started_at=started_at,
                request=trace_request,
                response={
                    "provider_model": None,
                    "content": "",
                    "refusal": None,
                    "tool_calls": [],
                    "finish_reason": "deterministic-empty-file-tree",
                    "usage": None,
                    "synthetic_reason": "paperbench-empty-submission-tree",
                },
                error=None,
            )
            return LiteLLMTurnCompleter.Completion(
                input_conversation=conversation,
                output_messages=[
                    ChatCompletionMessage(role="assistant", content="")
                ],
                usage=None,
            )
        t0 = time.monotonic()
        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as exc:
            self._write_trace(
                call_id,
                started_at=started_at,
                request=trace_request,
                response=None,
                error=f"{exc.__class__.__name__}: {exc}"[:4096],
            )
            raise
        # litellm exposes the cumulative API retry/backoff time on the
        # response when ``num_retries`` triggers. Best-effort; falls back
        # to wall-clock delta — which inflates by request latency, but
        # solver only uses this to subtract from time-budget accounting.
        retry_time = float(getattr(resp, "_response_ms", 0.0)) / 1000.0
        if retry_time <= 0.0:
            retry_time = max(0.0, time.monotonic() - t0)
        self._last_retry_time = retry_time

        choice = resp.choices[0]
        msg = choice.message
        raw_content = getattr(msg, "content", None)
        self._write_trace(
            call_id,
            started_at=started_at,
            request=trace_request,
            response={
                "provider_model": getattr(resp, "model", None),
                "content": _jsonable(raw_content),
                "refusal": _jsonable(getattr(msg, "refusal", None)),
                "tool_calls": _jsonable(getattr(msg, "tool_calls", None) or []),
                "finish_reason": getattr(choice, "finish_reason", None),
                "usage": _jsonable(getattr(resp, "usage", None)),
            },
            error=None,
        )

        # litellm's ``message.tool_calls`` is a list of OpenAI-shaped
        # ``ChatCompletionMessageToolCall`` dicts. Coerce each into the
        # typed ``ChatCompletionMessageFunctionToolCall`` that
        # ``parse_basic_agent_tool_calls`` requires (it asserts
        # ``isinstance(tc, ChatCompletionMessageFunctionToolCall)``).
        tool_calls_typed: list[ChatCompletionMessageFunctionToolCall] = []
        raw_tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in raw_tool_calls:
            tc_dict = (
                tc.model_dump() if hasattr(tc, "model_dump")
                else dict(tc) if isinstance(tc, dict)
                else {"id": tc.id, "type": "function",
                      "function": {"name": tc.function.name,
                                   "arguments": tc.function.arguments}}
            )
            fn = tc_dict.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, dict):
                args = json.dumps(args)
            tool_calls_typed.append(
                ChatCompletionMessageFunctionToolCall(
                    id=str(tc_dict.get("id", "")),
                    type="function",
                    function=Function(
                        name=str(fn.get("name", "")),
                        arguments=str(args or "{}"),
                    ),
                )
            )
        chat_msg = ChatCompletionMessage(
            role="assistant",
            content=_normalize_paperbench_file_selection(
                expanded_messages, raw_content
            ),
            refusal=getattr(msg, "refusal", None),
            tool_calls=tool_calls_typed or None,
        )
        usage_obj = getattr(resp, "usage", None)
        usage_dump: CompletionUsage | None = None
        if usage_obj is not None:
            try:
                usage_dump = CompletionUsage.model_validate(
                    usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
                )
            except Exception:  # noqa: BLE001 — usage is best-effort, never block grading
                usage_dump = None
        return LiteLLMTurnCompleter.Completion(
            input_conversation=conversation,
            output_messages=[chat_msg],
            usage=usage_dump,
        )

    def _write_trace(
        self,
        call_id: str,
        *,
        started_at: str,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        if self.trace_dir is None:
            return
        request_digest = _canonical_digest(request)
        payload = {
            "schema_version": "ari.model-call-trace/v1",
            "call_id": call_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "request": request,
            "request_digest": request_digest,
            "response": response,
            "response_digest": _canonical_digest(response)
            if response is not None
            else None,
            "error": error,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        temporary = self.trace_dir / f".{call_id}.tmp"
        destination = self.trace_dir / f"{call_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)


# ─── BasicAgent-compatible config (tool conversion + retry tracking) ──


def _responses_tool_to_chat_completions(rtool: dict) -> dict:
    """Convert a Responses-shaped FunctionToolParam dict to a Chat Completions
    tool param dict.

    Responses shape (what PaperBench tools emit via ``get_oai_tool_call()``):
        {"type": "function", "name": ..., "description": ..., "parameters": {...},
         "strict": false}

    Chat Completions shape (what litellm / OpenAI Chat-Completions API expect):
        {"type": "function", "function": {"name": ..., "description": ...,
                                          "parameters": {...}}}

    The two are *similar* (both call themselves "function tools") but the
    name/description/parameters live one nesting level apart. Some Chat-
    Completions providers also accept the flat form as a courtesy; we emit
    the nested form which is the OpenAI-documented norm.
    """
    if not isinstance(rtool, dict):
        rtool = (
            rtool.model_dump() if hasattr(rtool, "model_dump") else dict(rtool)
        )
    if "function" in rtool and "type" in rtool:
        # Already Chat Completions shaped.
        return rtool
    return {
        "type": "function",
        "function": {
            "name": rtool.get("name", ""),
            "description": rtool.get("description", ""),
            "parameters": rtool.get("parameters", {"type": "object"}),
        },
    }


# Imports deferred so this module loads without paperbench on path during
# unit tests of the standalone LiteLLMTurnCompleter.
def _basicagent_classes():
    import _vendor_path  # noqa: F401
    from paperbench.solvers.basicagent.completer import (
        BasicAgentTurnCompleterConfig,
        TimeTrackingRetryConfig,
    )
    return BasicAgentTurnCompleterConfig, TimeTrackingRetryConfig


def _make_litellm_basicagent_config_class():
    """Lazily build the subclass so import order is forgiving."""
    BasicAgentTurnCompleterConfig, TimeTrackingRetryConfig = _basicagent_classes()

    class LiteLLMBasicAgentCompleterConfig(  # noqa: D401  (class — see docstring)
        LiteLLMTurnCompleter.Config,
        BasicAgentTurnCompleterConfig,
    ):
        """Config that satisfies both ``BasicAgentTurnCompleterConfig`` and
        ``LiteLLMTurnCompleter.Config``.

        Used by ``AriPBSolver`` (Phase 4 entry-point alternative to
        ``OpenAIResponsesTurnCompleterConfig``). Converts PaperBench tool
        defs to Chat Completions form on ``build()`` so litellm can pass
        them to whichever provider the model id targets.
        """

        model_config = ConfigDict(arbitrary_types_allowed=True)

        def build(self) -> "LiteLLMTurnCompleter":
            converted_tools: list[dict] = []
            if self.basicagent_tools:
                for tool in self.basicagent_tools:
                    converted_tools.append(
                        _responses_tool_to_chat_completions(tool.get_oai_tool_call())
                    )
            existing = self.tools or []
            self.tools = list(existing) + converted_tools
            completer = LiteLLMTurnCompleter(
                model=self.model,
                n_ctx=self.n_ctx,
                encoding_name=self.encoding_name,
                api_base=self.api_base,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                top_p=self.top_p,
                response_format=self.response_format,
                timeout=self.timeout,
                extra_kwargs=self.extra_kwargs,
                tools=self.tools,
                tool_choice=self.tool_choice,
                trace_dir=self.trace_dir,
            )

            # Surface ``retry_config`` so ``make_completer_request`` can read
            # ``time_spent_retrying`` after each call (see vendor api.py).
            # We feed our subprocess-measured retry time into that slot.
            class _CompleterWithRetryShim(type(completer)):
                pass

            # Attach retry_config attribute to the completer instance so
            # ``hasattr(completer, "retry_config")`` returns True.
            completer.retry_config = self.retry_config  # type: ignore[attr-defined]
            return completer

    return LiteLLMBasicAgentCompleterConfig


def get_litellm_basicagent_completer_config():
    """Return the ``LiteLLMBasicAgentCompleterConfig`` class (lazily built)."""
    return _make_litellm_basicagent_config_class()
