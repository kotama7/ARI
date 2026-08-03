# ari-skill-plot runtime

- `server.py` — three MCP adapters and closed workspace validation.
- `planning.py` — native ScienceData loading, admitted metric/unit extraction,
  strict model-plan parsing, and feedback binding.
- `renderer.py` — fixed six-chart matplotlib renderer and artifact materializer.
- `prompts/figure_planner.md` — externalized spec-only planner instruction.

There is no generated-code, SVG, subprocess, filesystem-scan, or implicit VLM
execution path in the runtime.
