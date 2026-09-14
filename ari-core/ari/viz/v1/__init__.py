"""ari.viz.v1 — versioned read-only ``/api/v1`` platform (gui_refresh Wave 2a).

ADR-02 (``docs/concepts/gui_architecture.md``, "7. The backend seam"): the
canonical dashboard API lives under ``/api/v1`` and is built ON TOP of the
existing stdlib ``ThreadingHTTPServer`` — no FastAPI/uvicorn, no new runtime
dependency. This package supplies the pieces the stdlib server lacks:

- ``errors``  — typed error envelope ``{code, message, details, request_id,
  retryable}`` transported via the existing ``routes.py`` ``_status`` pop
  convention;
- ``dto``     — pydantic v2 response models, every one carrying
  ``schema_version`` (additive-change policy: a field is added, never
  removed or retyped, so an older client keeps parsing);
- ``queries`` — pure, filesystem-only read functions (no ``viz.state``
  globals, no ``os.environ`` writes — GETs have no side effects);
- ``router``  — declarative ``(method, path_template, handler)`` route table
  + per-request ``request_id`` correlation;
- ``openapi`` — deterministic OpenAPI 3.1 generator; the committed
  ``openapi.json`` is drift-guarded by ``tests/test_gui_v1_api.py``.

ADR-08: Wave 2a exposes a single virtual project ``default`` aggregating the
existing checkpoint search bases; run IDs stay checkpoint-dir-name based.
The one transport hook is the ``/api/v1/`` branch in ``routes.py`` ``do_GET``
which delegates to :func:`ari.viz.v1.router.dispatch`. The legacy unversioned
endpoints are unchanged facades; the frontend adopts this surface in Wave 2b.
"""

from __future__ import annotations
