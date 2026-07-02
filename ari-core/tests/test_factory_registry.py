"""Tests for the unified factory layer (subtask 014).

Covers:
- ``ari._factory.BaseRegistry`` behaviour (eager + lazy registration, uniform
  unknown-key error, ``keys``/``as_dict``/``__contains__``).
- Parity between the composite registry keys and ``EvaluatorConfig.composite``
  (the ``Literal``), so the two can never silently drift.
- Parity between the publish backend registry keys and the
  ``publish.schema.json`` backend-name enum, with the schema-only ``s3`` gap
  asserted and documented explicitly (enum lists ``s3`` but no backend module
  exists — must raise, not resolve).
- The ``_COMPOSITES`` back-compat alias and the ``_load_backend`` wrapper still
  behave exactly as before.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest

from ari._factory import BaseRegistry


# ── BaseRegistry core behaviour ──────────────────────────────────────────────

def test_register_eager_returns_value_unchanged():
    reg: BaseRegistry[int] = BaseRegistry("thing")
    reg.register("a", 1)
    reg.register("b", 2)
    assert reg.resolve("a") == 1
    assert reg.resolve("b") == 2
    assert "a" in reg
    assert set(reg.keys()) == {"a", "b"}
    assert reg.as_dict() == {"a": 1, "b": 2}
    assert len(reg) == 2
    assert set(iter(reg)) == {"a", "b"}


def test_register_eager_preserves_object_identity():
    sentinel = object()
    reg: BaseRegistry[object] = BaseRegistry("thing")
    reg.register("k", sentinel)
    assert reg.resolve("k") is sentinel
    assert reg.as_dict()["k"] is sentinel


def test_register_lazy_invokes_loader_on_resolve():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return "loaded"

    reg: BaseRegistry[str] = BaseRegistry("thing")
    reg.register_lazy("lazy", loader)
    # Not invoked until resolved.
    assert calls["n"] == 0
    assert "lazy" in reg
    assert "lazy" in reg.keys()
    # as_dict omits lazy entries (materialising may trigger optional imports).
    assert "lazy" not in reg.as_dict()
    assert reg.resolve("lazy") == "loaded"
    assert calls["n"] == 1


def test_lazy_loader_may_raise_domain_error():
    def boom():
        raise RuntimeError("import failed")

    reg: BaseRegistry[str] = BaseRegistry("thing")
    reg.register_lazy("bad", boom)
    with pytest.raises(RuntimeError, match="import failed"):
        reg.resolve("bad")


def test_unknown_key_raises_default_keyerror_listing_valid_keys():
    reg: BaseRegistry[int] = BaseRegistry("widget")
    reg.register("a", 1)
    with pytest.raises(KeyError) as exc:
        reg.resolve("nope")
    msg = str(exc.value)
    assert "widget" in msg
    assert "nope" in msg
    assert "a" in msg


def test_unknown_key_uses_custom_error_class():
    class MyError(Exception):
        pass

    reg: BaseRegistry[int] = BaseRegistry("widget", error_cls=MyError)
    reg.register("a", 1)
    with pytest.raises(MyError):
        reg.resolve("missing")


# ── Composite registry ↔ EvaluatorConfig.composite Literal parity ────────────

def test_composite_registry_keys_match_config_literal():
    from ari.config import EvaluatorConfig
    from ari.evaluator.llm_evaluator import _COMPOSITE_REGISTRY

    literal_args = set(
        typing.get_args(EvaluatorConfig.model_fields["composite"].annotation)
    )
    assert set(_COMPOSITE_REGISTRY.keys()) == literal_args
    assert literal_args == {
        "harmonic_mean",
        "arithmetic_mean",
        "weighted_min",
        "geometric_mean",
    }


def test_composites_alias_is_dict_backed_by_registry():
    from ari.evaluator.llm_evaluator import (
        _COMPOSITE_REGISTRY,
        _COMPOSITES,
        weighted_harmonic_mean,
    )

    # Back-compat alias is a plain dict with identical keys.
    assert isinstance(_COMPOSITES, dict)
    assert set(_COMPOSITES) == set(_COMPOSITE_REGISTRY.keys())
    # Values are the exact function objects, and resolve() returns the same one.
    assert _COMPOSITES["harmonic_mean"] is weighted_harmonic_mean
    assert _COMPOSITE_REGISTRY.resolve("harmonic_mean") is _COMPOSITES["harmonic_mean"]


def test_llm_evaluator_resolves_composite_through_registry():
    from ari.evaluator.llm_evaluator import LLMEvaluator, _COMPOSITES

    for name, fn in _COMPOSITES.items():
        ev = LLMEvaluator(model="test", composite=name)
        assert ev._composite_name == name
        assert ev._compose_fn is fn


def test_llm_evaluator_rejects_unknown_composite_with_valueerror():
    from ari.evaluator.llm_evaluator import LLMEvaluator

    with pytest.raises(ValueError):
        LLMEvaluator(model="test", composite="not_a_formula")


# ── Publish backend registry ↔ publish.schema.json enum parity ───────────────

def _schema_backend_enum() -> list[str]:
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "ari"
        / "schemas"
        / "publish.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return schema["properties"]["backend"]["enum"]


def test_publish_backend_registry_keys_are_subset_of_schema_enum():
    from ari.publish import _BACKEND_REGISTRY

    keys = set(_BACKEND_REGISTRY.keys())
    assert keys == {"ari-registry", "local-tarball", "zenodo", "gh"}
    enum = set(_schema_backend_enum())
    # Every live backend key is a valid schema value.
    assert keys <= enum


def test_s3_is_schema_only_gap():
    """``s3`` is in the schema enum but has NO backend module — do NOT add one.

    Passing ``backend='s3'`` validates against the schema yet must raise a
    ``PublishError`` at dispatch time. This test pins that documented gap so it
    is never silently "fixed" by adding an s3 backend or removing the enum value
    (both would be external-contract changes, out of scope for subtask 014).
    """
    from ari.publish import PublishError, _BACKEND_REGISTRY, _load_backend

    enum = set(_schema_backend_enum())
    assert "s3" in enum
    assert "s3" not in _BACKEND_REGISTRY.keys()
    with pytest.raises(PublishError):
        _load_backend("s3")


def test_load_backend_wrapper_resolves_live_backends():
    from ari.publish import _load_backend

    for name in ("ari-registry", "local-tarball"):
        backend = _load_backend(name)
        assert hasattr(backend, "publish")
        assert hasattr(backend, "promote")


def test_load_backend_unknown_raises_publish_error():
    from ari.publish import PublishError, _load_backend

    with pytest.raises(PublishError):
        _load_backend("does-not-exist")
