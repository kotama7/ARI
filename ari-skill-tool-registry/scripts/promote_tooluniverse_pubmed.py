#!/usr/bin/env python3
"""Build the evidence-bound verified lock for the exact PubMed Provider leaf."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
SRC = PACKAGE_ROOT / "src"
CORE = REPO_ROOT / "ari-core"
for path in (str(SRC), str(CORE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from ari.capability_binding.ontology import load_capability_ontology  # noqa: E402
from ari.providers.models import ProviderRegistrationGateV1  # noqa: E402
from ari.providers.registration import registration_report  # noqa: E402
from models import AdmissionEvidenceV1, sha256_digest  # noqa: E402
from providers import (  # noqa: E402
    ProviderProtocolError,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    provider_digest,
)
from semantic_projection import (  # noqa: E402
    ProjectedLiteratureResultV1,
    normalize_provider_response,
    projection_output_schema,
)
from sources import (  # noqa: E402
    ToolUniverseCatalogSource,
    ToolUniverseCategoryProfileV1,
    ToolUniversePinV1,
    ToolUniverseSourceSpecV1,
)
from tooluniverse_adapter import (  # noqa: E402
    TOOLUNIVERSE_ADAPTER_ID,
    TOOLUNIVERSE_ADAPTER_VERSION,
    TOOLUNIVERSE_COMPACT_TOOLS,
    TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES,
    ToolUniverseCompactAdapter,
    tooluniverse_adapter_digest,
    verify_tooluniverse_dependency_lock,
    verify_tooluniverse_environment,
    verify_tooluniverse_package,
    verify_tooluniverse_pin,
    verify_tooluniverse_verified_lock,
    verify_tooluniverse_wheel,
)


PROVIDER_ID = "tooluniverse-pubmed"
PROVIDER_VERSION = "1.3.1+ari.1"
TOOL_NAME = "PubMed_search_articles"
CAPABILITY_REF = "ari.literature.search/v1"
NORMALIZER_ID = "tooluniverse-pubmed-retrieval/v1"
REGISTRATION_TESTS = (
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::"
    "test_stdio_adapter_initializes_paginates_and_calls_normal_error_large",
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::"
    "test_stdio_adapter_passes_only_named_credentials_and_redacts_response",
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::"
    "test_stdio_timeout_reaps_the_provider_process_group",
    "ari-skill-tool-registry/tests/test_stdio_adapter.py::"
    "test_provider_and_architecture_drift_fail_before_execution",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_ari_patched_release_closes_dependency_graph_and_build_identity",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_exact_include_filter_cannot_expand_verified_leaf_scope",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_exact_reviewed_capability_projection_never_uses_description_or_substring",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_reviewed_capability_projection_fails_closed_on_missing_leaf",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_locked_runtime_is_strict_records_provenance_and_replays_offline",
    "ari-skill-tool-registry/tests/test_tooluniverse_adapter.py::"
    "test_schema_update_requires_separate_explicit_approval",
)


def _load_pin() -> dict[str, Any]:
    support = json.loads(
        (PACKAGE_ROOT / "providers" / "tooluniverse-support-v1.json").read_text(
            encoding="utf-8"
        )
    )
    matches = [
        item for item in support["releases"] if item["version"] == PROVIDER_VERSION
    ]
    if len(matches) != 1:
        raise ValueError("the patched ToolUniverse support pin is missing or ambiguous")
    ToolUniversePinV1.model_validate(matches[0]).verify()
    return matches[0]


def _artifact(pin: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": pin["artifact_kind"],
        "build_recipe_digest": pin["build_recipe_digest"],
        "dependency_lock_digest": pin["dependency_lock_digest"],
        "package_tree_digest": pin["package_tree_digest"],
        "patch_digest": pin["patch_digest"],
        "upstream_version": pin["upstream_version"],
        "upstream_wheel_digest": pin["upstream_wheel_digest"],
        "wheel_digest": pin["wheel_digest"],
    }


def _load_manifest(pin: dict[str, Any]) -> dict[str, Any]:
    path = PACKAGE_ROOT / "providers" / pin["provider_manifest_path"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if sha256_digest(manifest) != pin["provider_manifest_digest"]:
        raise ValueError("Provider manifest digest drift")
    return manifest


def _scope(manifest: dict[str, Any]) -> dict[str, Any]:
    capability = manifest["capabilities"][0]
    return {
        "categories": [capability["category"]],
        "tool_names": [capability["tool_name"]],
        "capability_ref": capability["capability_ref"],
        "capability_contract_digest": capability["capability_contract_digest"],
        "leaf_spec_digest": capability["leaf_spec_digest"],
        "input_schema_digest": capability["input_schema_digest"],
        "output_schema_digest": capability["output_schema_digest"],
        "projected_output_schema_digest": capability[
            "projected_output_schema_digest"
        ],
        "result_normalizer": capability["result_normalizer"],
        "side_effects": capability["side_effects"],
        "determinism": capability["determinism"],
        "context_requirement": capability["context_requirement"],
        "permissions": capability["permissions"],
        "credential_scope_ids": capability["credential_scope_ids"],
        "environment_requirements": ["network-read"],
        "resource_type": "network",
    }


def _launcher(args: argparse.Namespace) -> tuple[PythonStdioLauncherV1, PythonStdioLauncherV1]:
    base = PythonStdioLauncherV1(
        # Preserve the venv launcher; resolving its symlink bypasses pyvenv.cfg.
        python_executable=os.path.abspath(args.provider_python),
        package_root=str(Path(args.package_root).resolve()),
        python_module="tooluniverse.smcp_server",
        python_callable="run_stdio_server",
        expected_architecture="x86_64",
        identity_globs=[
            "**/*",
            "**/*.py",
            "*.lock",
            "pyproject.toml",
            "requirements*.txt",
        ],
    )
    effective = base.model_copy(
        update={
            "arguments": [
                "--compact-mode",
                "--no-search",
                "--max-workers",
                "1",
                "--categories",
                "pubmed",
            ]
        }
    )
    return base, effective


def _test_evidence(test_python: str) -> dict[str, Any]:
    command = [test_python, "-m", "pytest", *REGISTRATION_TESTS, "-q"]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=300,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            "Provider registration tests failed:\n"
            + output.decode("utf-8", errors="replace")[-8_000:]
        )
    return {
        "command": ["<test-python>", "-m", "pytest", *REGISTRATION_TESTS, "-q"],
        "exit_code": completed.returncode,
        "output_sha256": "sha256:" + hashlib.sha256(output).hexdigest(),
        "test_ids": list(REGISTRATION_TESTS),
    }


async def _live_observations(
    *,
    base: PythonStdioLauncherV1,
    effective: PythonStdioLauncherV1,
    pin: dict[str, Any],
    scope: dict[str, Any],
    dependency_lock: Path,
    wheel: Path,
) -> dict[str, Any]:
    verify_tooluniverse_pin(pin)
    verify_tooluniverse_dependency_lock(dependency_lock, pin)
    verify_tooluniverse_wheel(wheel, pin)
    verify_tooluniverse_package(base, pin)
    environment = verify_tooluniverse_environment(base, pin)
    effective_digest = provider_digest(effective)

    raw_adapter = StdioMCPAdapter(
        effective,
        expected_provider_digest=effective_digest,
        timeout_seconds=180,
    )
    raw_tools = await raw_adapter.list_tools()
    raw_names = [item.name for item in raw_tools]
    if set(raw_names) != set(TOOLUNIVERSE_COMPACT_TOOLS) or len(raw_names) != 4:
        raise ProviderProtocolError("ToolUniverse compact MCP tools/list drifted")
    raw_schema_snapshot = [
        {
            "name": item.name,
            "input_schema": item.input_schema,
            "output_schema": item.output_schema,
        }
        for item in raw_tools
    ]

    discovery = ToolUniverseCompactAdapter(
        effective,
        expected_provider_digest=effective_digest,
        pin=pin,
        include_categories=["pubmed"],
        include_leaf_names=[TOOL_NAME],
        timeout_seconds=180,
        verify_package=True,
    )
    leaves = await discovery.list_tools()
    if len(leaves) != 1 or leaves[0].name != TOOL_NAME:
        raise ProviderProtocolError("exact PubMed leaf filtering drifted")
    leaf = leaves[0]
    metadata = leaf.annotations["ari_tooluniverse"]
    observed_scope = {
        "leaf_spec_digest": metadata["tool_spec_digest"],
        "input_schema_digest": sha256_digest(leaf.input_schema),
        "output_schema_digest": sha256_digest(leaf.output_schema),
        "projected_output_schema_digest": sha256_digest(
            projection_output_schema(NORMALIZER_ID)
        ),
    }
    for field, value in observed_scope.items():
        if scope[field] != value:
            raise ProviderProtocolError(f"reviewed PubMed {field} drifted")
    if metadata.get("optional_api_keys") != ["NCBI_API_KEY"]:
        raise ProviderProtocolError("PubMed credential metadata drifted")

    profile = ToolUniverseCategoryProfileV1(
        profile_id="pubmed-literature-search-v1",
        categories=["pubmed"],
        tool_types=["PubMedRESTTool"],
        side_effects="read-only",
        determinism="live-data",
        permissions=["network-read"],
        semantics={"result_contract": "ari.retrieval-result/v1"},
        limitations=["PubMed is a mutable live external index."],
        backend_lineage=["pubmed"],
        data_lineage=["pubmed-live-api"],
        independence_group="pubmed",
        capability_projections={TOOL_NAME: CAPABILITY_REF},
        equivalence_keys={TOOL_NAME: "literature-search-v1"},
        result_normalizers={TOOL_NAME: NORMALIZER_ID},
    )
    source_spec = ToolUniverseSourceSpecV1(
        source_id="tooluniverse.pubmed.verified",
        provider_id=PROVIDER_ID,
        provider_digest=effective_digest,
        launcher=base,
        dependency_lock_path=str(dependency_lock.resolve()),
        wheel_path=str(wheel.resolve()),
        support_release=PROVIDER_VERSION,
        profiles=[profile],
        include_categories=["pubmed"],
        include_tool_names=[TOOL_NAME],
        evidence=AdmissionEvidenceV1(
            protocol_conformance=True,
            provider_pinned=True,
            launcher_verified=True,
            dependencies_pinned=True,
            limitations_documented=True,
            semantics_documented=True,
            architecture="ToolUniverse compact MCP, exact PubMed leaf",
        ),
    )
    candidates = await ToolUniverseCatalogSource(
        source_spec,
        adapter=discovery,
        verify_source=False,
    ).sync()
    descriptor = candidates[0].descriptor
    runtime = ToolUniverseCompactAdapter(
        effective,
        expected_provider_digest=effective_digest,
        pin=pin,
        include_categories=["pubmed"],
        include_leaf_names=[TOOL_NAME],
        allowed_leaf_names=[TOOL_NAME],
        leaf_spec_digests={TOOL_NAME: scope["leaf_spec_digest"]},
        timeout_seconds=180,
        verify_package=True,
    )
    query = "20656909[PMID]"
    response = await runtime.invoke(TOOL_NAME, {"query": query, "limit": 1})
    normalized = normalize_provider_response(
        descriptor=descriptor,
        arguments={"query": query, "limit": 1},
        response=response,
    )
    projected = ProjectedLiteratureResultV1.model_validate(normalized.structured)
    if projected.count != 1:
        raise ProviderProtocolError("fixed PubMed live probe did not return one record")
    try:
        await runtime.invoke("PubMed_get_article", {"pmid": "20656909"})
    except ProviderProtocolError as exc:
        if "active catalog lock" not in str(exc):
            raise
    else:
        raise ProviderProtocolError("unbound ToolUniverse leaf invocation succeeded")

    return {
        "environment": environment,
        "provider_digest_in_validation_environment": effective_digest,
        "internal_mcp_tools": sorted(raw_names),
        "internal_mcp_schema_snapshot_digest": sha256_digest(raw_schema_snapshot),
        "internal_mcp_schema_digests": {
            item.name: {
                "input": sha256_digest(item.input_schema),
                "output": sha256_digest(item.output_schema),
            }
            for item in sorted(raw_tools, key=lambda value: value.name)
        },
        "leaf": {
            "name": leaf.name,
            "category": metadata["category"],
            "type": metadata["type"],
            "optional_api_keys": metadata["optional_api_keys"],
            **observed_scope,
        },
        "live_result": {
            "query": query,
            "upstream_status": response.structured["status"],
            "projected_schema_version": projected.schema_version,
            "record_count": projected.count,
            "credential_used": False,
        },
        "unbound_invocation_rejected": True,
    }


def _gate_evidence(
    *,
    pin: dict[str, Any],
    manifest: dict[str, Any],
    observations: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    test_ids = tests["test_ids"]

    def selected(*suffixes: str) -> list[str]:
        return [item for item in test_ids if any(item.endswith(value) for value in suffixes)]

    common_test = {"test_output_sha256": tests["output_sha256"]}
    return {
        "manifest_schema": {
            "provider_manifest_digest": pin["provider_manifest_digest"],
            "schema_version": manifest["schema_version"],
            "support_pin_model": "ToolUniversePinV1",
        },
        "source_package_digest_pin": {
            "repository_commit": pin["repository_commit"],
            "wheel_digest": pin["wheel_digest"],
            "package_tree_digest": pin["package_tree_digest"],
            "dependency_lock_digest": pin["dependency_lock_digest"],
            "patch_digest": pin["patch_digest"],
            "reproducible_build_count": 2,
            **common_test,
        },
        "live_tools_list_parity": {
            "internal_mcp_tools": observations["internal_mcp_tools"],
            "internal_snapshot_digest": observations[
                "internal_mcp_schema_snapshot_digest"
            ],
            "admitted_leaf_tools": [TOOL_NAME],
        },
        "schema_digest_pin": {
            **observations["leaf"],
            "internal_mcp_schema_digests": observations[
                "internal_mcp_schema_digests"
            ],
            "test_ids": selected(
                "test_reviewed_capability_projection_fails_closed_on_missing_leaf",
                "test_schema_update_requires_separate_explicit_approval",
            ),
            **common_test,
        },
        "capability_contract_conformance": {
            "capability_ref": CAPABILITY_REF,
            "capability_contract_digest": manifest["capabilities"][0][
                "capability_contract_digest"
            ],
            "result_normalizer": NORMALIZER_ID,
            "projected_output_schema_digest": observations["leaf"][
                "projected_output_schema_digest"
            ],
        },
        "side_effect_declaration": {
            "tool_type": observations["leaf"]["type"],
            "declared_side_effects": "read-only",
            "admitted_permission": "network-read",
        },
        "credential_scope": {
            "upstream_optional_api_keys": observations["leaf"]["optional_api_keys"],
            "admitted_credential_scope_ids": [],
            "anonymous_live_probe_passed": True,
            "test_ids": selected(
                "test_stdio_adapter_passes_only_named_credentials_and_redacts_response"
            ),
            **common_test,
        },
        "environment_allowlist": {
            "environment_identity_digest": observations["environment"][
                "environment_identity_digest"
            ],
            "pip_check_output_digest": observations["environment"]["output_digest"],
            "runtime_target": manifest["environment_policy"]["runtime_target"],
            "test_ids": selected(
                "test_stdio_adapter_initializes_paginates_and_calls_normal_error_large",
                "test_provider_and_architecture_drift_fail_before_execution",
            ),
            **common_test,
        },
        "timeout_cancellation_process_group": {
            "process_group_proxy_digest": sha256_digest(
                {
                    "source_sha256": "sha256:"
                    + hashlib.sha256(
                        (SRC / "stdio_process_proxy.py").read_bytes()
                    ).hexdigest()
                }
            ),
            "test_ids": selected(
                "test_stdio_timeout_reaps_the_provider_process_group"
            ),
            **common_test,
        },
        "result_schema": {
            **observations["live_result"],
            "projected_output_schema_digest": observations["leaf"][
                "projected_output_schema_digest"
            ],
        },
        "malicious_description_boundary": {
            "binding_source": "exact reviewed tool-name mapping",
            "test_ids": selected(
                "test_exact_reviewed_capability_projection_never_uses_description_or_substring"
            ),
            **common_test,
        },
        "workspace_isolation": {
            "provider_home": "isolated-temporary-directory",
            "parent_environment": "allowlisted",
            "test_ids": selected(
                "test_stdio_adapter_initializes_paginates_and_calls_normal_error_large"
            ),
            **common_test,
        },
        "revocation_behavior": {
            "rule": "any status other than verified is rejected before runtime",
            "post_generation_mutation_check": "revoked-status-rejected",
        },
        "schema_drift_detection": {
            "rules": [
                "missing exact leaf rejected",
                "changed schema requires separate explicit approval",
            ],
            "test_ids": selected(
                "test_reviewed_capability_projection_fails_closed_on_missing_leaf",
                "test_schema_update_requires_separate_explicit_approval",
            ),
            **common_test,
        },
        "unbound_invocation_rejection": {
            "live_adapter_check": observations["unbound_invocation_rejected"],
            "test_ids": selected(
                "test_exact_include_filter_cannot_expand_verified_leaf_scope",
                "test_locked_runtime_is_strict_records_provenance_and_replays_offline",
            ),
            **common_test,
        },
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_bundle(
    *,
    output_dir: Path,
    captured_date: str,
    pin: dict[str, Any],
    manifest: dict[str, Any],
    observations: dict[str, Any],
    tests: dict[str, Any],
    authorized_by: str,
) -> dict[str, str]:
    artifact = _artifact(pin)
    scope = _scope(manifest)
    gate_evidence = _gate_evidence(
        pin=pin,
        manifest=manifest,
        observations=observations,
        tests=tests,
    )
    if tuple(gate_evidence) != TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES:
        raise ValueError("promotion evidence gates are incomplete or out of order")
    evidence: dict[str, Any] = {
        "schema_version": "ari.tooluniverse-registration-evidence/v1",
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "captured_date": captured_date,
        "artifact": artifact,
        "capability_scope": scope,
        "observations": observations,
        "test_run": tests,
        "gate_evidence": gate_evidence,
    }
    evidence["bundle_digest"] = sha256_digest(evidence)

    gates = tuple(
        ProviderRegistrationGateV1(
            gate_id=gate_id,
            passed=True,
            evidence_digest=sha256_digest(gate_evidence[gate_id]),
            detail="closed registration evidence passed",
        )
        for gate_id in TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES
    )
    report = registration_report(
        provider_id=PROVIDER_ID,
        manifest_sha256=pin["provider_manifest_digest"],
        gates=gates,
    ).model_dump(mode="json")

    approval: dict[str, Any] = {
        "schema_version": "ari.capability-provider-promotion-approval/v1",
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "from_status": "candidate",
        "to_status": "verified",
        "actor_kind": "human-maintainer",
        "actor_id": authorized_by,
        "authorization_basis": "explicit-maintainer-approval",
        "approved_date": captured_date,
        "provider_manifest_digest": pin["provider_manifest_digest"],
        "registration_report_digest": report["report_digest"],
        "evidence_bundle_digest": evidence["bundle_digest"],
        "capability_scope_digest": sha256_digest(scope),
    }
    approval["approval_digest"] = sha256_digest(approval)

    lock: dict[str, Any] = {
        "schema_version": "ari.tooluniverse-verified-lock/v1",
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "status": "verified",
        "artifact": artifact,
        "adapter": {
            "adapter_id": TOOLUNIVERSE_ADAPTER_ID,
            "adapter_version": TOOLUNIVERSE_ADAPTER_VERSION,
            "adapter_digest": tooluniverse_adapter_digest(),
        },
        "runtime_target": {
            "architecture": "x86_64",
            "operating_system": "linux",
            "python_implementation": "CPython",
            "python_minor": "3.13",
        },
        "capability_scope": scope,
        "registration": {
            "provider_manifest_path": Path(pin["provider_manifest_path"]).name,
            "provider_manifest_digest": pin["provider_manifest_digest"],
            "evidence_path": "registration-evidence-v1.json",
            "evidence_bundle_digest": evidence["bundle_digest"],
            "report_path": "registration-report-v1.json",
            "report_digest": report["report_digest"],
        },
        "promotion": {
            "approval_path": "promotion-approval-v1.json",
            "approval_digest": approval["approval_digest"],
        },
    }
    lock["lock_digest"] = sha256_digest(lock)

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".promotion-", dir=output_dir) as staging_text:
        staging = Path(staging_text)
        evidence_path = staging / "registration-evidence-v1.json"
        report_path = staging / "registration-report-v1.json"
        approval_path = staging / "promotion-approval-v1.json"
        lock_path = staging / "verified-lock-v1.json"
        _write_json(evidence_path, evidence)
        _write_json(report_path, report)
        _write_json(approval_path, approval)
        _write_json(lock_path, lock)
        verify_tooluniverse_verified_lock(lock_path, pin)

        mutation = staging / "mutation"
        mutation.mkdir()
        shutil.copy2(evidence_path, mutation / evidence_path.name)
        shutil.copy2(report_path, mutation / report_path.name)
        shutil.copy2(approval_path, mutation / approval_path.name)
        revoked = dict(lock)
        revoked["status"] = "revoked"
        revoked["lock_digest"] = sha256_digest(
            {key: value for key, value in revoked.items() if key != "lock_digest"}
        )
        revoked_path = mutation / lock_path.name
        _write_json(revoked_path, revoked)
        try:
            verify_tooluniverse_verified_lock(revoked_path, pin)
        except ProviderProtocolError:
            pass
        else:
            raise RuntimeError("revoked Provider lock was accepted")

        for source in (evidence_path, report_path, approval_path, lock_path):
            source.replace(output_dir / source.name)
    return {
        "evidence_bundle_digest": evidence["bundle_digest"],
        "registration_report_digest": report["report_digest"],
        "promotion_approval_digest": approval["approval_digest"],
        "verified_lock_digest": lock["lock_digest"],
        "adapter_digest": lock["adapter"]["adapter_digest"],
    }


async def _run(args: argparse.Namespace) -> dict[str, str]:
    if platform.system().casefold() != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("this verified identity is limited to linux-x86_64")
    pin = _load_pin()
    manifest = _load_manifest(pin)
    ontology = load_capability_ontology(
        CORE / "config" / "capabilities" / "ontology.yaml"
    )
    contract = ontology.contract(CAPABILITY_REF)
    if contract is None or contract.contract_digest != manifest["capabilities"][0][
        "capability_contract_digest"
    ]:
        raise RuntimeError("Capability ontology differs from the Provider manifest")
    base, effective = _launcher(args)
    observations = await _live_observations(
        base=base,
        effective=effective,
        pin=pin,
        scope=_scope(manifest),
        dependency_lock=Path(args.dependency_lock),
        wheel=Path(args.wheel),
    )
    tests = _test_evidence(os.path.abspath(args.test_python))
    return _build_bundle(
        output_dir=Path(args.output_dir).resolve(),
        captured_date=args.captured_date,
        pin=pin,
        manifest=manifest,
        observations=observations,
        tests=tests,
        authorized_by=args.authorized_by,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-python", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--dependency-lock", required=True)
    parser.add_argument("--captured-date", required=True)
    parser.add_argument(
        "--authorized-by",
        required=True,
        help="authenticated human maintainer identity authorizing candidate -> verified",
    )
    parser.add_argument("--test-python", default=sys.executable)
    parser.add_argument(
        "--output-dir",
        default=str(PACKAGE_ROOT / "providers" / "tooluniverse" / PROVIDER_VERSION),
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
