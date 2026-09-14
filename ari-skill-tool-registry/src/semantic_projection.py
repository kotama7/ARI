"""Reviewed Provider-result projections for versioned ARI Capabilities.

Descriptions and name similarity never select these transforms.  A transform
is active only when the immutable descriptor carries its exact, reviewed ID.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ari.public.research_contract import RetrievalRecordV1

from models import CanonicalToolDescriptorV1, sha256_digest
from providers import ProviderResponseV1


PUBMED_RETRIEVAL_NORMALIZER_V1 = "tooluniverse-pubmed-retrieval/v1"


class SemanticProjectionError(ValueError):
    """A live Provider response does not match its reviewed semantic adapter."""


class ProjectedLiteratureResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ari.retrieval-result/v1"] = "ari.retrieval-result/v1"
    provider: Literal["pubmed-via-tooluniverse"] = "pubmed-via-tooluniverse"
    query: str = Field(min_length=1, max_length=4096)
    count: int = Field(ge=0)
    records: tuple[RetrievalRecordV1, ...]
    collection_provenance: dict[str, Any]


def projection_output_schema(normalizer_id: str) -> dict[str, Any]:
    if normalizer_id != PUBMED_RETRIEVAL_NORMALIZER_V1:
        raise ValueError(f"unknown reviewed result normalizer: {normalizer_id}")
    return ProjectedLiteratureResultV1.model_json_schema()


def _pubmed_record(
    row: dict[str, Any], *, query: str, provider_version: str
) -> RetrievalRecordV1:
    pmid = str(row.get("pmid") or "").strip()
    title = str(row.get("title") or "").strip()
    if not pmid or not title:
        raise SemanticProjectionError("PubMed result omitted PMID or title")
    try:
        year = int(str(row.get("pub_year") or ""))
    except ValueError:
        year = None
    doi = str(row.get("doi") or "").strip().lower()
    aliases = (f"doi:{doi}",) if doi else ()
    authors = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (row.get("authors") or ())
            if str(item).strip()
        )
    )
    return RetrievalRecordV1(
        canonical_id=f"pubmed:{pmid.casefold()}",
        provider="pubmed",
        provider_record_id=pmid,
        provider_version=provider_version,
        query=query,
        retrieved_at=None,
        title=title,
        abstract=str(row.get("abstract") or "")[:100_000],
        authors=authors,
        year=year,
        source_url=str(row.get("url") or "").strip() or None,
        payload_digest=sha256_digest(row),
        aliases=aliases,
    )


def _normalize_pubmed(
    *,
    descriptor: CanonicalToolDescriptorV1,
    arguments: dict[str, Any],
    response: ProviderResponseV1,
) -> ProviderResponseV1:
    structured = response.structured
    if response.is_error or not isinstance(structured, dict):
        return response
    if structured.get("status") != "success" or not isinstance(
        structured.get("data"), list
    ):
        raise SemanticProjectionError(
            "ToolUniverse PubMed response is outside the reviewed success envelope"
        )
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise SemanticProjectionError("ToolUniverse PubMed invocation omitted query")
    rows = structured["data"]
    if not all(isinstance(item, dict) for item in rows):
        raise SemanticProjectionError("ToolUniverse PubMed data contains a non-object")
    provenance = structured.get("_ari_collection_provenance")
    if not isinstance(provenance, dict):
        raise SemanticProjectionError(
            "ToolUniverse PubMed result omitted collection provenance"
        )
    document = ProjectedLiteratureResultV1(
        query=query,
        count=len(rows),
        records=tuple(
            _pubmed_record(
                item,
                query=query,
                provider_version=f"tooluniverse-{descriptor.provider_version}",
            )
            for item in rows
        ),
        collection_provenance=provenance,
    )
    payload = document.model_dump(mode="json")
    return ProviderResponseV1(
        text=document.model_dump_json(),
        structured=payload,
        is_error=False,
    )


def normalize_provider_response(
    *,
    descriptor: CanonicalToolDescriptorV1,
    arguments: dict[str, Any],
    response: ProviderResponseV1,
) -> ProviderResponseV1:
    normalizer_id = descriptor.semantics.get("result_normalizer")
    if normalizer_id is None:
        return response
    if normalizer_id == PUBMED_RETRIEVAL_NORMALIZER_V1:
        return _normalize_pubmed(
            descriptor=descriptor,
            arguments=arguments,
            response=response,
        )
    raise SemanticProjectionError(
        f"descriptor names an unknown result normalizer: {normalizer_id}"
    )


__all__ = [
    "PUBMED_RETRIEVAL_NORMALIZER_V1",
    "ProjectedLiteratureResultV1",
    "SemanticProjectionError",
    "normalize_provider_response",
    "projection_output_schema",
]
