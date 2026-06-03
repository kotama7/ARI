"""LLM client wrapping LiteLLM for unified LLM access."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import litellm

from ari.config import LLMConfig


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None
    usage: dict | None = None


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        # Pass per-call settings instead of using global config
        self._node_id: str = ""
        self._phase: str = ""
        self._skill: str = ""
        self._work_dir: str = ""
        # Optional MCPClient injected post-construction (see core.py). When
        # set AND the backend is the cli-shim, complete() forwards a
        # --mcp-config payload to the shim so Claude can call the same
        # ari-skill MCP servers directly (instead of relying on the shim's
        # text-catalog tool protocol, which Claude can ignore — see the
        # 2026-05-28 hallucinated-partA incident).
        self.mcp_client = None

    def set_context(
        self,
        *,
        node_id: str | None = None,
        phase: str | None = None,
        skill: str | None = None,
        work_dir: str | None = None,
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

    def _model_name(self) -> str:
        from ari.llm.routing import resolve_litellm_model
        return resolve_litellm_model(self.config.model, self.config.backend)

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
        _model = self._model_name()
        _node_id = node_id if node_id is not None else getattr(self, "_node_id", "")
        _phase = phase if phase is not None else getattr(self, "_phase", "")
        _skill = skill if skill is not None else getattr(self, "_skill", "")
        _work_dir = work_dir if work_dir is not None else getattr(self, "_work_dir", "")
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
        # litellm.UnsupportedParamsError
        if not self.config.model.startswith("gpt-5"):
            kwargs["temperature"] = self.config.temperature
        if tools:
            kwargs["tools"] = tools
            # require_tool=True: always call a tool (exploration phase)
            # require_tool=False: JSON output also allowed (completion phase)
            kwargs["tool_choice"] = "required" if require_tool else "auto"
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["api_base"] = self.config.base_url
        # Disable qwen3 thinking mode (long chain-of-thought causes timeout on CPU inference)
        if "qwen3" in self.config.model.lower():
            kwargs["extra_body"] = {"options": {"think": False}}

        # When the backend is the ari cli-shim, forward (work_dir + MCP
        # server config) via extra_body so the shim can spawn `claude -p`
        # with --mcp-config + --strict-mcp-config + --allowedTools mcp__*.
        # This replaces the shim's text-catalog tool protocol (which the
        # model can ignore — leading to hallucinated tool calls / results;
        # see 2026-05-28 incident). The extra_body keys are passed through
        # by litellm's openai-compatible handler and read by
        # ari/llm/cli_server.py do_POST.
        if (
            tools
            and self.mcp_client is not None
            and self._is_cli_shim_target()
        ):
            try:
                mcp_cfg, allowed = self.mcp_client.to_claude_mcp_config(
                    phase=(_phase or None),
                )
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
        msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {
            "model": self._model_name(),
            "messages": msgs,
            "stream": True,
        }
        if not self.config.model.startswith("gpt-5"):
            kwargs["temperature"] = self.config.temperature
        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
