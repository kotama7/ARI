% snapshot-from: ari-core/ari/prompts/llm/mcp_name_resolution.md@8b16afc83b1ba5a80de1fe0d92092c8dce33649cfdf9a8cfdde0271c9805cd43 @ commit 758cce4e2666
% DO NOT EDIT — regenerate via `make snapshot-prompts`.
%
## TOOL NAME RESOLUTION — read before your first tool call

The instructions above refer to tools by their BARE names. The tools
actually available to you are MCP tools with namespaced names. When the
instructions say to call `X()`, call the name on the RIGHT:
{rows}
A bare name is NOT callable here and fails with "No such tool
available". Do not re-probe a failed bare name — translate it using
this table and call the qualified name.
