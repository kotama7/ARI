"""Canonical identity, graph safety, admission, overlap, and scale tests."""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path

import pytest

from admission import AdmissionEngine, AdmissionPolicyV1
from catalog import (
    CatalogImmutableError,
    build_catalog,
    load_catalog_index,
    load_catalog_lock,
    write_catalog_lock,
    write_reviewable_catalog,
)
from models import (
    CatalogLockV1,
    OriginHopV1,
    catalog_lock_digest,
    sha256_digest,
)

from conftest import (
    callable_evidence,
    fixture_descriptor,
    fixture_source,
    static_source,
)


def test_tool_ref_is_order_independent_and_execution_sensitive():
    schema_a = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "string"},
        },
        "required": ["x", "y"],
    }
    schema_b = {
        "required": ["y", "x"],
        "properties": {
            "y": {"type": "string"},
            "x": {"type": "integer"},
        },
        "type": "object",
    }
    first = fixture_descriptor(input_schema=schema_a, defaults={})
    reordered = fixture_descriptor(input_schema=schema_b, defaults={})
    assert first.tool_ref == reordered.tool_ref

    changed = [
        fixture_descriptor(
            input_schema={
                **schema_a,
                "properties": {**schema_a["properties"], "z": {"type": "number"}},
            },
            defaults={},
        ),
        fixture_descriptor(defaults={"scale": 2.0}),
        fixture_descriptor(provider_version="1.0.1"),
        fixture_descriptor(adapter_digest=sha256_digest({"adapter": "changed"})),
        fixture_descriptor(semantics={"quantity": "different"}),
    ]
    assert all(item.tool_ref != first.tool_ref for item in changed)


def test_policy_reassessment_does_not_change_execution_identity():
    descriptor = fixture_descriptor()
    evidence = callable_evidence(
        dependencies_pinned=True,
        replay_fixture_digest=sha256_digest({"fixture": 1}),
    )
    callable_policy = AdmissionPolicyV1(required_level="callable")
    reproducible_policy = AdmissionPolicyV1(required_level="reproducible")

    first = AdmissionEngine(callable_policy).evaluate(descriptor, evidence)
    second = AdmissionEngine(reproducible_policy).evaluate(descriptor, evidence)
    assert first.tool_ref == second.tool_ref == descriptor.tool_ref
    assert first.policy_digest != second.policy_digest
    assert first.level == second.level == "reproducible"
    assert first.invokable and second.invokable


@pytest.mark.asyncio
async def test_direct_credential_arguments_are_never_callable():
    descriptor = fixture_descriptor(
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "api_key": {"type": "string"},
                "token_count": {"type": "integer"},
            },
            "required": ["value", "api_key"],
        },
        defaults={},
    )
    result = await build_catalog(
        [static_source([descriptor], evidence=callable_evidence())]
    )
    decision = result.lock.admissions[0]
    assert decision.level == "discovered"
    assert any("credential-scope" in reason for reason in decision.reasons)
    assert all("token_count" not in reason for reason in decision.reasons)


@pytest.mark.asyncio
async def test_catalog_rejects_admission_policy_digest_inconsistency():
    descriptor = fixture_descriptor()
    result = await build_catalog([static_source([descriptor])])
    payload = result.lock.model_dump(mode="json")
    payload["admissions"][0]["policy_digest"] = sha256_digest({"policy": "forged"})
    payload["catalog_digest"] = catalog_lock_digest(payload)

    with pytest.raises(ValueError, match="catalog policy_digest"):
        CatalogLockV1.model_validate(payload)


@pytest.mark.asyncio
async def test_origin_cycle_depth_and_hidden_leaf_are_quarantined():
    source = fixture_source()
    leaf = f"{source.provider_id}:measure"
    cycle = fixture_descriptor(
        source=source,
        origin_chains=[
            [
                OriginHopV1(kind="source", id=source.source_id),
                OriginHopV1(kind="collection", id="loop"),
                OriginHopV1(kind="collection", id="loop"),
                OriginHopV1(kind="tool", id=leaf),
            ]
        ],
    )
    hidden = fixture_descriptor(
        name="hidden",
        source=source,
        leaf_identity=f"{source.provider_id}:hidden",
        origin_chains=[
            [
                OriginHopV1(kind="source", id=source.source_id),
                OriginHopV1(kind="provider", id=source.provider_id),
            ]
        ],
    )
    depth_leaf = f"{source.provider_id}:deep"
    deep = fixture_descriptor(
        name="deep",
        source=source,
        leaf_identity=depth_leaf,
        origin_chains=[
            [
                OriginHopV1(kind="source", id=source.source_id),
                *[
                    OriginHopV1(kind="collection", id=f"level-{index}")
                    for index in range(8)
                ],
                OriginHopV1(kind="tool", id=depth_leaf),
            ]
        ],
    )
    result = await build_catalog(
        [static_source([cycle, hidden, deep], source=source)],
        max_origin_depth=6,
    )
    assert result.lock.tools == []
    assert {item.reason_code for item in result.lock.quarantined} == {
        "cycle",
        "depth-exceeded",
        "hidden-leaf",
    }


@pytest.mark.asyncio
async def test_exact_duplicates_collapse_and_near_matches_remain_distinct():
    source_a = fixture_source("fixture.a", provider_id="fixture.shared")
    source_b = fixture_source("fixture.b", provider_id="fixture.shared")
    duplicate_a = fixture_descriptor(source=source_a)
    duplicate_b = fixture_descriptor(source=source_b)
    assert duplicate_a.tool_ref == duplicate_b.tool_ref

    source_c = fixture_source("fixture.c", provider_id="fixture.alternative")
    near_match = fixture_descriptor(
        source=source_c,
        capability_ref=duplicate_a.capability_ref,
        semantics={"quantity": "related but not proven equivalent"},
    )
    result = await build_catalog(
        [
            static_source([duplicate_a], source=source_a),
            static_source([duplicate_b], source=source_b),
            static_source([near_match], source=source_c),
        ]
    )
    assert len(result.lock.tools) == 2
    merged = next(
        tool for tool in result.lock.tools if tool.tool_ref == duplicate_a.tool_ref
    )
    assert merged.source_ids == ["fixture.a", "fixture.b"]
    relationships = {item.relationship for item in result.lock.overlaps}
    assert "exact-duplicate" in relationships
    assert "semantic-near-match" in relationships


@pytest.mark.asyncio
async def test_overlap_distinguishes_same_backend_from_independent_method():
    sources = [
        fixture_source("fixture.one", provider_id="fixture.one-provider"),
        fixture_source("fixture.two", provider_id="fixture.two-provider"),
        fixture_source("fixture.three", provider_id="fixture.three-provider"),
    ]
    same_backend_a = fixture_descriptor(
        name="method_a",
        source=sources[0],
        capability_ref="ari.fixture.compare",
        independence_group="physical-backend-1",
    )
    same_backend_b = fixture_descriptor(
        name="method_b",
        source=sources[1],
        capability_ref="ari.fixture.compare",
        independence_group="physical-backend-1",
    )
    independent_a = fixture_descriptor(
        name="independent_a",
        source=sources[0],
        capability_ref="ari.fixture.independent",
        independence_group="method-1",
        equivalence_key="same-observable-v1",
    )
    independent_b = fixture_descriptor(
        name="independent_b",
        source=sources[2],
        capability_ref="ari.fixture.independent",
        independence_group="method-2",
        equivalence_key="same-observable-v1",
    )
    result = await build_catalog(
        [
            static_source([same_backend_a, independent_a], source=sources[0]),
            static_source([same_backend_b], source=sources[1]),
            static_source([independent_b], source=sources[2]),
        ]
    )
    by_capability = {item.capability_ref: item for item in result.lock.overlaps}
    assert by_capability["ari.fixture.compare"].relationship == "same-backend"
    assert by_capability["ari.fixture.independent"].relationship == "independent-method"


@pytest.mark.asyncio
async def test_catalog_rebuild_is_deterministic_and_updates_are_pending(tmp_path: Path):
    source = fixture_source()
    descriptor = fixture_descriptor(source=source)
    first = await build_catalog([static_source([descriptor], source=source)])
    second = await build_catalog([static_source([descriptor], source=source)])
    assert first.lock.model_dump(mode="json") == second.lock.model_dump(mode="json")
    assert first.index.model_dump(mode="json") == second.index.model_dump(mode="json")

    lock_path = tmp_path / "CATALOG.lock"
    index_path = tmp_path / "catalog.index.json"
    created = write_reviewable_catalog(
        lock_path=lock_path,
        index_path=index_path,
        result=first,
    )
    assert created["status"] == "created"
    assert load_catalog_lock(lock_path).catalog_digest == first.lock.catalog_digest
    assert (
        load_catalog_index(
            index_path, expected_catalog_digest=first.lock.catalog_digest
        ).catalog_digest
        == first.lock.catalog_digest
    )

    changed_descriptor = fixture_descriptor(name="other", source=source)
    changed = await build_catalog(
        [static_source([descriptor, changed_descriptor], source=source)]
    )
    report = write_reviewable_catalog(
        lock_path=lock_path,
        index_path=index_path,
        result=changed,
    )
    assert report["status"] == "pending-review"
    assert load_catalog_lock(lock_path).catalog_digest == first.lock.catalog_digest
    assert Path(report["pending_lock"]).is_file()
    assert json.loads(Path(report["diff"]).read_text())["tools_added"] == [
        changed_descriptor.tool_ref
    ]
    with pytest.raises(CatalogImmutableError):
        write_catalog_lock(lock_path, changed.lock)


@pytest.mark.asyncio
async def test_single_source_imports_one_thousand_tools_with_bounded_resources():
    source = fixture_source()
    descriptors = [
        fixture_descriptor(
            name=f"measure_{index:04d}",
            source=source,
            capability_ref=f"ari.fixture.measure.{index:04d}",
            leaf_identity=f"{source.provider_id}:measure_{index:04d}",
        )
        for index in range(1_000)
    ]
    tracemalloc.start()
    started = time.monotonic()
    result = await build_catalog([static_source(descriptors, source=source)])
    elapsed = time.monotonic() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(result.lock.sources) == 1
    assert len(result.lock.tools) == 1_000
    assert len(result.index.entries) == 1_000
    assert elapsed < 10
    assert peak < 192 * 1024 * 1024
    assert len({tool.tool_ref for tool in result.lock.tools}) == 1_000
