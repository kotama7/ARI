"""ReAct-message helpers extracted from agent/loop.py (Phase 3D).

Two pure functions that inspect a flat message-history list:

- :func:`_extract_job_ids` — pull async job IDs out of MCP tool
  messages (sbatch stdout + JSON ``job_id`` fields).
- :func:`_tool_was_called` — scan the assistant turns for a named
  tool call.

Both used to live as module-level functions in ``ari.agent.loop``;
the call-site continues to import them under their original names so
external callers keep working unchanged.
"""

from __future__ import annotations

import json


def _extract_job_ids(messages: list[dict], job_id_key: str) -> list[str]:
    """Extract async job IDs from tool messages (JSON field and sbatch stdout)."""
    import re as _re_jid
    seen: set[str] = set()
    ids: list[str] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        # Direct "Submitted batch job NNN" scan (eliminates need for synthetic inject)
        for _sbatch_m in _re_jid.finditer(r"Submitted batch job (\d+)", content):
            jid = _sbatch_m.group(1)
            if jid not in seen:
                seen.add(jid)
                ids.append(jid)
        # JSON structured result
        try:
            r = json.loads(content)
            if isinstance(r, dict) and "result" in r:
                r = json.loads(r["result"])
            if isinstance(r, dict) and job_id_key in r:
                jid = str(r[job_id_key])
                if jid not in seen:
                    seen.add(jid)
                    ids.append(jid)
        except Exception:
            pass
    return ids


def _tool_was_called(messages: list[dict], tool_name: str) -> bool:
    """Check whether the message history contains a call to the specified tool."""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("function", {}).get("name") == tool_name:
                return True
    return False
