"""The MCP tool → capability triple policy (plan 04 §5.6.4).

:class:`ari.rqgm.kernel.CapabilityGatedMCPClient` is the constitutional choke
point: it maps each tool call to an ``(actor, action, resource)`` triple and
denies the call when :meth:`ConstitutionalKernel.validate_capability` says the
actor may not do that. It shipped complete — and was never constructed outside
tests, so under ``ari_rqgm`` NO tool call was ever checked against the
capability matrix and the codes that make the constitution enforceable
(``CK-ACC-001`` out-of-scope access, ``CK-ACC-002`` retired-prompt-text access,
``CK-ROL-901`` forged registry-writer authority) could not be raised from the
one place a running agent actually touches the world.

This module supplies the missing policy. Its posture is deliberately
conservative:

* **Unmapped tools dispatch untouched.** Returning ``None`` is the documented
  "ungoverned tool" answer, so a tool this policy does not recognise behaves
  exactly as before the gate existed.
* **The research agent acts as the institutional ``generator``.** That is the
  role the capability matrix already grants ``read: checkpoint_artifacts`` /
  ``read: records`` / ``append: records`` / ``invoke: records``, so ordinary
  research work is ALLOWED and merely audited — installing the gate does not
  change what a well-behaved run can do.
* **What it catches is the abnormal.** A tool reaching for retired prompt text
  or attempting a registry write resolves to a resource the generator does not
  hold, which is exactly the violation class the emergency path exists for.
"""

from __future__ import annotations

#: The role/tier a running research agent acts as at the MCP choke point.
#: Institutional (not meta): it may read artifacts and append records, but it
#: holds no registry-write or meta-emission capability.
AGENT_ACTOR: tuple[str, str] = ("generator", "institutional")

#: Tool-name substrings that reach for GOVERNED prompt text. A generator has
#: ``read: active_prompt_text`` but NOT ``read: retired_prompt_text`` — the
#: distinction CK-ACC-002 exists to enforce.
_RETIRED_PROMPT_MARKERS: tuple[str, ...] = ("retired_prompt", "retired_text")

#: Tool-name substrings that would WRITE the governed registry. Only the
#: RegistryTransitionEngine may; anyone else is CK-ROL-901.
_REGISTRY_WRITE_MARKERS: tuple[str, ...] = (
    "registry_write", "set_prompt_status", "activate_candidate",
    "register_component", "register_prompt",
)

#: Tools that mutate the checkpoint / execute work on its behalf.
_APPEND_MARKERS: tuple[str, ...] = (
    "write", "save", "append", "record", "store", "upload", "commit",
)

#: Tools that execute code or submit jobs — invocation, not a read.
_INVOKE_MARKERS: tuple[str, ...] = (
    "run_", "exec", "submit", "compile", "build", "reproduce", "replicate",
)


def _has(name: str, markers: tuple[str, ...]) -> bool:
    low = (name or "").lower()
    return any(m in low for m in markers)


def default_tool_policy(tool_name: str, args) -> "tuple | None":
    """Map ``(tool_name, args)`` to ``(actor, action, resource)`` or ``None``.

    ``None`` means "ungoverned" — the gate dispatches the call untouched. Every
    mapped triple is checked against ``CAPABILITY_MATRIX``; the mappings a
    normal research run produces are ones the institutional generator holds, so
    the gate audits without blocking legitimate work.
    """
    name = str(tool_name or "")
    if not name:
        return None
    # The two genuinely dangerous shapes first — these are what the emergency
    # path exists to catch, and the generator holds neither capability.
    if _has(name, _REGISTRY_WRITE_MARKERS):
        return (AGENT_ACTOR, "write", "registry")
    if _has(name, _RETIRED_PROMPT_MARKERS):
        return (AGENT_ACTOR, "read", "retired_prompt_text")
    # Ordinary research work, mapped onto capabilities the generator has.
    if _has(name, _INVOKE_MARKERS):
        return (AGENT_ACTOR, "invoke", "records")
    if _has(name, _APPEND_MARKERS):
        return (AGENT_ACTOR, "append", "records")
    return None
