"""Viz service layer (subtasks 021, 062).

Thin, unit-testable service modules extracted out of the ``routes.py`` /
``api_*`` HTTP handlers. Handlers parse the request, call a service, and
serialize the result; the endpoint paths, JSON shapes, status codes, and CORS
behaviour are unchanged (dashboard API contract — 010 §4).

Modules:

- :mod:`ari.viz.services.launch_service` — the ``.env`` discovery/parse shared
  by ``api_experiment._api_run_stage`` / ``_api_launch`` (subtask 021).
- :mod:`ari.viz.services.state_service` — the ``GET /state`` app-state builder
  (:func:`~ari.viz.services.state_service.build_app_state`), extracted from the
  ~450-line inline ``routes.py`` ``do_GET`` branch (subtask 062, StateService).
- :mod:`ari.viz.services.file_service` — the FileService (subtask 023): the one
  traversal-validation guard (:func:`~ari.viz.services.file_service.safe_resolve`),
  the named byte-size limits, the file-classification sets, the canonical
  content-type table, and the read/write/delete helpers. ``file_api.py`` and
  ``node_work_api.py`` delegate their guards/limits/sets/IO to it; wire behaviour
  (endpoint paths, JSON keys, error sentinels, byte thresholds) is unchanged.

StateService (subtask 062): the ``GET /state`` builder that 021 §7.1 DEFERRED is
now in :mod:`state_service`. ``routes.py`` keeps the ``elif self.path == "/state"``
comparison (so ``test_contract_snapshots``'s ``_scan_route_literals`` still finds
``/state``) and the byte-identical HTTP response; only the builder body moved.
The frozen source-inspection guards that pinned the ``/state`` literals
(``"frontier_score"``/``"composite"``/``"axis_mode"``/``experiment_config``/
``gap_analysis``/``idea_primary_metric``/``_lc_data.get(...)``) to ``routes.py``
or the ``ui_helpers``+``websocket``+``routes``+``server`` concat were updated as
**pure location pointers** — the concat helpers (and ``test_variable_passthrough``'s
``_routes()``) now also read ``services/state_service.py``, asserting the SAME
literals at the new location.

DEFERRED to a later subtask (still pinned by frozen source-inspection tests,
would require weakening a contract to land here):

- **Route registry / declarative dispatch table** (062 §7.1): the ``do_GET`` /
  ``do_POST`` ``if/elif`` chain cannot be replaced by a data-driven table because
  ``test_contract_snapshots.py::test_viz_route_literals_no_drift`` AST-scans
  ``routes.py`` for ``self.path == "..."`` / ``.startswith`` / ``.endswith``
  comparisons (``scripts/snapshot_contracts.py::_scan_route_literals``). A table
  removes those comparisons and drops ~90 golden literals — a HARD contract-snapshot
  drift that must not be weakened.
- **Full LaunchService** (``ARI_*`` env mapping + ``subprocess.Popen``, 062 §7.2):
  pinned to ``api_experiment.py`` by ``test_gui_env_propagation`` /
  ``test_launch_config`` (source-inspection); only the shared ``.env`` parse was
  extracted (021's :mod:`launch_service`).
- **routes.py inline file-serving** (subtask 023 §3.3, REVIEW_REQUIRED): the
  ``/codefile``, ``/api/checkpoint/<id>/paper.<ext>``, ``.../file/raw``,
  ``/logo``, ``/static``, ``_serve_spa_index`` byte serves and the
  ``_write_access_log`` write stay inline in ``routes.py``. Relocating them into
  :mod:`file_service` would (a) move literals out of the file that ~8 frozen
  concat source-inspection tests read (``test_server.py`` /
  ``test_data_flow.py`` / ``test_page_requirements.py`` /
  ``test_settings_roundtrip.py`` / ``test_launch_config.py`` /
  ``test_default_provider.py`` / ``test_api_lineage_decisions.py`` /
  ``test_file_explorer.py``) plus break the route-literal snapshot
  (``test_contract_snapshots.py::test_viz_route_literals_no_drift``), and (b) the
  two content-type maps differ by a ``.gif`` member — ``/codefile`` maps ``.gif``
  → ``image/gif`` while ``.../file/raw`` falls back to
  ``application/octet-stream`` — so folding them into one shared table is a
  **wire change**, not a mechanical move. :func:`file_service.content_type_for`
  is the canonical table that a dedicated, contract-verified subtask will adopt.
  The weak ``/codefile`` substring guard (``"checkpoints" in str(p)``) is a
  separate REVIEW_REQUIRED security follow-up (``010`` §4) and is kept identical.
- **api_tools upload/delete** (subtask 023 §3.4): ``_api_upload_file`` /
  ``_api_upload_delete`` are source-inspected by ``test_data_flow.py``
  (``Path.cwd()``/import scans); their byte-write/unlink is low value to relocate
  and is deferred with the routes.py serving.
"""
