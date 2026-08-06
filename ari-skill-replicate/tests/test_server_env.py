"""Tests for server.py's GUI-env-var override resolution.

The GUI/wizard persists rubric_gen_target_leaves / rubric_gen_temperature
as ARI_RUBRIC_GEN_* env vars. These must be honored
when the workflow stage doesn't pass the corresponding kwarg.
"""

from __future__ import annotations


import pytest

from server import _resolve_env_overrides


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in (
        "ARI_RUBRIC_GEN_TARGET_LEAVES",
        "ARI_RUBRIC_GEN_TEMPERATURE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_no_env_returns_kwarg_defaults():
    assert _resolve_env_overrides(0, 0.0) == (0, 0.0)
    assert _resolve_env_overrides(50, 0.5) == (50, 0.5)


def test_target_leaves_env_overrides(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC_GEN_TARGET_LEAVES", "120")
    assert _resolve_env_overrides(0, 0.0)[0] == 120


def test_temperature_env_overrides(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC_GEN_TEMPERATURE", "0.7")
    assert _resolve_env_overrides(0, 0.0)[1] == pytest.approx(0.7)


def test_invalid_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC_GEN_TARGET_LEAVES", "not-a-number")
    monkeypatch.setenv("ARI_RUBRIC_GEN_TEMPERATURE", "abc")
    assert _resolve_env_overrides(99, 0.3) == (99, 0.3)


def test_empty_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("ARI_RUBRIC_GEN_TARGET_LEAVES", "")
    monkeypatch.setenv("ARI_RUBRIC_GEN_TEMPERATURE", "")
    assert _resolve_env_overrides(42, 0.2) == (42, 0.2)
