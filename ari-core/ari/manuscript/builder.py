"""Deterministic projection from exploration snapshots to manuscript context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ari.manuscript.contracts import (
    EvidenceRecordV1,
    ExplorationSnapshotV1,
    ManuscriptContextV1,
    OmissionManifestV1,
    OmissionV1,
)
from ari.manuscript.profiles import ManuscriptRequirementProfileV1


def _read_json(checkpoint: Path, relative_path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads((checkpoint / relative_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, type(exc).__name__
    if not isinstance(value, dict):
        return None, "not_object"
    return value, None


def _records(document: dict[str, Any] | None, *keys: str) -> list[dict[str, Any]]:
    if not document:
        return []
    for key in keys:
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, tuple):
            return [item for item in value if isinstance(item, dict)]
    return []


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _lane(
    node,
    assurance_mode: str,
    provenance_statuses: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    status = node.status.lower()
    if status in {"failed", "abandoned", "cancelled", "error", "inconclusive", "null"}:
        return "contextual_negative", (f"execution_{status}",)
    if any(value == "mismatch" for value in provenance_statuses):
        return "excluded", ("artifact_digest_mismatch",)
    if any(value == "missing" for value in provenance_statuses):
        return "excluded", ("artifact_missing",)
    if any(value == "invalid" for value in provenance_statuses):
        return "excluded", ("artifact_invalid",)
    if any(value == "unhashed" for value in provenance_statuses):
        return "exploratory", ("artifact_unhashed",)
    if not node.valid_for_frontier:
        return "excluded", ("stale_or_erased",)
    if not node.has_real_data or not node.metrics:
        return "contextual_negative", ("no_real_measurement",)
    if node.frontier_class == "debug_frontier":
        return "exploratory", ("debug_frontier",)
    if node.frontier_class == "uncertified_frontier":
        return "exploratory", ("uncertified_frontier",)
    if any(value in {"fail", "tampered"} for value in node.property_verdicts.values()):
        return "excluded", ("assurance_property_failed",)
    assurance_pass = node.assurance_status == "pass"
    if assurance_mode == "enforce" and not (
        assurance_pass
        and node.assurance_tier == "certify"
        and node.certify_attestation_item_ids
        and node.verified_target_digest
    ):
        reasons.append("certification_required")
        return "exploratory", tuple(reasons)
    if assurance_mode == "audit" and node.assurance_status and not assurance_pass:
        return "exploratory", (f"assurance_{node.assurance_status}",)
    return "publishable", ("typed_measurement",)


def _best_publication_candidate(snapshot: ExplorationSnapshotV1, records: list[EvidenceRecordV1]):
    by_node = {record.node_id: record for record in records if record.node_id}
    winner = snapshot.scientific_winner_id
    if winner and winner in by_node and by_node[winner].publishable:
        return winner, "scientific_winner_is_publishable"
    eligible = [
        node for node in snapshot.nodes
        if node.node_id in by_node and by_node[node.node_id].publishable
    ]
    eligible.sort(
        key=lambda node: (
            node.scientific_score is not None,
            node.scientific_score if node.scientific_score is not None else float("-inf"),
            node.node_id,
        ),
        reverse=True,
    )
    if eligible:
        # The default policy records a possible alternative but does not silently
        # replace the scientific winner.  Readiness/certification can request an
        # explicit policy decision before publication.
        return None, f"certified_alternative_available:{eligible[0].node_id}"
    return None, "no_publishable_candidate"


def _extract_references(document: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    records = _records(document, "records", "papers", "results")
    out: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        out.append({
            "reference_id": str(
                record.get("record_id")
                or record.get("paper_id")
                or record.get("id")
                or record.get("citation_key")
                or f"reference-{index:04d}"
            ),
            "title": str(record.get("title") or ""),
            "url": str(record.get("url") or record.get("source_url") or ""),
            "year": record.get("year"),
            "authors": record.get("authors") or [],
            "citation_key": str(
                record.get("citation_key") or record.get("bibtex_key") or ""
            ),
            "abstract": str(record.get("abstract") or record.get("summary") or ""),
            "source_digest": record.get("record_digest") or record.get("digest") or "",
        })
    return tuple(out)


def _extract_limitations(
    verified: dict[str, Any] | None,
    disclosures: dict[str, Any] | None,
    negative_results: tuple[dict[str, Any], ...],
    assurance_mode: str,
    publication_candidate: str | None,
) -> tuple[str, ...]:
    values: list[str] = []
    for item in (verified or {}).get("limitations") or []:
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            values.append(str(item["text"]).strip())
    for item in _records(disclosures, "records"):
        limitation = str(item.get("limitation") or "").strip()
        if limitation:
            values.append(limitation)
    if negative_results:
        values.append(
            f"Exploration contained {len(negative_results)} failed, null, or inconclusive candidate(s)."
        )
    if assurance_mode == "enforce" and publication_candidate is None:
        values.append("The scientific winner does not yet have publication-admissible certification.")
    return tuple(dict.fromkeys(values))


def _declared_claim_characteristics(
    *documents: dict[str, Any] | None,
) -> dict[str, bool]:
    """Read only explicit typed applicability declarations.

    Free-form draft/reviewer prose is deliberately excluded. Research
    contracts and typed claim records may declare the fixed applicability
    booleans directly or through a bounded claim type vocabulary.
    """

    out: dict[str, bool] = {}
    type_map = {
        "comparative": "comparative_claim",
        "superiority": "comparative_claim",
        "stochastic": "stochastic_claim",
        "aggregate": "stochastic_claim",
        "component-causal": "multi_component_claim",
        "multi-component": "multi_component_claim",
        "novelty": "novelty_claim",
        "result": "result_claim",
        "numeric-result": "numeric_result",
        "reproducibility": "reproducibility_claim",
    }
    allowed = set(type_map.values()) | {
        "hypothesis_testing",
        "empirical",
    }
    for document in documents:
        if not isinstance(document, dict):
            continue
        declared = document.get("claim_characteristics")
        if isinstance(declared, dict):
            for key, value in declared.items():
                if key in allowed and isinstance(value, bool):
                    out[key] = out.get(key, False) or value
        raw_types = document.get("claim_types")
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if isinstance(raw_types, (list, tuple)):
            for raw in raw_types:
                mapped = type_map.get(str(raw).strip().lower())
                if mapped:
                    out[mapped] = True
        raw_type = str(
            document.get("claim_type") or document.get("category") or ""
        ).strip().lower()
        mapped = type_map.get(raw_type)
        if mapped:
            out[mapped] = True
    return out


def build_manuscript_context(
    checkpoint_dir: str | Path,
    snapshot: ExplorationSnapshotV1,
    profile: ManuscriptRequirementProfileV1,
    *,
    assurance_mode: str = "off",
) -> tuple[ManuscriptContextV1, OmissionManifestV1]:
    checkpoint = Path(checkpoint_dir).resolve()
    parsed: dict[str, dict[str, Any] | None] = {}
    parse_errors: dict[str, str] = {}
    for artifact in snapshot.artifacts:
        if artifact.source_node_id is not None or artifact.relative_path is None:
            continue
        if artifact.status != "present" or not artifact.relative_path.endswith(".json"):
            continue
        value, error = _read_json(checkpoint, artifact.relative_path)
        parsed[artifact.kind] = value
        if error:
            parse_errors[artifact.item_id] = error

    evidence: list[EvidenceRecordV1] = []
    history: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    provenance_by_node: dict[str, tuple[str, ...]] = {}
    for item in _records(parsed.get("provenance-audit"), "results"):
        node_id = str(item.get("node_id") or "")
        status = str(item.get("status") or "")
        if node_id and status:
            provenance_by_node[node_id] = tuple(
                dict.fromkeys((*provenance_by_node.get(node_id, ()), status))
            )
    artifact_by_id = {item.item_id: item for item in snapshot.artifacts}
    for node in snapshot.nodes:
        local_statuses = tuple(
            artifact_by_id[item_id].status
            for item_id in node.artifact_item_ids
            if item_id in artifact_by_id
        )
        lane, reasons = _lane(
            node,
            assurance_mode,
            tuple(dict.fromkeys((*provenance_by_node.get(node.node_id, ()), *local_statuses))),
        )
        valid_artifact_ids = tuple(
            item_id
            for item_id in node.artifact_item_ids
            if item_id in artifact_by_id and artifact_by_id[item_id].status == "present"
        )
        record = EvidenceRecordV1(
            evidence_id=f"node-evidence:{node.node_id}",
            kind="node-measurement",
            lane=lane,
            node_id=node.node_id,
            claim_eligible_fact=(lane in {"publishable", "exploratory"}),
            publishable=(lane == "publishable"),
            metric_values=node.metrics,
            artifact_item_ids=valid_artifact_ids,
            reason_codes=reasons,
        )
        evidence.append(record)
        event = {
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "ancestor_ids": list(node.ancestor_ids),
            "status": node.status,
            "label": node.label,
            "name": node.name,
            "direction": node.original_direction or "",
            "lane": lane,
            "reason_codes": list(reasons),
            "repair_request_id": node.repair_request_id,
            "repair_requirement_ids": list(node.repair_requirement_ids),
            "repair_context_digest": node.repair_context_digest,
        }
        history.append(event)
        if lane == "contextual_negative":
            negative.append({
                **event,
                "metrics": node.metrics,
                "error_summary": node.error_summary,
            })

    publication_candidate, selection_reason = _best_publication_candidate(snapshot, evidence)
    scientific_winner = snapshot.scientific_winner_id
    certified_alternatives = [
        record.node_id for record in evidence
        if record.publishable and record.node_id != scientific_winner
    ]
    subjects = {
        "scientific_winner": scientific_winner,
        "publication_candidate": publication_candidate,
        "selection_reason": selection_reason,
        "certified_alternatives": certified_alternatives,
        "node_count": len(snapshot.nodes),
        "negative_node_ids": [item["node_id"] for item in negative],
        "excluded_node_ids": [
            record.node_id for record in evidence if record.lane == "excluded"
        ],
    }

    idea = parsed.get("research-contract") or {}
    contract = idea.get("research_contract") if isinstance(idea.get("research_contract"), dict) else {}
    ideas = idea.get("ideas") if isinstance(idea.get("ideas"), list) else []
    first_idea = ideas[0] if ideas and isinstance(ideas[0], dict) else {}
    question = snapshot.research_question
    hypothesis = str(
        contract.get("hypothesis")
        or first_idea.get("hypothesis")
        or idea.get("hypothesis")
        or ""
    )
    falsification = _strings(
        contract.get("falsification_conditions")
        or first_idea.get("falsification_conditions")
        or idea.get("falsification_conditions")
    )
    research_question = {
        "question": question,
        "objective": str(contract.get("objective") or question),
        "hypothesis": hypothesis,
        "falsification_conditions": list(falsification),
        "research_contract_digest": snapshot.research_contract_digest,
    }
    contribution_map: list[dict[str, Any]] = []
    contributions = (
        contract.get("contributions")
        or first_idea.get("contributions")
        or idea.get("contributions")
        or []
    )
    for index, item in enumerate(contributions if isinstance(contributions, list) else [contributions]):
        if isinstance(item, dict):
            contribution_map.append({"contribution_id": f"contribution-{index:03d}", **item})
        elif str(item).strip():
            contribution_map.append({
                "contribution_id": f"contribution-{index:03d}",
                "description": str(item).strip(),
            })

    methods: list[dict[str, Any]] = []
    plan = first_idea.get("experiment_plan") or idea.get("experiment_plan") or contract.get("method")
    if isinstance(plan, str) and plan.strip():
        methods.append({"method_id": "research-plan", "description": plan.strip()})
    elif isinstance(plan, dict):
        methods.append({"method_id": "research-plan", "specification": plan})
    for node in snapshot.nodes:
        if node.original_direction:
            methods.append({
                "method_id": f"node-method:{node.node_id}",
                "node_id": node.node_id,
                "description": node.original_direction,
            })

    science = parsed.get("science-data") or {}
    raw = science.get("raw") if isinstance(science.get("raw"), dict) else {}
    configurations = _records(raw, "configurations") or _records(science, "configurations")
    measurement_records = _records(raw, "measurement_records", "measurements")
    claims = _records(raw, "claims") or _records(science, "claims")
    metric_evidence = [record for record in evidence if record.metric_values]
    related_work = _extract_references(parsed.get("retrieval-records"))
    declared = _declared_claim_characteristics(
        idea,
        contract,
        first_idea,
        *claims,
    )
    empirical = bool(metric_evidence or measurement_records or configurations)
    comparator_exists = len(metric_evidence) >= 2 or any(
        str(item.get("role") or item.get("kind") or "").lower()
        in {"baseline", "comparator", "control"}
        for item in configurations
    )
    comparative = bool(declared.get("comparative_claim") or comparator_exists)
    has_ablation = any(node.label == "ablation" for node in snapshot.nodes)
    uncertainty_evidence = bool(
        len(measurement_records) > max(1, len(configurations))
        or any(
            any(
                token in str(key).lower()
                for token in ("std", "variance", "confidence", "stderr", "error_bar")
            )
            for record in [*metric_evidence, *measurement_records]
            for key in (
                record.metric_values.keys()
                if isinstance(record, EvidenceRecordV1)
                else record.keys()
            )
        )
    )
    stochastic = bool(declared.get("stochastic_claim") or uncertainty_evidence)
    claim_characteristics = {
        "empirical": bool(declared.get("empirical") or empirical),
        "hypothesis_testing": bool(
            declared.get("hypothesis_testing") or hypothesis or falsification
        ),
        "result_claim": bool(
            declared.get("result_claim") or metric_evidence or claims
        ),
        "numeric_result": bool(
            declared.get("numeric_result") or metric_evidence or measurement_records
        ),
        "stochastic_claim": stochastic,
        "comparative_claim": comparative,
        "comparator_exists": comparator_exists,
        "multi_component_claim": bool(
            declared.get("multi_component_claim")
            or has_ablation
            or len(contribution_map) > 1
        ),
        "multiple_candidates": len(snapshot.nodes) > 1,
        "novelty_claim": bool(declared.get("novelty_claim") or question),
        "reproducibility_claim": bool(
            declared.get("reproducibility_claim") or empirical
        ),
        "assurance_enforce": assurance_mode == "enforce",
        "manuscript_enabled": True,
    }

    ear_artifact = next((a for a in snapshot.artifacts if a.kind == "ear-manifest"), None)
    code_lock = next((a for a in snapshot.artifacts if a.kind == "code-bundle-lock"), None)
    interpretation = science.get("interpretation") if isinstance(science, dict) else {}
    experiment_context = (
        interpretation.get("experiment_context")
        if isinstance(interpretation, dict)
        and interpretation.get("status") == "ok"
        and isinstance(interpretation.get("experiment_context"), dict)
        else {}
    )
    ear_document = parsed.get("ear-manifest") or {}
    environment = experiment_context.get("hardware") or ear_document.get("environment") or {}
    if not environment and ear_document.get("has_environment"):
        environment = {"captured_in_ear": True}
    commands = ear_document.get("commands") or []
    if not commands and ear_document.get("has_reproduce_sh"):
        commands = ["ear/reproduce.sh"]
    reproducibility = {
        "ear_manifest": ear_artifact.relative_path if ear_artifact and ear_artifact.status == "present" else None,
        "ear_digest": ear_artifact.digest if ear_artifact else None,
        "code_bundle_lock": code_lock.relative_path if code_lock and code_lock.status == "present" else None,
        "code_bundle_digest": code_lock.digest if code_lock else None,
        "configuration_count": len(configurations),
        "measurement_count": len(measurement_records) or len(metric_evidence),
        "claim_count": len(claims),
        "uncertainty_evidence": uncertainty_evidence,
        "commands": commands,
        "environment": environment,
    }
    attestation_items = [
        artifact
        for artifact in snapshot.artifacts
        if artifact.kind == "harness-attestation"
    ]
    certify_item_ids = {
        item_id
        for node in snapshot.nodes
        for item_id in node.certify_attestation_item_ids
    }
    assurance = {
        "mode": assurance_mode,
        "publication_candidate": publication_candidate,
        "scientific_winner": scientific_winner,
        "certified_node_ids": [record.node_id for record in evidence if record.publishable],
        "attestation_item_ids": [
            item.item_id
            for item in attestation_items
            if item.status == "present" and item.item_id in certify_item_ids
        ],
        "missing_attestation_item_ids": [item.item_id for item in attestation_items if item.status != "present"],
        "selection_reason": selection_reason,
    }

    inventory_ids = [f"node:{node.node_id}" for node in snapshot.nodes] + [
        artifact.item_id for artifact in snapshot.artifacts
    ]
    included_ids = [f"node:{node.node_id}" for node in snapshot.nodes]
    omissions: list[OmissionV1] = []
    for artifact in snapshot.artifacts:
        reason = None
        detail = ""
        if artifact.item_id in parse_errors:
            reason = "parse_failure"
            detail = parse_errors[artifact.item_id]
        elif artifact.status == "missing":
            reason = "missing_on_disk"
        elif artifact.status == "mismatch":
            reason = "digest_mismatch"
        elif artifact.status == "stale":
            reason = "stale"
        elif artifact.status == "invalid":
            reason = (
                "unsafe_path"
                if artifact.relative_path is None or artifact.metadata.get("unsafe_path")
                else "parse_failure"
            )
        elif artifact.status == "unhashed":
            reason = "policy_excluded"
        if reason:
            omissions.append(
                OmissionV1(
                    item_id=artifact.item_id,
                    reason=reason,
                    projection="manuscript-context",
                    detail=detail,
                    creates_readiness_failure=artifact.kind in {
                        "science-data", "retrieval-records", "ear-manifest", "figure-batch"
                    },
                )
            )
        else:
            included_ids.append(artifact.item_id)
    omission_manifest = OmissionManifestV1.create(
        source_snapshot_digest=snapshot.snapshot_digest,
        projection="manuscript-context",
        inventory_item_ids=tuple(inventory_ids),
        included_item_ids=tuple(included_ids),
        omissions=tuple(omissions),
    )

    verified = parsed.get("verified-context")
    limitations = _extract_limitations(
        verified,
        parsed.get("manuscript-disclosures"),
        tuple(negative),
        assurance_mode,
        publication_candidate,
    )
    recorded_threats = [
        str(item.get("threat_to_validity") or "").strip()
        for item in _records(parsed.get("manuscript-disclosures"), "records")
        if str(item.get("threat_to_validity") or "").strip()
    ]
    threats = tuple(
        dict.fromkeys(
            [
                *recorded_threats,
                "Selection among explored candidates may overestimate generalization."
                if len(snapshot.nodes) > 1 else "",
                "Missing or unhashed source artifacts limit independent provenance verification."
                if any(item.status in {"missing", "unhashed", "invalid"} for item in snapshot.artifacts)
                else "",
            ]
        )
    )
    threats = tuple(item for item in threats if item)
    context = ManuscriptContextV1.create(
        run_id=snapshot.run_id,
        profile_digest=profile.profile_digest,
        source_snapshot_digest=snapshot.snapshot_digest,
        omission_manifest_digest=omission_manifest.manifest_digest,
        research_question=research_question,
        claim_characteristics=claim_characteristics,
        contribution_map=tuple(contribution_map),
        methods=tuple(methods),
        subjects=subjects,
        evidence_records=tuple(evidence),
        exploration_history=tuple(history),
        negative_results=tuple(negative),
        related_work=related_work,
        limitations=limitations,
        threats_to_validity=threats,
        reproducibility=reproducibility,
        assurance=assurance,
        annotations=(),
    )
    return context, omission_manifest


__all__ = ["build_manuscript_context"]
