from __future__ import annotations
"""ARI viz: api_wizard — consolidated wizard endpoint router.

All wizard-related API handlers are exposed here for clean imports.
Actual implementations live in their original modules to avoid
breaking existing imports and tests.

Wizard endpoints:
  POST /api/chat-goal        → chat-based goal refinement (api_tools)
  POST /api/generate-config  → single-shot experiment.md generation (api_tools)
  POST /api/upload           → file upload (api_tools)
  POST /api/launch           → launch experiment subprocess (api_experiment)
  GET  /api/logs             → stream logs via SSE (api_experiment)
  POST /api/run-stage        → run resume/paper/review stage (api_experiment)
"""

# Re-export wizard handlers from their source modules
from .api_tools import (
    _api_chat_goal as chat_goal,
    _api_generate_config as generate_config,
    _api_upload_file as upload_file,
)
from .api_experiment import (
    _api_launch as launch,
    _api_run_stage as run_stage,
    _api_logs_sse as logs_sse,
)

# Route table for server.py integration
WIZARD_ROUTES = {
    "/api/chat-goal":       ("POST", lambda body, **kw: chat_goal(body)),
    "/api/generate-config": ("POST", lambda body, **kw: generate_config(body)),
    "/api/launch":          ("POST", lambda body, **kw: launch(body)),
    "/api/run-stage":       ("POST", lambda body, **kw: run_stage(body)),
}
