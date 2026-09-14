# Scientific tool federation

Use this Skill when an experiment needs capabilities from a large reviewed MCP
collection without placing every leaf schema in the model context.

1. Call `discover` with a capability-oriented query and constraints.
2. Use `describe` on promising opaque `tool_ref` values. Inspect admission,
   provenance, units, semantics, limitations, and independence groups before
   choosing a method.
3. Call `invoke` with the exact selected `tool_ref`. Prefer `record` for evidence
   that must be replayed; use `replay` only with the matching immutable catalog.
4. If the result is submitted, pass its complete registry handle to
   `get_status` and `get_result` without editing it.

Do not infer equivalence from names or capability labels. Keep disagreements
between independent methods as separate results with separate provenance. A
`discovered` candidate is not executable, and `callable` alone is not evidence
that a numerical or scientific method is valid for the experiment.
