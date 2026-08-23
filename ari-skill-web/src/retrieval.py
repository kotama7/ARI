"""Shared retrieval normalization and content-addressed record/replay support."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ari.public.execution import WorkspaceRefV1
from ari.public.research_contract import (
    CitationEdgeV1,
    ResearchArtifactRefV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
    load_survey_snapshot_ref,
)


PROVIDER_VERSIONS = {
    "semantic-scholar": "graph-v1",
    "arxiv": "atom-api/v1",
    "alphaxiv": "mcp/v1",
    "duckduckgo": "ddgs-text/v1",
    "url": "http-fetch/v1",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _authors(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    result: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        value = str(name or "").strip()
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _external_aliases(raw: dict[str, Any]) -> tuple[str, ...]:
    external = raw.get("externalIds") or raw.get("external_ids") or {}
    if not isinstance(external, dict):
        external = {}
    candidates = {
        "doi": raw.get("doi") or external.get("DOI"),
        "arxiv": (raw.get("arxiv_id") or raw.get("arxivId") or external.get("ArXiv")),
        "s2": raw.get("paperId") or raw.get("paper_id"),
    }
    aliases: list[str] = []
    for prefix, candidate in candidates.items():
        value = str(candidate or "").strip().lower()
        if prefix == "doi":
            value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
        elif prefix == "arxiv":
            value = re.sub(r"^arxiv:\s*", "", value)
            value = re.sub(r"v\d+$", "", value)
        elif prefix == "s2":
            value = re.sub(r"^s2:\s*", "", value)
        if value:
            aliases.append(f"{prefix}:{value}")
    return tuple(dict.fromkeys(aliases))


def _record_id(raw: dict[str, Any], provider: str) -> str:
    if provider == "semantic-scholar":
        value = raw.get("paperId") or raw.get("paper_id")
        if value:
            return "s2:" + str(value).strip().lower()
    if provider == "arxiv":
        value = raw.get("arxiv_id") or raw.get("arxivId") or raw.get("id")
        if not value:
            url = str(raw.get("url") or raw.get("entry_id") or "")
            match = re.search(r"/(?:abs|pdf)/([^/?#]+)", url)
            value = match.group(1) if match else ""
        if value:
            normalized = re.sub(r"v\d+$", "", str(value).strip().lower())
            return "arxiv:" + normalized
    if provider == "alphaxiv":
        # AlphaXiv is a distinct provider record even when it describes an
        # arXiv paper.  The arXiv identifier is retained as an alias, not used
        # as the primary key, so merging never erases source lineage.
        value = (
            raw.get("alphaxiv_id")
            or raw.get("provider_record_id")
            or raw.get("paperId")
            or raw.get("id")
        )
        if value:
            component = str(value).strip().lower()
            if re.fullmatch(r"[a-z0-9][a-z0-9._:/@+-]{0,240}", component):
                return "alphaxiv:" + component
    identity = str(raw.get("url") or raw.get("source_url") or "").strip()
    if not identity:
        identity = json.dumps(
            {
                "title": " ".join(str(raw.get("title") or "").casefold().split()),
                "year": raw.get("year") or raw.get("published"),
                "provider": provider,
            },
            sort_keys=True,
        )
    return f"{provider}:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def normalize_record(
    raw: dict[str, Any],
    *,
    provider: str,
    query: str,
    retrieved_at: datetime | None,
) -> RetrievalRecordV1:
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("retrieval record has no title")
    year_raw = raw.get("year")
    if year_raw is None:
        published = str(raw.get("published") or "")
        year_raw = published[:4] if len(published) >= 4 else None
    try:
        year = int(year_raw) if year_raw not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    citation_raw = raw.get("citationCount", raw.get("citation_count"))
    try:
        citation_count = int(citation_raw) if citation_raw is not None else None
    except (TypeError, ValueError):
        citation_count = None
    provider_id = (
        raw.get("paperId")
        or raw.get("paper_id")
        or raw.get("arxiv_id")
        or raw.get("arxivId")
        or raw.get("alphaxiv_id")
        or raw.get("provider_record_id")
        or raw.get("id")
    )
    source_url = (
        str(
            raw.get("url") or raw.get("entry_id") or raw.get("source_url") or ""
        ).strip()
        or None
    )
    return RetrievalRecordV1(
        canonical_id=_record_id(raw, provider),
        provider=provider,
        provider_record_id=str(provider_id).strip() if provider_id else None,
        provider_version=PROVIDER_VERSIONS.get(provider),
        query=str(raw.get("retrieval_query") or query),
        retrieved_at=retrieved_at,
        title=title,
        abstract=str(
            raw.get("abstract") or raw.get("snippet") or raw.get("text") or ""
        )[:100_000],
        authors=_authors(raw.get("authors")),
        year=year,
        citation_count=citation_count,
        source_url=source_url,
        payload_digest=canonical_digest(raw),
        aliases=tuple(
            alias
            for alias in _external_aliases(raw)
            if alias != _record_id(raw, provider)
        ),
        license=str(raw.get("license") or "").strip() or None,
        use_restriction=(str(raw.get("use_restriction") or "").strip() or None),
    )


def normalize_records(
    rows: Iterable[dict[str, Any]],
    *,
    provider: str,
    query: str,
    retrieved_at: datetime | None,
) -> tuple[RetrievalRecordV1, ...]:
    records: dict[str, RetrievalRecordV1] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("title") or "").strip():
            continue
        record = normalize_record(
            row, provider=provider, query=query, retrieved_at=retrieved_at
        )
        previous = records.get(record.canonical_id)
        if previous is None or record.payload_digest < previous.payload_digest:
            records[record.canonical_id] = record
    return tuple(records[key] for key in sorted(records))


def alias_groups(records: Iterable[RetrievalRecordV1]) -> list[list[str]]:
    """Return provider records linked through a shared DOI/arXiv/S2 alias."""

    records = tuple(records)
    groups: list[set[str]] = []
    for record in records:
        identities = {record.canonical_id, *record.aliases}
        overlapping = [group for group in groups if group & identities]
        if not overlapping:
            groups.append(set(identities))
            continue
        merged = set(identities)
        for group in overlapping:
            merged.update(group)
            groups.remove(group)
        groups.append(merged)
    canonical_ids = {record.canonical_id for record in records}
    result = [sorted(group & canonical_ids) for group in groups]
    return sorted((group for group in result if len(group) > 1), key=lambda x: x[0])


def _write_artifact(
    workspace: WorkspaceRefV1,
    name: str,
    payload: bytes,
    *,
    role: str,
    media_type: str = "application/json",
) -> ResearchArtifactRefV1:
    workspace.atomic_write_bytes(name, payload)
    return ResearchArtifactRefV1(
        logical_name=name,
        digest=bytes_digest(payload),
        media_type=media_type,
        role=role,
    )


def record_snapshot(
    *,
    rows: Iterable[dict[str, Any]],
    provider: str,
    query: str,
    operation: str,
    parameters: dict[str, Any],
    checkpoint_dir: str | Path | None,
    retrieved_at: datetime,
    mode: str = "record",
    citation_edges: Iterable[CitationEdgeV1] = (),
    warnings: Iterable[str] = (),
    response_metadata: dict[str, Any] | None = None,
    raw_payloads: Iterable[tuple[bytes, str, str]] = (),
) -> tuple[SurveySnapshotV1, str | None]:
    if mode not in {"record", "live"}:
        raise ValueError("snapshot mode must be record or live")
    if mode == "record" and not checkpoint_dir:
        raise ValueError("record mode requires ARI_CHECKPOINT_DIR")
    rows = list(rows)
    citation_edges = tuple(citation_edges)
    warnings = tuple(warnings)
    raw_payloads = tuple(raw_payloads)
    records = normalize_records(
        rows, provider=provider, query=query, retrieved_at=retrieved_at
    )
    artifacts: tuple[ResearchArtifactRefV1, ...] = ()
    reference: str | None = None
    workspace: WorkspaceRefV1 | None = None
    if mode == "record" and checkpoint_dir:
        root = Path(checkpoint_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = WorkspaceRefV1(root=str(root))
        cassette_payload = _json_bytes(
            {
                "schema_version": "ari.retrieval-cassette/v1",
                "provider": provider,
                "provider_version": PROVIDER_VERSIONS.get(provider),
                "operation": operation,
                "query": query,
                "parameters": parameters,
                "retrieved_at": retrieved_at.isoformat(),
                "response_metadata": response_metadata or {},
                "rows": rows,
                "citation_edges": [
                    edge.model_dump(mode="json") for edge in citation_edges
                ],
                "warnings": list(warnings),
            }
        )
        cassette_digest = bytes_digest(cassette_payload).removeprefix("sha256:")
        cassette_name = f"retrieval_cassettes/{cassette_digest}.json"
        artifact_list = [
            _write_artifact(
                workspace,
                cassette_name,
                cassette_payload,
                role="raw-provider-cassette",
            )
        ]
        for payload, media_type, role in raw_payloads:
            digest = bytes_digest(payload).removeprefix("sha256:")
            artifact_list.append(
                _write_artifact(
                    workspace,
                    f"retrieval_payloads/{digest}.bin",
                    payload,
                    role=role,
                    media_type=media_type,
                )
            )
        artifacts = tuple(artifact_list)
    snapshot = SurveySnapshotV1.create(
        mode=mode,
        provider=provider,
        provider_version=PROVIDER_VERSIONS.get(provider),
        query=query,
        retrieved_at=retrieved_at,
        byte_reproducible=False,
        records=records,
        citation_edges=citation_edges,
        artifacts=artifacts,
        warnings=warnings,
    )
    if workspace is not None:
        reference = (
            "retrieval_snapshots/"
            f"{snapshot.snapshot_digest.removeprefix('sha256:')}.json"
        )
        workspace.atomic_write_bytes(
            reference, _json_bytes(snapshot.model_dump(mode="json"))
        )
    return snapshot, reference


def replay_snapshot(
    *,
    checkpoint_dir: str | Path | None,
    snapshot_ref: str,
    query: str | None = None,
    provider: str | None = None,
    operation: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> SurveySnapshotV1:
    if not checkpoint_dir:
        raise ValueError("replay requires ARI_CHECKPOINT_DIR")
    if not snapshot_ref:
        raise ValueError("replay requires snapshot_ref")
    workspace = WorkspaceRefV1(root=str(Path(checkpoint_dir).expanduser().resolve()))
    snapshot = load_survey_snapshot_ref(workspace.root, snapshot_ref)
    expected_ref = (
        f"retrieval_snapshots/{snapshot.snapshot_digest.removeprefix('sha256:')}.json"
    )
    if snapshot_ref != expected_ref:
        raise ValueError("snapshot_ref is not the content-addressed snapshot path")
    if query is not None and snapshot.query != query:
        raise ValueError("replay query does not match snapshot")
    if provider is not None and snapshot.provider != provider:
        raise ValueError("replay provider does not match snapshot")
    cassette_refs = [
        artifact
        for artifact in snapshot.artifacts
        if artifact.role == "raw-provider-cassette"
    ]
    if len(cassette_refs) != 1:
        raise ValueError("recorded retrieval snapshot must reference one cassette")
    cassette_payload = workspace.read_bytes(
        cassette_refs[0].logical_name, max_bytes=128 * 1024 * 1024
    )
    try:
        cassette = json.loads(cassette_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("retrieval cassette is not valid JSON") from exc
    if cassette.get("schema_version") != "ari.retrieval-cassette/v1":
        raise ValueError("unsupported retrieval cassette schema")
    expected_values = {
        "provider": provider,
        "query": query,
        "operation": operation,
        "parameters": parameters,
    }
    for field, expected in expected_values.items():
        if expected is not None and cassette.get(field) != expected:
            raise ValueError(f"replay {field} does not match cassette")
    rows = cassette.get("rows")
    if not isinstance(rows, list):
        raise ValueError("retrieval cassette rows must be a list")
    timestamp = cassette.get("retrieved_at")
    try:
        retrieved_at = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("retrieval cassette timestamp is invalid") from exc
    reconstructed = normalize_records(
        rows,
        provider=snapshot.provider,
        query=snapshot.query,
        retrieved_at=retrieved_at,
    )
    if reconstructed != snapshot.records:
        raise ValueError("retrieval cassette does not reproduce snapshot records")
    if tuple(cassette.get("warnings") or ()) != snapshot.warnings:
        raise ValueError("retrieval cassette warnings do not match snapshot")
    reconstructed_edges = tuple(
        CitationEdgeV1.model_validate(edge)
        for edge in (cassette.get("citation_edges") or ())
    )
    if reconstructed_edges != snapshot.citation_edges:
        raise ValueError("retrieval cassette edges do not match snapshot")
    return snapshot


def result_document(
    snapshot: SurveySnapshotV1,
    *,
    snapshot_ref: str | None,
    execution_mode: str,
) -> dict[str, Any]:
    records = [record.model_dump(mode="json") for record in snapshot.records]
    return {
        "schema_version": "ari.retrieval-result/v1",
        "provider": snapshot.provider,
        "query": snapshot.query,
        "count": len(records),
        "records": records,
        "alias_groups": alias_groups(snapshot.records),
        "survey_snapshot": snapshot.model_dump(mode="json"),
        "survey_snapshot_digest": snapshot.snapshot_digest,
        "snapshot_ref": snapshot_ref,
        "execution_mode": execution_mode,
    }
