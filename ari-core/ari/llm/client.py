"""LLM client wrapping LiteLLM for unified LLM access."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import litellm

from ari.call_context import ToolCallContextV1
from ari.config import LLMConfig

# gpt-5* models reject temperature!=1 (and other params) with
# UnsupportedParamsError. The explicit _is_gpt5_family guard below avoids
# sending temperature in the first place; this is the process-wide safety net
# for any OTHER unsupported param litellm would otherwise raise on (matches what
# skill processes set in cost_tracker.bootstrap_skill).
litellm.drop_params = True


def _is_gpt5_family(model: str) -> bool:
    """True if any segment of ``model`` is a ``gpt-5*`` model — which only
    supports ``temperature=1`` (litellm raises ``UnsupportedParamsError`` for
    any other value). Splits on ``/`` and ``:`` so it also catches a routing
    prefix (``openai/gpt-5.1``) and a cli-shim alias
    (``codex-cli:gpt-5.6-sol``), not just a bare ``gpt-5*``. Without the alias
    case a delegated codex node sent ``temperature=0.7`` and every react call
    502'd — the node failed with ``has_real=False`` despite the shim itself
    ignoring temperature."""
    segs = (model or "").strip().replace("/", ":").split(":")
    return any(s.startswith("gpt-5") for s in segs)


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system"
    content: str



def _filter_allowed_to_offered(allowed, tools) -> list[str]:
    """Keep only the ``mcp__<server>__<tool>`` entries whose bare tool name the
    caller actually offered in ``tools``.

    Guarantees the delegated tool set equals the set ARI advertised, so the
    model is never handed a tool the prompt does not describe (nor denied one it
    does). Returns everything when the offered set cannot be read, which keeps
    the previous fail-open shape."""
    offered = set()
    for t in tools or []:
        if isinstance(t, dict):
            fn = t.get("function") or {}
            name = fn.get("name") or t.get("name")
            if name:
                offered.add(str(name))
    if not offered:
        return list(allowed or [])
    kept = []
    for full in allowed or []:
        parts = str(full).split("__")
        bare = "__".join(parts[2:]) if len(parts) >= 3 and parts[0] == "mcp" else str(full)
        if bare in offered:
            kept.append(str(full))
    return kept

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None
    usage: dict | None = None
    # Provider-attribution fields (populated by the claude_code backend;
    # None for litellm-routed backends — existing constructors unaffected).
    provider: str | None = None
    model: str | None = None
    provenance_path: str | None = None
    raw: dict | str | None = None

    @property
    def text(self) -> str:
        """Alias of ``content`` (provider-style naming)."""
        return self.content


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        # Pass per-call settings instead of using global config
        self._node_id: str = ""
        self._phase: str = ""
        self._skill: str = ""
        self._work_dir: str = ""
        self._call_context: ToolCallContextV1 | None = None
        # Optional MCPClient injected post-construction (see core.py). When
        # set AND the backend is the cli-shim, complete() forwards a
        # --mcp-config payload to the shim so Claude can call the same
        # ari-skill MCP servers directly (instead of relying on the shim's
        # text-catalog tool protocol, which Claude can ignore — see the
        # 2026-05-28 hallucinated-environment incident).
        self.mcp_client = None
        # True iff the LAST complete() call attached mcp_config (i.e. the whole
        # tool loop was delegated to one `claude -p` subprocess and only final
        # text comes back — never tool_calls). AgentLoop reads this to know a
        # prose reply may mean "work done, terminal protocol forgotten" rather
        # than a wasted step. Literal bool on purpose: consumers compare with
        # `is True` so mock objects with auto-created attributes stay inert.
        self.last_request_delegated = False

    def set_context(
        self,
        *,
        node_id: str | None = None,
        phase: str | None = None,
        skill: str | None = None,
        work_dir: str | None = None,
        call_context: ToolCallContextV1 | None = None,
    ) -> None:
        """Attach context that will be sent as litellm metadata on every
        subsequent ``complete()`` call. Pass ``None`` to leave a field
        unchanged; pass ``""`` to explicitly clear it.

        ``work_dir`` is forwarded to the cli-shim via ``extra_body`` so the
        Claude subprocess uses the node's real working directory (and so its
        debug log lands there).
        """
        if node_id is not None:
            self._node_id = str(node_id)
        if phase is not None:
            self._phase = str(phase)
        if skill is not None:
            self._skill = str(skill)
        if work_dir is not None:
            self._work_dir = str(work_dir)
        if call_context is not None:
            self._call_context = call_context

    def _model_name(self) -> str:
        from ari.llm.routing import resolve_litellm_model
        return resolve_litellm_model(self.config.model, self.config.backend)

    def _is_claude_code_target(self) -> bool:
        """True iff this client routes to the Claude Code provider
        (``ari.llm.claude_code``) instead of litellm."""
        return (self.config.backend or "").lower().replace("-", "_") == "claude_code"

    def _claude_code_complete(
        self,
        msgs: list[dict],
        tools: list[dict] | None,
        node_id: str,
        phase: str,
        skill: str,
    ) -> LLMResponse:
        """Route one completion through ClaudeCodeProvider (no litellm).

        The provider serializes the full message window into a single prompt
        (history stays ARI-side), runs Claude Code hermetically, records
        provenance + cost, and returns the same LLMResponse shape. OpenAI
        tool calling is NOT supported on this backend — fail loud so ReAct
        phases are pointed at a tool-calling backend instead of silently
        hallucinating tool results (cf. the text-catalog incident).
        """
        from ari.llm.claude_code import ClaudeCodeToolsUnsupportedError
        from ari.llm.claude_code.provider import ClaudeCodeProvider

        if tools:
            raise ClaudeCodeToolsUnsupportedError()
        if getattr(self, "_claude_code_provider", None) is None:
            self._claude_code_provider = ClaudeCodeProvider.from_llm_config(
                self.config
            )
        return self._claude_code_provider.complete(
            msgs,
            node_id=node_id,
            phase=phase,
            skill=skill,
        )

    def _is_cli_shim_target(self) -> bool:
        """True iff this client routes to ari's cli_server shim.

        Detected by either: backend=='cli-shim', model startswith
        'claude-cli'/'codex-cli'/'openai/claude-cli'/'openai/codex-cli', or
        base_url containing ':8900' (the shim's default port).
        """
        m = (self.config.model or "").lower()
        if m.startswith("claude-cli") or m.startswith("codex-cli"):
            return True
        if m.startswith("openai/claude-cli") or m.startswith("openai/codex-cli"):
            return True
        if (self.config.backend or "").lower() == "cli-shim":
            return True
        url = (self.config.base_url or "")
        return ":8900" in url

    def complete(
        self,
        messages: list[LLMMessage] | list[dict],
        tools: list[dict] | None = None,
        require_tool: bool = True,
        *,
        node_id: str | None = None,
        phase: str | None = None,
        skill: str | None = None,
        work_dir: str | None = None,
        max_tokens: int | None = None,
        call_context: ToolCallContextV1 | None = None,
    ) -> LLMResponse:
        """Send messages to the LLM and return a response.

        messages can be LLMMessage dataclasses or raw dicts (for tool role support).

        node_id/phase/skill are forwarded to litellm via ``metadata`` and picked
        up by ``cost_tracker``'s global success_callback so every call is
        attributed to a node/phase/skill in ``cost_trace.jsonl``. Defaults fall
        back to attributes set on the client (see ``set_context``).
        """
        msgs = []
        for m in messages:
            if isinstance(m, dict):
                msgs.append(m)
            else:
                msgs.append({"role": m.role, "content": m.content})
        _node_id = node_id if node_id is not None else getattr(self, "_node_id", "")
        _phase = phase if phase is not None else getattr(self, "_phase", "")
        _skill = skill if skill is not None else getattr(self, "_skill", "")
        _work_dir = work_dir if work_dir is not None else getattr(self, "_work_dir", "")
        _call_context = (
            call_context
            if call_context is not None
            else getattr(self, "_call_context", None)
        )
        # This backend routes around litellm entirely. The branch was dropped in
        # a merge and only the streaming half came back, so `backend=claude_code`
        # went to litellm as `anthropic` and asked for an ANTHROPIC_API_KEY the
        # CLI provider does not need -- a configured backend silently replaced
        # by a different one, which is worse than an outright failure.
        if self._is_claude_code_target():
            return self._claude_code_complete(
                msgs,
                tools,
                str(_node_id or ""),
                str(_phase or ""),
                str(_skill or ""),
            )
        _model = self._model_name()
        kwargs: dict = {
            "model": _model,
            "messages": msgs,
            "metadata": {
                "node_id": str(_node_id or ""),
                "phase": str(_phase or ""),
                "skill": str(_skill or ""),
            },
        }
        # gpt-5* models only support temperature=1; drop the param to avoid
        # litellm.UnsupportedParamsError (covers cli-shim aliases like
        # codex-cli:gpt-5.6-sol, not just a bare gpt-5* model).
        if not _is_gpt5_family(self.config.model):
            kwargs["temperature"] = self.config.temperature
        # Fixed seed for reproducible local-model runs (handoff study). Passed
        # to litellm/Ollama when set; backends that ignore `seed` are unaffected.
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed
        if tools:
            kwargs["tools"] = tools
            # require_tool=True: always call a tool (exploration phase)
            # require_tool=False: JSON output also allowed (completion phase)
            kwargs["tool_choice"] = "required" if require_tool else "auto"
        # Per-call reply cap. Optional and off by default, so every existing
        # caller is byte-identical; callers on a live-LLM scoring path (the
        # agent-as-judge, rqgm.paper.reviewer.agent_as_judge.max_tokens) use it
        # as a real cost bound rather than declaring one they cannot enforce.
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["api_base"] = self.config.base_url
        # The cli-shim is a LOCAL proxy that ignores auth, but litellm's
        # openai-compatible provider still refuses a call with no key at all
        # ("Missing credentials"). Without a key configured or in the env, that
        # rejection would silently degrade any caller that fails open (e.g. the
        # agent-as-judge -> deterministic rubric). Inject a harmless placeholder
        # for the shim ONLY, and only when nothing real is set.
        if (
            "api_key" not in kwargs
            and self._is_cli_shim_target()
            and not os.environ.get("OPENAI_API_KEY")
        ):
            kwargs["api_key"] = "sk-cli-shim-local"
        # Disable qwen3 thinking mode (long chain-of-thought causes timeout on CPU inference)
        if "qwen3" in self.config.model.lower():
            kwargs.setdefault("extra_body", {})["think"] = False

        # Retry transient backend failures (APIConnectionError / timeout / rate
        # limit) with litellm's built-in exponential backoff. A GPU-hosted Ollama
        # serving several concurrent BFTS shards intermittently drops connections;
        # without retries a single blip kills the node — and if it is the ROOT
        # node (no valid parent), the whole run dies at 1 node, silently biasing
        # a sweep by run survival rather than by the channel under test. Env-
        # overridable; 0 disables (restores the old single-shot behaviour).
        import os as _os
        try:
            _nr = int(_os.environ.get("ARI_LLM_NUM_RETRIES", "4"))
        except ValueError:
            _nr = 4
        if _nr > 0:
            kwargs["num_retries"] = _nr

        # Pin the Ollama context window so the KV cache fits ON-GPU. Ollama loads
        # a model at ITS OWN default context, and code models ship a huge one
        # (qwen3-coder defaults to ~256K); that × OLLAMA_NUM_PARALLEL overflows
        # VRAM and spills the model to CPU — measured 7 tok/s (78% GPU) vs
        # 224 tok/s (100% GPU) at num_ctx=32768. 32K holds the full_log handoff
        # injection (~12k tokens) plus the prompt/tools/ReAct history. litellm
        # maps the `num_ctx` kwarg into options.num_ctx (verified). Ollama-only.
        if self.config.backend == "ollama":
            try:
                _nc = int(_os.environ.get("ARI_LLM_NUM_CTX", "32768"))
            except ValueError:
                _nc = 32768
            if _nc > 0:
                kwargs["num_ctx"] = _nc

        # When the backend is the ari cli-shim, forward (work_dir + MCP
        # server config) via extra_body so the shim can spawn `claude -p`
        # with --mcp-config + --strict-mcp-config + --allowedTools mcp__*.
        # This replaces the shim's text-catalog tool protocol (which the
        # model can ignore — leading to hallucinated tool calls / results;
        # see 2026-05-28 incident). The extra_body keys are passed through
        # by litellm's openai-compatible handler and read by
        # ari/llm/cli_server.py do_POST.
        self.last_request_delegated = False
        if (
            tools
            and self.mcp_client is not None
            and self._is_cli_shim_target()
        ):
            try:
                # NOT `phase=_phase`: `phase` here is the COST-ATTRIBUTION label
                # ("react", "agent", "paper_judge", …) that rides litellm
                # metadata, while `to_claude_mcp_config(phase=…)` filters on the
                # SKILL-ROUTING vocabulary ("bfts", "paper", "reproduce").
                # Crossing the two silently returned zero servers for every
                # agent-loop call — `if mcp_cfg and allowed` then fell through,
                # so delegation NEVER fired for the phase that most needs tools
                # and the model could only emit text (observed 2026-07-20: the
                # exploration node burned its whole step budget producing plans
                # and zero artifacts).
                #
                # Ask for every skill, then keep exactly the tools the caller
                # already advertised in `tools`. The delegated set is then
                # BY CONSTRUCTION the set ARI told the model about, so the two
                # vocabularies can never disagree again.
                _routing_phase = (
                    _call_context.phase
                    if _call_context is not None and _call_context.phase
                    else None
                )
                try:
                    mcp_cfg, allowed = self.mcp_client.to_claude_mcp_config(
                        phase=_routing_phase,
                        context=_call_context,
                    )
                except TypeError as _context_error:
                    # Compatibility for pre-v1 MCP clients and test doubles.
                    # Retry only when the callable explicitly rejects the new
                    # keyword; an arbitrary TypeError raised inside the client
                    # must still reach the outer fail-safe and be reported.
                    _message = str(_context_error)
                    if "context" not in _message or "unexpected keyword" not in _message:
                        raise
                    mcp_cfg, allowed = self.mcp_client.to_claude_mcp_config(
                        phase=_routing_phase,
                    )
                allowed = _filter_allowed_to_offered(allowed, tools)
            except Exception as _e:  # noqa: BLE001 — never block the LLM call
                import logging as _l
                _l.getLogger("ari.llm.client").warning(
                    "to_claude_mcp_config failed (%s); falling back to text catalog",
                    _e,
                )
                mcp_cfg, allowed = None, None
            if mcp_cfg and allowed:
                eb = kwargs.setdefault("extra_body", {})
                eb["mcp_config"] = mcp_cfg
                eb["allowed_mcp_tools"] = allowed
                if _work_dir:
                    eb["work_dir"] = _work_dir
                self.last_request_delegated = True
        elif _work_dir and self._is_cli_shim_target():
            # No MCP wiring but still pin cwd so the shim doesn't fall back
            # to a throwaway tmp dir (which it then rmtrees, deleting any
            # artifacts the agent wrote).
            kwargs.setdefault("extra_body", {})["work_dir"] = _work_dir
        response = litellm.completion(timeout=1800, **kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        import logging as _logging
        _log = _logging.getLogger('ari.llm.client')
        _log.info("LLM response: tool_calls=%s content_preview=%r",
                  bool(tool_calls), (message.content or "")[:100])
        # Cost tracking is handled by the litellm global success_callback
        # installed in ari.cost_tracker; the metadata above carries the
        # node/phase/skill context. Don't call _ct.record() here — doing so
        # would double-count every LLM call.
        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            usage=usage,
        )

    def stream(self, messages: list[LLMMessage]) -> Iterator[str]:
        """Stream responses from the LLM."""
        if self._is_claude_code_target():
            raise NotImplementedError(
                "backend=claude_code does not support streaming; use "
                "complete() (each call is a single hermetic Claude Code run)"
            )
        msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {
            "model": self._model_name(),
            "messages": msgs,
            "stream": True,
        }
        if not _is_gpt5_family(self.config.model):
            kwargs["temperature"] = self.config.temperature
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed
        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
