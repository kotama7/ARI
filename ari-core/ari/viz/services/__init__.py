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
"""
