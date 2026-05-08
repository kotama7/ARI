"""Tests for the GUI publish.yaml read/write API.

The Results page uses these endpoints to let users author/edit
{checkpoint}/ear/publish.yaml without dropping to a shell. The API:
- GET  /api/ear/<run_id>/publish-yaml — returns existing content or a
  default template (so the editor can pre-fill on first open).
- POST /api/ear/<run_id>/publish-yaml — accepts {"text": "..."} (raw)
  or {"data": {...}} (structured) and writes the file.
"""

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def fake_checkpoint(monkeypatch, tmp_path):
    """Create a checkpoint with an ear/ dir and stub _resolve_checkpoint_dir."""
    ckpt = tmp_path / "checkpoints" / "20260430_test_run"
    (ckpt / "ear").mkdir(parents=True)
    from ari.viz import api_state

    def _stub_resolve(run_id: str):
        if run_id == "20260430_test_run":
            return ckpt
        return None

    monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", _stub_resolve)
    return ckpt


def test_get_returns_default_when_missing(fake_checkpoint):
    from ari.viz.api_state import _api_ear_publish_yaml_get

    r = _api_ear_publish_yaml_get("20260430_test_run")
    assert r.get("exists") is False
    assert "include" in r["data"]
    assert "exclude" in r["data"]
    assert isinstance(r["data"]["include"], list)
    assert r["data"]["max_file_mb"] == 100
    # Text round-trips back to the same structure
    assert yaml.safe_load(r["text"])["include"] == r["data"]["include"]


def test_post_then_get_roundtrip(fake_checkpoint):
    from ari.viz.api_state import _api_ear_publish_yaml_get, _api_ear_publish_yaml_set

    payload = {
        "data": {
            "include": ["src/**/*.py", "README.md"],
            "exclude": ["**/__pycache__/**"],
            "max_file_mb": 50,
            "license": "Apache-2.0",
            "visibility": "public",
        }
    }
    r = _api_ear_publish_yaml_set("20260430_test_run", json.dumps(payload).encode())
    assert r.get("ok"), r
    # File on disk matches what we sent
    yml = fake_checkpoint / "ear" / "publish.yaml"
    assert yml.exists()
    on_disk = yaml.safe_load(yml.read_text())
    assert on_disk["include"] == ["src/**/*.py", "README.md"]
    assert on_disk["license"] == "Apache-2.0"
    # GET now reports exists=True with the same data
    g = _api_ear_publish_yaml_get("20260430_test_run")
    assert g.get("exists") is True
    assert g["data"]["license"] == "Apache-2.0"


def test_post_rejects_non_mapping(fake_checkpoint):
    from ari.viz.api_state import _api_ear_publish_yaml_set

    r = _api_ear_publish_yaml_set(
        "20260430_test_run",
        json.dumps({"text": "- not a mapping\n- still not\n"}).encode(),
    )
    assert "error" in r
    assert "mapping" in r["error"].lower()


def test_post_rejects_non_list_include(fake_checkpoint):
    from ari.viz.api_state import _api_ear_publish_yaml_set

    r = _api_ear_publish_yaml_set(
        "20260430_test_run",
        json.dumps({"data": {"include": "not-a-list", "exclude": []}}).encode(),
    )
    assert "error" in r
    assert "list" in r["error"].lower()


def test_post_accepts_raw_text(fake_checkpoint):
    from ari.viz.api_state import _api_ear_publish_yaml_set

    raw = "include:\n  - '*.py'\nexclude: []\nlicense: BSD-3-Clause\n"
    r = _api_ear_publish_yaml_set(
        "20260430_test_run", json.dumps({"text": raw}).encode()
    )
    assert r.get("ok"), r
    on_disk = (fake_checkpoint / "ear" / "publish.yaml").read_text()
    assert "BSD-3-Clause" in on_disk


def test_get_unknown_checkpoint_errors(monkeypatch, tmp_path):
    from ari.viz import api_state

    monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", lambda r: None)
    r = api_state._api_ear_publish_yaml_get("nope")
    assert r.get("error") == "checkpoint not found"


def test_get_no_ear_dir_errors(monkeypatch, tmp_path):
    from ari.viz import api_state

    ckpt = tmp_path / "ckpt-without-ear"
    ckpt.mkdir()
    monkeypatch.setattr(api_state, "_resolve_checkpoint_dir", lambda r: ckpt)
    r = api_state._api_ear_publish_yaml_get("any")
    assert "no EAR directory" in r.get("error", "")
