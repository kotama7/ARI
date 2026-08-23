"""GET /api/capabilities — the ARI_GUI_V2 server capability flag (gui_refresh Wave 1).

Direct handler tests for ``ari.viz.api_capabilities._api_capabilities`` (no
live server; the route only ``_json``-serialises the returned dict). Pins the
feature-flag policy from ``docs/concepts/gui_architecture.md``
§Capabilities and kill-switches:

* default ON (flag unset, or any value other than ``'0'`` / ``'false'``);
* env kill-switch: ``ARI_GUI_V2=0`` and ``ARI_GUI_V2=false`` turn it off;
* frozen payload shape ``{"gui_v2": bool, "server_version": "wave1"}`` — the
  frontend ``fetchCapabilities()`` (services/api/capabilities.ts) types it.
"""
from __future__ import annotations

import pytest

from ari.viz.api_capabilities import _api_capabilities


def test_default_on_when_unset(monkeypatch):
    monkeypatch.delenv("ARI_GUI_V2", raising=False)
    assert _api_capabilities() == {"gui_v2": True, "server_version": "wave1"}


def test_zero_turns_flag_off(monkeypatch):
    monkeypatch.setenv("ARI_GUI_V2", "0")
    assert _api_capabilities()["gui_v2"] is False


def test_false_turns_flag_off(monkeypatch):
    monkeypatch.setenv("ARI_GUI_V2", "false")
    assert _api_capabilities()["gui_v2"] is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "", "FALSE", "off"])
def test_other_values_stay_on(monkeypatch, value):
    # Only the literal '0' / 'false' disable the flag (kill-switch is exact;
    # 'FALSE'/'off'/'' deliberately stay ON — fail-open per the flag policy).
    monkeypatch.setenv("ARI_GUI_V2", value)
    assert _api_capabilities()["gui_v2"] is True


def test_payload_shape_frozen(monkeypatch):
    monkeypatch.delenv("ARI_GUI_V2", raising=False)
    payload = _api_capabilities()
    assert set(payload) == {"gui_v2", "server_version"}
    assert isinstance(payload["gui_v2"], bool)
    assert payload["server_version"] == "wave1"
