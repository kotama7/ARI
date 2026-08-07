"""ari.viz — HTTP + WebSocket dashboard server.

A stdlib ``ThreadingHTTPServer`` that exposes the BFTS state, per-checkpoint
files, EAR bundles, and tooling endpoints to the bundled web frontend. There
is no FastAPI and no uvicorn anywhere under ``ari/viz`` — see
``ari/viz/v1/__init__.py``, which states the same constraint for the v1
surface.
The server entry point is ``server.py``; HTTP routes live in
``routes.py`` and the per-domain handlers under ``api_*.py``
(split out in Phase 3B).

Public symbols:
- ``serve`` — programmatic launch.
- ``main`` — CLI entry point used by ``ari viz``.

Module map (post-3B split):
- ``server`` — ``ThreadingHTTPServer`` lifecycle + WebSocket pump.
- ``routes`` — HTTP route table dispatching into handlers.
- ``websocket`` — push-side state sync to the frontend.
- ``state`` / ``state_sync`` — server-side state shared across handlers.
- ``checkpoint_finder`` / ``checkpoint_lifecycle`` — checkpoint scan + create/delete.
- ``checkpoint_api`` — ``GET /api/checkpoints/...`` handlers.
- ``file_api`` / ``node_work_api`` — file tree + node working dir browsing.
- ``ear`` — EAR bundle endpoints.
- ``ui_helpers`` / ``frontend`` / ``static`` — helpers + static assets.
- ``api_*`` — per-domain handlers (memory, settings, workflow, ollama, ...).
- ``v1`` — versioned read-only ``/api/v1`` platform (gui_refresh Wave 2a):
  typed errors, DTOs, pure queries, declarative router, OpenAPI.

See also:
- ``docs/reference/rest_api.md`` (full REST endpoint reference).
- ``git log -- ari-core/ari/viz/`` for the Phase 3B split history.
"""
