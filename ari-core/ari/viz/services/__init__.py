"""Viz service layer (subtask 021).

Thin, unit-testable service modules extracted out of the ``routes.py`` /
``api_*`` HTTP handlers. Handlers parse the request, call a service, and
serialize the result; the endpoint paths, JSON shapes, status codes, and CORS
behaviour are unchanged (dashboard API contract — 010 §4).

Modules:

- :mod:`ari.viz.services.launch_service` — the ``.env`` discovery/parse shared
  by ``api_experiment._api_run_stage`` / ``_api_launch``.

Note (subtask 021 §7.1, StateService): the ``GET /state`` app-state builder was
**not** extracted into a service module. The frozen source-inspection contract
tests pin its literals to ``routes.py`` (``test_variable_passthrough`` reads
``routes.py`` alone for ``"frontier_score"``/``"composite"``/``"axis_mode"``) and
to the ``ui_helpers`` + ``routes`` + ``server`` concat (``test_wizard`` /
``test_page_requirements`` for ``idea.json``/``"ideas"``/``exit_code``/``Error``);
relocating the builder breaks those guards. That extraction is deferred to the
larger Phase-5 follow-on (subtask 062), where the contract snapshots can be
re-baselined deliberately.
"""
