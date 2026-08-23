"""Progressive disclosure, immutable dispatch, async, artifact, and replay tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from broker import MAX_DESCRIBE_CHARS, MAX_DISCOVER_RESULTS, CatalogBroker
from catalog import build_catalog
from models import (
    AdmissionEvidenceV1,
    CatalogIndexEntryV1,
    ProviderAsyncLifecycleV1,
)
from providers import ProviderResponseV1, ProviderToolV1, StaticProviderAdapter
from storage import CassetteStore, RegistryArtifactStore, RegistryStorageError

from conftest import (
    callable_evidence,
    fixture_descriptor,
    fixture_source,
    static_source,
)


async def _broker_for(
    descriptors,
    *,
    evidence=None,
    adapter=None,
    artifact_root: Path | None = None,
):
    source = fixture_source()
    result = await build_catalog(
        [
            static_source(
                descriptors,
                source=source,
                evidence=evidence or callable_evidence(),
            )
        ]
    )
    artifacts = RegistryArtifactStore(artifact_root) if artifact_root else None
    cassettes = (
        CassetteStore(
            artifacts.root / "cassettes",
            artifact_store=artifacts,
        )
        if artifacts
        else None
    )
    return (
        CatalogBroker(
            result.lock,
            index=result.index,
            adapters={source.source_id: adapter} if adapter else {},
            artifact_store=artifacts,
            cassette_store=cassettes,
        ),
        result,
        source,
        artifacts,
        cassettes,
    )


@pytest.mark.asyncio
async def test_discover_is_bounded_paginated_and_never_exposes_leaf_schemas():
    source = fixture_source()
    descriptors = [
        fixture_descriptor(
            name=f"measurement_{index:02d}",
            source=source,
            capability_ref=f"ari.fixture.measurement.{index:02d}",
            leaf_identity=f"{source.provider_id}:measurement_{index:02d}",
        )
        for index in range(40)
    ]
    result = await build_catalog([static_source(descriptors, source=source)])
    broker = CatalogBroker(result.lock, index=result.index)

    first = broker.discover("measurement", top_k=1_000)
    assert len(first["results"]) == MAX_DISCOVER_RESULTS
    assert first["next_cursor"]
    assert all("input_schema" not in item for item in first["results"])
    assert len(json.dumps(first)) < 40_000

    second = broker.discover(
        "measurement",
        constraints={"cursor": first["next_cursor"]},
        top_k=MAX_DISCOVER_RESULTS,
    )
    assert len(second["results"]) == 15
    assert not second["next_cursor"]
    assert {item["tool_ref"] for item in first["results"]}.isdisjoint(
        item["tool_ref"] for item in second["results"]
    )


@pytest.mark.asyncio
async def test_describe_pages_large_schema_and_binds_cursor_to_tool():
    source = fixture_source()
    huge_schema = {
        "type": "object",
        "properties": {
            f"field_{index:03d}": {
                "type": "string",
                "description": "bounded schema detail " * 8,
            }
            for index in range(100)
        },
    }
    descriptor = fixture_descriptor(
        source=source, input_schema=huge_schema, defaults={}
    )
    other = fixture_descriptor(name="other", source=source)
    result = await build_catalog([static_source([descriptor, other], source=source)])
    broker = CatalogBroker(result.lock, index=result.index)

    page = broker.describe(descriptor.tool_ref, section="schema")
    assert len(page["content"]) == MAX_DESCRIBE_CHARS
    assert page["next_cursor"]
    pieces = [page["content"]]
    cursor = page["next_cursor"]
    while cursor:
        page = broker.describe(descriptor.tool_ref, section="schema", cursor=cursor)
        pieces.append(page["content"])
        cursor = page["next_cursor"]
    parsed = json.loads("".join(pieces))
    assert len(parsed["input_schema"]["properties"]) == 100
    with pytest.raises(Exception, match="cursor does not belong"):
        broker.describe(
            other.tool_ref,
            section="schema",
            cursor=pieces
            and broker.describe(descriptor.tool_ref, section="schema")["next_cursor"],
        )


@pytest.mark.asyncio
async def test_unadmitted_and_unqualified_invocation_fail_closed():
    descriptor = fixture_descriptor()
    broker, _result, _source, _artifacts, _cassettes = await _broker_for(
        [descriptor], evidence=AdmissionEvidenceV1()
    )
    unadmitted = await broker.invoke(descriptor.tool_ref, {"value": 1})
    assert unadmitted["status"] == "error"
    assert unadmitted["error"]["kind"] == "admission"

    bare = await broker.invoke("measure", {"value": 1})
    assert bare["status"] == "error"
    assert bare["error"]["kind"] == "admission"


@pytest.mark.asyncio
async def test_strict_record_applies_declared_defaults_and_rejects_bad_arguments(
    tmp_path: Path,
):
    descriptor = fixture_descriptor()
    adapter = StaticProviderAdapter(
        [ProviderToolV1(name="measure")],
        {
            "measure": ProviderResponseV1(
                text='{"status":"ok","value":3}',
                structured={"status": "ok", "value": 3},
            )
        },
    )
    broker, _result, _source, _artifacts, _cassettes = await _broker_for(
        [descriptor], adapter=adapter, artifact_root=tmp_path / "ear" / "catalog"
    )
    invalid_type = await broker.invoke(
        descriptor.tool_ref, {"value": "not-a-number"}, mode="live"
    )
    assert invalid_type["status"] == "error"
    assert invalid_type["error"]["kind"] == "protocol"

    unknown = await broker.invoke(
        descriptor.tool_ref,
        {"value": 3, "undeclared": True},
        mode="record",
    )
    assert unknown["status"] == "error"
    assert "unknown fields" in unknown["error"]["message"]

    recorded = await broker.invoke(descriptor.tool_ref, {"value": 3}, mode="record")
    assert recorded["status"] == "ok"
    assert adapter.calls[-1][1] == {"scale": 1.0, "value": 3}


@pytest.mark.asyncio
async def test_record_large_result_and_replay_without_provider(
    tmp_path: Path,
):
    descriptor = fixture_descriptor()
    large_text = json.dumps({"status": "ok", "payload": "x" * 12_000})
    adapter = StaticProviderAdapter(
        [ProviderToolV1(name="measure")],
        {"measure": ProviderResponseV1(text=large_text)},
    )
    artifact_root = tmp_path / "ear" / "catalog"
    broker, result, source, artifacts, cassettes = await _broker_for(
        [descriptor], adapter=adapter, artifact_root=artifact_root
    )
    recorded = await broker.invoke(descriptor.tool_ref, {"value": 7}, mode="record")
    assert recorded["status"] == "ok"
    assert recorded["content_truncated"] is True
    assert recorded["artifacts"][0]["logical_role"] == "mcp-raw-result"
    assert artifacts is not None and cassettes is not None
    assert artifacts.get(recorded["artifacts"][0]["logical_name"]).is_file()
    assert any("raw-cassettes" in path.as_posix() for path in artifacts.list())
    assert len(cassettes.list_records()) == 1
    assert (artifact_root / "CATALOG.lock").is_file()
    provenance = json.loads((artifact_root / "catalog-provenance.json").read_text())
    assert provenance["catalog_digest"] == result.lock.catalog_digest

    offline = CatalogBroker(
        result.lock,
        index=result.index,
        adapters={},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )
    replayed = await offline.invoke(descriptor.tool_ref, {"value": 7}, mode="replay")
    assert replayed["status"] == "ok"
    assert replayed["structured_content"]["_registry_replay"]["cassette_key"]
    assert len(adapter.calls) == 1, "offline replay must not contact the provider"
    assert result.lock.sources[0].source_id == source.source_id


def test_cassette_store_rejects_credentials_but_allows_token_count(tmp_path: Path):
    store = CassetteStore(tmp_path / "cassettes")
    common = {
        "tool_ref": "ari-tool://fixture/measure@" + "sha256:" + "0" * 64,
        "catalog_digest": "sha256:" + "1" * 64,
        "policy_digest": "sha256:" + "2" * 64,
        "selection_reason": "test",
        "rejected_candidates": [],
        "result_envelope": {"status": "ok"},
    }

    with pytest.raises(RegistryStorageError, match="credential fields"):
        store.record(
            **common,
            arguments={"api_key": "must-not-persist"},
            raw_response=ProviderResponseV1(text='{"status":"ok"}'),
        )
    with pytest.raises(RegistryStorageError, match="credential material"):
        store.record(
            **common,
            arguments={"token_count": 12},
            raw_response=ProviderResponseV1(
                text='{"status":"ok","access_token":"must-not-persist"}'
            ),
        )

    cassette = store.record(
        **common,
        arguments={"token_count": 12},
        raw_response=ProviderResponseV1(
            text='{"status":"ok","token_count":12}',
            structured={"status": "ok", "token_count": 12},
        ),
    )
    assert cassette.arguments == {"token_count": 12}


@pytest.mark.asyncio
async def test_catalog_broker_snapshot_does_not_change_after_new_build():
    source = fixture_source()
    first_tool = fixture_descriptor(source=source)
    first = await build_catalog([static_source([first_tool], source=source)])
    broker = CatalogBroker(first.lock, index=first.index)
    second_tool = fixture_descriptor(name="later", source=source)
    second = await build_catalog(
        [static_source([first_tool, second_tool], source=source)]
    )

    assert broker.discover("", top_k=25)["matched_count"] == 1
    assert len(second.lock.tools) == 2
    assert broker.lock.catalog_digest == first.lock.catalog_digest


@pytest.mark.asyncio
async def test_catalog_broker_rejects_tampered_derived_index():
    source = fixture_source()
    descriptor = fixture_descriptor(source=source)
    result = await build_catalog([static_source([descriptor], source=source)])
    original = result.index.entries[0]
    forged = result.index.model_copy(
        update={
            "entries": [
                CatalogIndexEntryV1(
                    **{
                        **original.model_dump(mode="json"),
                        "description": "unreviewed search manipulation",
                        "terms": ["forged-ranking-term"],
                    }
                )
            ]
        }
    )

    with pytest.raises(Exception, match="exact derivation"):
        CatalogBroker(result.lock, index=forged)


@pytest.mark.asyncio
async def test_async_submit_status_result_cancel_and_unknown_state(tmp_path: Path):
    lifecycle = ProviderAsyncLifecycleV1(
        handle_field="job_id",
        state_field="status",
        status_tool="job_status",
        result_tool="job_result",
        cancel_tool="job_cancel",
        handle_argument="job_id",
        submitted_states=["SUBMITTED"],
        running_states=["RUNNING"],
        succeeded_states=["COMPLETED"],
        failed_states=["FAILED"],
        cancelled_states=["CANCELLED"],
    )
    descriptor = fixture_descriptor(async_lifecycle=lifecycle)
    adapter = StaticProviderAdapter(
        [ProviderToolV1(name="measure")],
        {
            "measure": ProviderResponseV1(
                text='{"job_id":"job-1","status":"SUBMITTED"}',
                structured={"job_id": "job-1", "status": "SUBMITTED"},
            ),
            "job_status": ProviderResponseV1(
                text='{"status":"RUNNING"}', structured={"status": "RUNNING"}
            ),
            "job_result": ProviderResponseV1(
                text='{"status":"COMPLETED","value":42}',
                structured={"status": "COMPLETED", "value": 42},
            ),
            "job_cancel": ProviderResponseV1(
                text='{"status":"CANCELLED"}',
                structured={"status": "CANCELLED"},
            ),
        },
    )
    broker, _result, _source, _artifacts, _cassettes = await _broker_for(
        [descriptor], adapter=adapter, artifact_root=tmp_path / "ear" / "catalog"
    )
    submitted = await broker.invoke(descriptor.tool_ref, {"value": 1})
    assert submitted["status"] == "submitted"
    handle = submitted["structured_content"]["registry_handle"]

    running = await broker.get_status(handle)
    assert running["status"] == "running"
    completed = await broker.get_result(handle)
    assert completed["status"] == "ok"
    assert completed["structured_content"]["value"] == 42
    cancelled = await broker.cancel(handle)
    assert cancelled["status"] == "cancelled"

    adapter.responses["job_status"] = ProviderResponseV1(
        text="provider lifecycle failed",
        structured={"status": "RUNNING"},
        is_error=True,
    )
    provider_error = await broker.get_status(handle)
    assert provider_error["status"] == "error"
    assert "MCP error" in provider_error["error"]["message"]

    adapter.responses["job_status"] = ProviderResponseV1(
        text='{"status":"PROVIDER_MYSTERY"}',
        structured={"status": "PROVIDER_MYSTERY"},
    )
    unknown = await broker.get_status(handle)
    assert unknown["status"] == "error"
    assert "unknown async state" in unknown["error"]["message"]

    tampered = dict(handle)
    tampered["provider_handle"] = "other-job"
    invalid = await broker.get_status(tampered)
    assert invalid["status"] == "error"
    assert "handle" in invalid["error"]["message"]


@pytest.mark.asyncio
async def test_async_record_context_survives_broker_restart(tmp_path: Path):
    lifecycle = ProviderAsyncLifecycleV1(
        handle_field="job_id",
        state_field="status",
        status_tool="job_status",
        result_tool="job_result",
        submitted_states=["SUBMITTED"],
        running_states=["RUNNING"],
        succeeded_states=["COMPLETED"],
        failed_states=["FAILED"],
        cancelled_states=["CANCELLED"],
    )
    descriptor = fixture_descriptor(async_lifecycle=lifecycle)
    adapter = StaticProviderAdapter(
        [ProviderToolV1(name="measure")],
        {
            "measure": ProviderResponseV1(
                text='{"job_id":"portable-job","status":"SUBMITTED"}',
                structured={"job_id": "portable-job", "status": "SUBMITTED"},
            ),
            "job_result": ProviderResponseV1(
                text='{"status":"COMPLETED","value":99}',
                structured={"status": "COMPLETED", "value": 99},
            ),
        },
    )
    artifact_root = tmp_path / "ear" / "catalog"
    broker, result, source, artifacts, cassettes = await _broker_for(
        [descriptor], adapter=adapter, artifact_root=artifact_root
    )
    submitted = await broker.invoke(descriptor.tool_ref, {"value": 4}, mode="record")
    handle = submitted["structured_content"]["registry_handle"]
    assert any("pending" in path.parts for path in artifacts.list())

    restarted = CatalogBroker(
        result.lock,
        index=result.index,
        adapters={source.source_id: adapter},
        artifact_store=artifacts,
        cassette_store=cassettes,
    )
    completed = await restarted.get_result(handle)
    assert completed["status"] == "ok"
    assert completed["structured_content"]["value"] == 99

    offline = CatalogBroker(
        result.lock,
        index=result.index,
        artifact_store=artifacts,
        cassette_store=cassettes,
    )
    replayed = await offline.invoke(descriptor.tool_ref, {"value": 4}, mode="replay")
    assert replayed["status"] == "ok"
    assert replayed["structured_content"]["value"] == 99
