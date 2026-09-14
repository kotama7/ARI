"""Pinned ToolUniverse compact-collection transport.

ToolUniverse is treated as one collection provider.  Its compact MCP tools are
never exposed on ARI's public MCP surface: this adapter expands reviewed leaf
descriptors during operator sync and executes only leaf names already present
in the active catalog lock.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from models import canonical_json, sanitize_text, sha256_digest
from providers import (
    ProviderAdapter,
    ProviderProtocolError,
    ProviderResponseV1,
    ProviderToolV1,
    PythonStdioLauncherV1,
    StdioMCPAdapter,
    stdio_adapter_digest,
)


TOOLUNIVERSE_ADAPTER_ID = "ari.tooluniverse-compact"
TOOLUNIVERSE_ADAPTER_VERSION = "1.0.0"
TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES = (
    "manifest_schema",
    "source_package_digest_pin",
    "live_tools_list_parity",
    "schema_digest_pin",
    "capability_contract_conformance",
    "side_effect_declaration",
    "credential_scope",
    "environment_allowlist",
    "timeout_cancellation_process_group",
    "result_schema",
    "malicious_description_boundary",
    "workspace_isolation",
    "revocation_behavior",
    "schema_drift_detection",
    "unbound_invocation_rejection",
)
TOOLUNIVERSE_COMPACT_TOOLS = frozenset(
    {"list_tools", "grep_tools", "get_tool_info", "execute_tool"}
)
_NON_LEAF_TOOLS = TOOLUNIVERSE_COMPACT_TOOLS | frozenset({"find_tools"})
_SUPPORT_MATRIX = (
    Path(__file__).resolve().parent.parent
    / "providers"
    / "tooluniverse-support-v1.json"
)
_DANGEROUS_TYPE_FRAGMENTS = (
    "agentic",
    "codeinterpreter",
    "compose",
    "mcpautoloader",
    "mcpclient",
    "pythonexecutor",
    "shelltool",
    "toolfinderllm",
)
_DANGEROUS_CATEGORY_PREFIXES = (
    "mcp_auto_loader",
    "agentic",
    "code_interpreter",
)
_AUTH_FAILURE_RE = re.compile(
    r"(?:unauthori[sz]ed|unauthenticated|authentication failed|"
    r"invalid api key|missing api key|forbidden)",
    re.IGNORECASE,
)


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ProviderProtocolError(f"cannot read adapter support file: {exc}") from exc
    return f"sha256:{hasher.hexdigest()}"


def _support_document() -> dict[str, Any]:
    try:
        value = json.loads(_SUPPORT_MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ProviderProtocolError(
            f"ToolUniverse support matrix is unavailable or invalid: {exc}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != (
        "ari.tooluniverse-support/v1"
    ):
        raise ProviderProtocolError("ToolUniverse support matrix version is invalid")
    releases = value.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ProviderProtocolError("ToolUniverse support matrix has no releases")
    return value


def verify_tooluniverse_pin(pin: dict[str, Any]) -> None:
    """Require an exact entry from the reviewed support matrix."""

    releases = _support_document()["releases"]
    if pin not in releases:
        version = sanitize_text(pin.get("version", "<unknown>"), limit=100)
        raise ProviderProtocolError(
            f"ToolUniverse {version} is not an exact reviewed support-matrix pin"
        )
    if pin.get("artifact_kind") == "ari-patched-wheel":
        _verify_patched_support_artifacts(pin)


def _support_artifact(path_text: Any, expected_digest: Any) -> Path:
    relative = Path(str(path_text or ""))
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ProviderProtocolError("ToolUniverse support artifact path is unsafe")
    path = (_SUPPORT_MATRIX.parent / relative).resolve()
    try:
        path.relative_to(_SUPPORT_MATRIX.parent.resolve())
    except ValueError as exc:
        raise ProviderProtocolError(
            "ToolUniverse support artifact escapes the providers directory"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(
            f"ToolUniverse support artifact is not a regular file: {relative}"
        )
    actual = _file_sha256(path)
    if actual != expected_digest:
        raise ProviderProtocolError(
            f"ToolUniverse support artifact drift for {relative}: "
            f"expected {expected_digest}, got {actual}"
        )
    return path


def _verify_patched_support_artifacts(pin: dict[str, Any]) -> None:
    """Verify the checked-in patch, recipe, and single runtime lock as one unit."""

    patch = _support_artifact(pin.get("patch_path"), pin.get("patch_digest"))
    recipe_path = _support_artifact(
        pin.get("build_recipe_path"), pin.get("build_recipe_digest")
    )
    manifest_path = _support_json_artifact(
        pin.get("provider_manifest_path"), pin.get("provider_manifest_digest")
    )
    runtime_lock_path = _support_artifact(
        pin.get("checked_dependency_lock_path"), pin.get("dependency_lock_digest")
    )
    try:
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runtime_lock = tomllib.loads(runtime_lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProviderProtocolError(
            f"ToolUniverse patched support metadata is invalid: {exc}"
        ) from exc
    if not isinstance(recipe, dict) or recipe.get("schema_version") != (
        "ari.tooluniverse-build-recipe/v1"
    ):
        raise ProviderProtocolError("ToolUniverse patched build recipe version is invalid")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != (
        "ari.tooluniverse-capability-provider-manifest/v1"
    ):
        raise ProviderProtocolError("ToolUniverse Provider manifest version is invalid")
    if (
        recipe.get("provider_version") != pin.get("version")
        or recipe.get("expected_wheel_sha256") != pin.get("wheel_digest")
        or recipe.get("expected_package_tree_sha256")
        != pin.get("package_tree_digest")
        or recipe.get("patch", {}).get("sha256") != pin.get("patch_digest")
        or recipe.get("runtime_lock", {}).get("sha256")
        != pin.get("dependency_lock_digest")
        or recipe.get("upstream", {}).get("version") != pin.get("upstream_version")
        or recipe.get("upstream", {}).get("wheel_sha256")
        != pin.get("upstream_wheel_digest")
        or recipe.get("patch", {}).get("path") != patch.name
        or recipe.get("runtime_lock", {}).get("path") != runtime_lock_path.name
    ):
        raise ProviderProtocolError(
            "ToolUniverse patched build recipe conflicts with its support pin"
        )
    expected_artifact = _verified_artifact(pin)
    capabilities = manifest.get("capabilities")
    if (
        manifest.get("provider_id") != "tooluniverse-pubmed"
        or manifest.get("provider_version") != pin.get("version")
        or manifest.get("artifact") != expected_artifact
        or not isinstance(capabilities, list)
        or len(capabilities) != 1
        or capabilities[0].get("tool_name") != "PubMed_search_articles"
        or capabilities[0].get("capability_ref") != "ari.literature.search/v1"
        or capabilities[0].get("credential_scope_ids") != []
    ):
        raise ProviderProtocolError(
            "ToolUniverse Provider manifest expands or changes the reviewed identity"
        )
    packages = runtime_lock.get("package")
    if not isinstance(packages, list):
        raise ProviderProtocolError("ToolUniverse runtime lock omits its package graph")
    by_name = {
        str(item.get("name", "")).casefold(): item
        for item in packages
        if isinstance(item, dict)
    }
    forbidden = sorted({"fitz", "pathlib", "pyxnat"} & set(by_name))
    if forbidden:
        raise ProviderProtocolError(
            f"ToolUniverse runtime lock retains rejected dependencies: {forbidden}"
        )
    root = by_name.get("tooluniverse")
    if (
        not isinstance(root, dict)
        or root.get("version") != pin.get("version")
        or "pymupdf" not in by_name
        or by_name["pymupdf"].get("version") != "1.26.4"
    ):
        raise ProviderProtocolError(
            "ToolUniverse runtime lock does not close the patched provider dependency graph"
        )


def _support_json_artifact(path_text: Any, expected_digest: Any) -> Path:
    """Verify a canonical JSON support artifact without depending on whitespace."""

    relative = Path(str(path_text or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ProviderProtocolError("ToolUniverse JSON support artifact path is unsafe")
    path = (_SUPPORT_MATRIX.parent / relative).resolve()
    try:
        path.relative_to(_SUPPORT_MATRIX.parent.resolve())
    except ValueError as exc:
        raise ProviderProtocolError(
            "ToolUniverse JSON support artifact escapes the providers directory"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(
            f"ToolUniverse JSON support artifact is not a regular file: {relative}"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"ToolUniverse JSON support artifact is invalid: {exc}"
        ) from exc
    actual = sha256_digest(document)
    if actual != expected_digest:
        raise ProviderProtocolError(
            f"ToolUniverse JSON support artifact drift for {relative}: "
            f"expected {expected_digest}, got {actual}"
        )
    return path


def _verified_artifact(pin: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": pin.get("artifact_kind"),
        "build_recipe_digest": pin.get("build_recipe_digest"),
        "dependency_lock_digest": pin.get("dependency_lock_digest"),
        "package_tree_digest": pin.get("package_tree_digest"),
        "patch_digest": pin.get("patch_digest"),
        "upstream_version": pin.get("upstream_version"),
        "upstream_wheel_digest": pin.get("upstream_wheel_digest"),
        "wheel_digest": pin.get("wheel_digest"),
    }


def _verified_scope(manifest: dict[str, Any]) -> dict[str, Any]:
    capabilities = manifest["capabilities"]
    capability = capabilities[0]
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


def tooluniverse_release_pin(version: str) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["releases"]
        if item.get("version") == version
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"ToolUniverse release {sanitize_text(version, limit=100)!r} is not supported"
        )
    return dict(matches[0])


def verify_tooluniverse_package(
    launcher: PythonStdioLauncherV1,
    pin: dict[str, Any],
) -> None:
    """Match the installed package tree to the exact reviewed wheel payload."""

    root, _executable, _entrypoint = launcher.resolve()
    if root.name != "tooluniverse":
        raise ProviderProtocolError(
            "ToolUniverse package_root must be the exact installed tooluniverse directory"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if len(files) >= 50_000:
            raise ProviderProtocolError("ToolUniverse package exceeds 50,000 files")
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > 500_000_000:
            raise ProviderProtocolError("ToolUniverse package exceeds 500 MB")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "digest": _file_sha256(path),
            }
        )
    actual = sha256_digest(files)
    expected = pin.get("package_tree_digest")
    if actual != expected:
        raise ProviderProtocolError(
            "ToolUniverse installed package tree does not match the reviewed wheel: "
            f"expected {expected}, got {actual}"
        )


def verify_tooluniverse_dependency_lock(
    path: str | Path,
    pin: dict[str, Any],
) -> str:
    """Verify the exact upstream lock artifact reviewed for this release."""

    lock = Path(path)
    if lock.is_symlink() or not lock.is_file():
        raise ProviderProtocolError(
            "ToolUniverse dependency lock must be a regular file"
        )
    actual = _file_sha256(lock)
    expected = str(pin.get("dependency_lock_digest") or "")
    if actual != expected:
        raise ProviderProtocolError(
            "ToolUniverse dependency lock drift: "
            f"expected {expected}, got {actual}"
        )
    return actual


def verify_tooluniverse_wheel(path: str | Path, pin: dict[str, Any]) -> str:
    """Verify the retained immutable wheel and its primary metadata identity."""

    wheel = Path(path)
    if wheel.is_symlink() or not wheel.is_file():
        raise ProviderProtocolError("ToolUniverse wheel must be a regular file")
    actual = _file_sha256(wheel)
    expected = str(pin.get("wheel_digest") or "")
    if actual != expected:
        raise ProviderProtocolError(
            f"ToolUniverse wheel drift: expected {expected}, got {actual}"
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ProviderProtocolError(
                    "ToolUniverse wheel must contain exactly one METADATA file"
                )
            metadata = archive.read(metadata_names[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, KeyError) as exc:
        raise ProviderProtocolError(f"ToolUniverse wheel is invalid: {exc}") from exc
    headers: dict[str, list[str]] = {}
    for line in metadata.splitlines():
        if ":" not in line:
            if not line:
                break
            continue
        name, value = line.split(":", 1)
        headers.setdefault(name.casefold(), []).append(value.strip())
    if headers.get("name") != ["tooluniverse"] or headers.get("version") != [
        str(pin.get("version"))
    ]:
        raise ProviderProtocolError("ToolUniverse wheel metadata identity is invalid")
    requirements = headers.get("requires-dist", [])
    if pin.get("artifact_kind") == "ari-patched-wheel" and (
        not any(item.casefold() == "pymupdf==1.26.4" for item in requirements)
        or any(item.casefold().startswith("fitz") for item in requirements)
    ):
        raise ProviderProtocolError(
            "ToolUniverse patched wheel does not carry the reviewed PyMuPDF dependency"
        )
    return actual


def _sibling_artifact(root: Path, path_text: Any) -> Path:
    relative = Path(str(path_text or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ProviderProtocolError("ToolUniverse verified-lock artifact path is unsafe")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ProviderProtocolError(
            "ToolUniverse verified-lock artifact escapes its bundle"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise ProviderProtocolError(
            f"ToolUniverse verified-lock artifact is missing: {relative}"
        )
    return path


def _self_digest(document: dict[str, Any], field: str) -> str:
    return sha256_digest({key: value for key, value in document.items() if key != field})


def verify_tooluniverse_verified_lock(
    path: str | Path,
    pin: dict[str, Any],
) -> dict[str, Any]:
    """Validate a closed, evidence-bound, exact-scope Provider promotion lock."""

    verify_tooluniverse_pin(pin)
    lock_path = Path(path)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ProviderProtocolError(
            "ToolUniverse verified lock must be a regular file"
        )
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(f"ToolUniverse verified lock is invalid: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("schema_version") != (
        "ari.tooluniverse-verified-lock/v1"
    ):
        raise ProviderProtocolError("ToolUniverse verified lock version is invalid")
    expected_lock_digest = lock.get("lock_digest")
    if expected_lock_digest != _self_digest(lock, "lock_digest"):
        raise ProviderProtocolError("ToolUniverse verified lock digest mismatch")
    artifact = lock.get("artifact")
    scope = lock.get("capability_scope")
    registration = lock.get("registration")
    promotion = lock.get("promotion")
    manifest_path = _support_json_artifact(
        pin.get("provider_manifest_path"), pin.get("provider_manifest_digest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_scope = _verified_scope(manifest)
    if (
        lock.get("status") != "verified"
        or lock.get("provider_id") != "tooluniverse-pubmed"
        or lock.get("provider_version") != pin.get("version")
        or not isinstance(artifact, dict)
        or not isinstance(scope, dict)
        or not isinstance(registration, dict)
        or not isinstance(promotion, dict)
    ):
        raise ProviderProtocolError("ToolUniverse verified lock identity is invalid")
    expected_artifact = _verified_artifact(pin)
    if artifact != expected_artifact:
        raise ProviderProtocolError(
            "ToolUniverse verified lock artifact differs from its support pin"
        )
    if scope != expected_scope:
        raise ProviderProtocolError(
            "ToolUniverse verified lock expands or changes the reviewed PubMed scope"
        )
    expected_runtime = {
        "architecture": "x86_64",
        "operating_system": "linux",
        "python_implementation": "CPython",
        "python_minor": "3.13",
    }
    adapter = lock.get("adapter")
    if (
        lock.get("runtime_target") != expected_runtime
        or not isinstance(adapter, dict)
        or adapter.get("adapter_id") != TOOLUNIVERSE_ADAPTER_ID
        or adapter.get("adapter_version") != TOOLUNIVERSE_ADAPTER_VERSION
        or adapter.get("adapter_digest") != tooluniverse_adapter_digest()
    ):
        raise ProviderProtocolError(
            "ToolUniverse verified lock runtime or adapter identity drifted"
        )
    root = lock_path.parent
    evidence_path = _sibling_artifact(root, registration.get("evidence_path"))
    report_path = _sibling_artifact(root, registration.get("report_path"))
    approval_path = _sibling_artifact(root, promotion.get("approval_path"))
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"ToolUniverse promotion evidence is invalid: {exc}"
        ) from exc
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema_version")
        != "ari.tooluniverse-registration-evidence/v1"
        or evidence.get("bundle_digest") != _self_digest(evidence, "bundle_digest")
        or evidence.get("bundle_digest") != registration.get("evidence_bundle_digest")
        or evidence.get("provider_id") != lock.get("provider_id")
        or evidence.get("provider_version") != lock.get("provider_version")
        or evidence.get("artifact") != expected_artifact
        or evidence.get("capability_scope") != expected_scope
    ):
        raise ProviderProtocolError(
            "ToolUniverse registration evidence bundle digest mismatch"
        )
    if (
        not isinstance(report, dict)
        or report.get("schema_version")
        != "ari.capability-provider-registration-report/v1"
        or report.get("report_digest") != _self_digest(report, "report_digest")
        or report.get("report_digest") != registration.get("report_digest")
        or report.get("provider_id") != lock.get("provider_id")
        or report.get("manifest_sha256") != pin.get("provider_manifest_digest")
        or report.get("decision") != "eligible-for-verified"
        or registration.get("provider_manifest_path")
        != Path(str(pin.get("provider_manifest_path"))).name
        or registration.get("provider_manifest_digest")
        != pin.get("provider_manifest_digest")
    ):
        raise ProviderProtocolError(
            "ToolUniverse registration report is not eligible for verified"
        )
    gates = report.get("gates")
    gate_evidence = evidence.get("gate_evidence")
    if not isinstance(gates, list) or not isinstance(gate_evidence, dict):
        raise ProviderProtocolError("ToolUniverse registration gates are missing")
    observed_gate_ids = tuple(item.get("gate_id") for item in gates if isinstance(item, dict))
    if observed_gate_ids != TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES:
        raise ProviderProtocolError("ToolUniverse registration gates are incomplete")
    if (
        len(gate_evidence) != len(TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES)
        or set(gate_evidence) != set(TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES)
    ):
        raise ProviderProtocolError(
            "ToolUniverse registration evidence gates are incomplete or out of order"
        )
    for gate in gates:
        gate_id = gate["gate_id"]
        item = gate_evidence.get(gate_id)
        if (
            gate.get("passed") is not True
            or not isinstance(item, dict)
            or not item
            or not str(gate.get("detail") or "").strip()
            or gate.get("evidence_digest") != sha256_digest(item)
        ):
            raise ProviderProtocolError(
                f"ToolUniverse registration gate evidence mismatch: {gate_id}"
            )
    if (
        not isinstance(approval, dict)
        or approval.get("schema_version")
        != "ari.capability-provider-promotion-approval/v1"
        or approval.get("approval_digest")
        != _self_digest(approval, "approval_digest")
        or approval.get("approval_digest") != promotion.get("approval_digest")
        or approval.get("provider_id") != lock.get("provider_id")
        or approval.get("provider_version") != lock.get("provider_version")
        or approval.get("from_status") != "candidate"
        or approval.get("to_status") != "verified"
        or approval.get("actor_kind") != "human-maintainer"
        or not str(approval.get("actor_id") or "").strip()
        or approval.get("authorization_basis") != "explicit-maintainer-approval"
        or approval.get("provider_manifest_digest")
        != registration.get("provider_manifest_digest")
        or approval.get("registration_report_digest")
        != registration.get("report_digest")
        or approval.get("evidence_bundle_digest")
        != registration.get("evidence_bundle_digest")
        or approval.get("capability_scope_digest") != sha256_digest(expected_scope)
    ):
        raise ProviderProtocolError(
            "ToolUniverse formal promotion approval is missing or invalid"
        )
    return lock


def verify_tooluniverse_environment(
    launcher: PythonStdioLauncherV1,
    pin: dict[str, Any],
) -> dict[str, Any]:
    """Require the installed environment's declared dependencies to close."""

    _root, executable, _entrypoint = launcher.resolve()
    completed = subprocess.run(
        [str(executable), "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=False,
        timeout=120,
        env={
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    )
    output = (completed.stdout + completed.stderr)[: 256 * 1024]
    report: dict[str, Any] = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "output_digest": "sha256:" + hashlib.sha256(output).hexdigest(),
    }
    if completed.returncode != 0:
        diagnostic = sanitize_text(
            output.decode("utf-8", errors="replace"), limit=2_000
        )
        raise ProviderProtocolError(
            f"ToolUniverse dependency environment is incomplete: {diagnostic}"
        )
    probe = subprocess.run(
        [
            str(executable),
            "-c",
            (
                "import importlib.metadata as m,json,platform,sys;"
                "names=('tooluniverse','pymupdf','fitz','pathlib','pyxnat');"
                "versions={};"
                "[(versions.__setitem__(n,m.version(n)) if True else None) "
                "for n in names if any(d.metadata.get('Name','').casefold()==n "
                "for d in m.distributions())];"
                "print(json.dumps({'implementation':platform.python_implementation(),"
                "'python':list(sys.version_info[:3]),'system':platform.system().casefold(),"
                "'machine':platform.machine(),'versions':versions},sort_keys=True))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    )
    try:
        inventory = json.loads(probe.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderProtocolError(
            "ToolUniverse environment identity probe returned invalid JSON"
        ) from exc
    versions = inventory.get("versions") if isinstance(inventory, dict) else None
    if (
        probe.returncode != 0
        or not isinstance(versions, dict)
        or versions.get("tooluniverse") != pin.get("version")
    ):
        raise ProviderProtocolError(
            "ToolUniverse installed distribution identity does not match the support pin"
        )
    if pin.get("artifact_kind") == "ari-patched-wheel" and (
        versions.get("pymupdf") != "1.26.4"
        or {"fitz", "pathlib", "pyxnat"} & set(versions)
        or inventory.get("implementation") != "CPython"
        or inventory.get("python", [])[:2] != [3, 13]
        or inventory.get("system") != "linux"
        or inventory.get("machine") != "x86_64"
    ):
        raise ProviderProtocolError(
            "ToolUniverse patched runtime differs from its closed verified target"
        )
    report["environment_identity"] = inventory
    report["environment_identity_digest"] = sha256_digest(inventory)
    return report


def tooluniverse_adapter_digest() -> str:
    return sha256_digest(
        {
            "adapter_source": _file_sha256(Path(__file__).resolve()),
            "generic_stdio_adapter": stdio_adapter_digest(),
            "source_projection": _file_sha256(
                Path(__file__).resolve().with_name("sources.py")
            ),
            "result_projection": _file_sha256(
                Path(__file__).resolve().with_name("semantic_projection.py")
            ),
            "support_matrix": _file_sha256(_SUPPORT_MATRIX),
        }
    )


def dangerous_leaf(category: str, tool_type: str) -> str | None:
    normalized_type = re.sub(r"[^a-z0-9]", "", tool_type.casefold())
    for fragment in _DANGEROUS_TYPE_FRAGMENTS:
        if fragment in normalized_type:
            return f"tool type {tool_type!r} is execution-composing or dynamic"
    folded_category = category.casefold()
    if any(
        folded_category.startswith(prefix) for prefix in _DANGEROUS_CATEGORY_PREFIXES
    ):
        return f"category {category!r} can dynamically load or execute tools"
    return None


def _response_object(response: ProviderResponseV1, operation: str) -> dict[str, Any]:
    if response.is_error:
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} failed: "
            f"{sanitize_text(response.text, limit=1_000)}"
        )
    value: Any = response.structured
    if not isinstance(value, dict):
        try:
            value = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderProtocolError(
                f"ToolUniverse compact operation {operation} returned non-JSON"
            ) from exc
    if isinstance(value, dict) and set(value) == {"result"}:
        nested = value["result"]
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except json.JSONDecodeError:
                pass
        if isinstance(nested, dict):
            value = nested
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} returned a non-object"
        )
    status = str(value.get("status") or "").casefold()
    if (
        status in {"error", "failed", "failure", "unauthorized"}
        or (value.get("error_type") and value.get("error"))
        or (value.get("success") is False and value.get("error"))
    ):
        raise ProviderProtocolError(
            f"ToolUniverse compact operation {operation} failed: "
            f"{sanitize_text(value.get('error'), limit=1_000)}"
        )
    return value


def _schema(value: Any, *, field: str, tool_name: str) -> dict[str, Any]:
    if value is None and field == "output_schema":
        return {}
    if not isinstance(value, dict):
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has a non-object {field}"
        )
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has an invalid {field}: {exc.message}"
        ) from exc
    if len(canonical_json(value).encode("utf-8")) > 262_144:
        raise ProviderProtocolError(
            f"ToolUniverse leaf {tool_name!r} has a {field} larger than 256 KiB"
        )
    return value


def _normalize_property_required_markers(
    value: Any,
    *,
    path: str = "$",
) -> tuple[Any, list[str]]:
    """Translate ToolUniverse's pinned property-level required dialect.

    ToolUniverse v1.3.1 represents required parameters as
    ``properties.<name>.required: true``.  Draft 2020-12 represents the same
    constraint as the property name in the containing object's ``required``
    array.  No value types or defaults are changed.
    """

    if isinstance(value, list):
        output: list[Any] = []
        notes: list[str] = []
        for index, item in enumerate(value):
            normalized, child_notes = _normalize_property_required_markers(
                item, path=f"{path}/{index}"
            )
            output.append(normalized)
            notes.extend(child_notes)
        return output, notes
    if not isinstance(value, dict):
        return value, []

    output: dict[str, Any] = {}
    notes: list[str] = []
    for key, item in value.items():
        if key == "properties" and isinstance(item, dict):
            properties: dict[str, Any] = {}
            marker_required: list[str] = []
            for property_name, property_schema in item.items():
                normalized, child_notes = _normalize_property_required_markers(
                    property_schema,
                    path=f"{path}/properties/{property_name}",
                )
                if isinstance(normalized, dict) and isinstance(
                    normalized.get("required"), bool
                ):
                    marker = normalized.pop("required")
                    if marker:
                        marker_required.append(str(property_name))
                    child_notes.append(
                        f"property-required-marker:{path}/properties/{property_name}"
                    )
                properties[str(property_name)] = normalized
                notes.extend(child_notes)
            output[key] = properties
            existing = value.get("required")
            if marker_required and (
                existing is None
                or (
                    isinstance(existing, list)
                    and all(isinstance(item, str) for item in existing)
                )
            ):
                output["required"] = sorted(set(marker_required) | set(existing or []))
            continue
        if key == "required" and "required" in output:
            continue
        normalized, child_notes = _normalize_property_required_markers(
            item, path=f"{path}/{key}"
        )
        output[str(key)] = normalized
        notes.extend(child_notes)
    return output, notes


def _package_relative_source_file(value: Any, package_root: Path) -> Any:
    """Express a leaf's source file relative to the reviewed package.

    Upstream reports ``source_file`` as an absolute installation path.  It
    reaches both the leaf metadata and ``tool_spec_digest``, so digesting it
    verbatim pins the install location rather than the leaf definition: the
    same reviewed wheel yields a different leaf identity on every machine, and
    the promoting host's absolute paths are written into promotion evidence.
    Paths outside the reviewed package are replaced rather than disclosed.
    """

    if not isinstance(value, str) or not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        return value
    try:
        return path.resolve().relative_to(package_root.resolve()).as_posix()
    except (OSError, ValueError):
        return "<outside-reviewed-package>"


def _metadata(summary: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "category",
        "type",
        "source_file",
        "package_name",
        "endpoint",
        "tool_url",
        "required_api_keys",
        "optional_api_keys",
        "metadata",
        "local_info",
        "remote_info",
    )
    metadata: dict[str, Any] = {}
    for key in keys:
        value = spec.get(key, summary.get(key))
        if value is not None:
            metadata[key] = value
    return metadata


class _ToolUniverseStdioTransport(StdioMCPAdapter):
    """Stdio transport with ToolUniverse's mutable user state disabled."""

    def _environment(self, isolated_home: Path) -> dict[str, str]:
        environment = super()._environment(isolated_home)
        workspace = isolated_home / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "TOOLUNIVERSE_HOME": str(workspace),
                "TOOLUNIVERSE_COERCE_TYPES": "false",
                "TOOLUNIVERSE_STRICT_VALIDATION": "true",
                "TOOLUNIVERSE_CACHE_ENABLED": "false",
                "TOOLUNIVERSE_CACHE_PERSIST": "false",
                "FASTMCP_CHECK_FOR_UPDATES": "off",
                "FASTMCP_SHOW_SERVER_BANNER": "false",
            }
        )
        return environment


class ToolUniverseCompactAdapter:
    """Expand and invoke ToolUniverse leaves through four compact MCP tools."""

    def __init__(
        self,
        launcher: PythonStdioLauncherV1,
        *,
        expected_provider_digest: str,
        pin: dict[str, Any],
        include_categories: Iterable[str] = (),
        exclude_categories: Iterable[str] = (),
        include_leaf_names: Iterable[str] = (),
        allowed_leaf_names: Iterable[str] | None = None,
        leaf_spec_digests: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        page_size: int = 250,
        info_batch_size: int = 20,
        max_pages: int = 1_000,
        max_tools: int = 100_000,
        transport: ProviderAdapter | None = None,
        verify_package: bool = True,
    ) -> None:
        verify_tooluniverse_pin(pin)
        if verify_package:
            verify_tooluniverse_package(launcher, pin)
        if page_size < 1 or page_size > 1_000:
            raise ValueError("ToolUniverse page_size must be between 1 and 1000")
        if info_batch_size < 1 or info_batch_size > 100:
            raise ValueError("ToolUniverse info_batch_size must be between 1 and 100")
        if max_pages < 1 or max_tools < 1:
            raise ValueError("ToolUniverse collection bounds must be positive")
        self.launcher = launcher
        self.expected_provider_digest = expected_provider_digest
        self.pin = dict(pin)
        self.include_categories = frozenset(include_categories)
        self.exclude_categories = frozenset(exclude_categories)
        self.include_leaf_names = frozenset(include_leaf_names)
        overlap = self.include_categories & self.exclude_categories
        if overlap:
            raise ValueError(
                f"ToolUniverse category filters overlap: {sorted(overlap)}"
            )
        self.allowed_leaf_names = (
            frozenset(allowed_leaf_names) if allowed_leaf_names is not None else None
        )
        self.leaf_spec_digests = dict(leaf_spec_digests or {})
        self.timeout_seconds = timeout_seconds
        self.page_size = page_size
        self.info_batch_size = info_batch_size
        self.max_pages = max_pages
        self.max_tools = max_tools
        self.transport = transport or _ToolUniverseStdioTransport(
            launcher,
            expected_provider_digest=expected_provider_digest,
            timeout_seconds=timeout_seconds,
            max_pages=8,
            max_tools=16,
        )

    async def _call(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        transport: ProviderAdapter | None = None,
    ) -> dict[str, Any]:
        response = await (transport or self.transport).invoke(operation, arguments)
        return _response_object(response, operation)

    async def _summaries(
        self, transport: ProviderAdapter | None = None
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        offset = 0
        for _page in range(self.max_pages):
            payload = await self._call(
                "list_tools",
                {
                    "mode": "custom",
                    "fields": [
                        "name",
                        "type",
                        "category",
                        "source_file",
                        "package_name",
                        "required_api_keys",
                        "optional_api_keys",
                    ],
                    "limit": self.page_size,
                    "offset": offset,
                },
                transport=transport,
            )
            tools = payload.get("tools")
            if not isinstance(tools, list):
                raise ProviderProtocolError(
                    "ToolUniverse list_tools response omitted its tools array"
                )
            for raw in tools:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                    raise ProviderProtocolError(
                        "ToolUniverse list_tools returned a malformed tool summary"
                    )
                name = raw["name"]
                if name in seen_names:
                    raise ProviderProtocolError(
                        f"ToolUniverse list_tools returned duplicate leaf {name!r}"
                    )
                seen_names.add(name)
                category = raw.get("category")
                if not isinstance(category, str) or not category:
                    category = "unknown"
                    raw = {**raw, "category": category}
                selected = (
                    not self.include_categories or category in self.include_categories
                ) and category not in self.exclude_categories
                selected = selected and (
                    not self.include_leaf_names or name in self.include_leaf_names
                )
                if name not in _NON_LEAF_TOOLS and selected:
                    summaries.append(raw)
                    if len(summaries) > self.max_tools:
                        raise ProviderProtocolError(
                            f"ToolUniverse exceeds max_tools={self.max_tools}"
                        )
            has_more = payload.get("has_more")
            next_offset = payload.get("next_offset")
            if has_more is False or (has_more is None and len(tools) < self.page_size):
                return summaries
            if not isinstance(next_offset, int):
                next_offset = offset + len(tools)
            if next_offset <= offset:
                raise ProviderProtocolError(
                    "ToolUniverse list_tools pagination did not advance"
                )
            offset = next_offset
        raise ProviderProtocolError(
            f"ToolUniverse list_tools exceeds max_pages={self.max_pages}"
        )

    async def _list_tools_connected(
        self, transport: ProviderAdapter | None = None
    ) -> list[ProviderToolV1]:
        summaries = await self._summaries(transport)
        by_name = {item["name"]: item for item in summaries}
        names = sorted(by_name)
        output: list[ProviderToolV1] = []
        for offset in range(0, len(names), self.info_batch_size):
            batch = names[offset : offset + self.info_batch_size]
            payload = await self._call(
                "get_tool_info",
                {"tool_names": batch, "detail_level": "full"},
                transport=transport,
            )
            raw_tools = payload.get("tools")
            if not isinstance(raw_tools, list):
                if len(batch) == 1 and payload.get("name") == batch[0]:
                    raw_tools = [payload]
                else:
                    raise ProviderProtocolError(
                        "ToolUniverse get_tool_info response omitted its tools array"
                    )
            returned: set[str] = set()
            for spec in raw_tools:
                if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
                    raise ProviderProtocolError(
                        "ToolUniverse get_tool_info returned a malformed definition"
                    )
                name = spec["name"]
                if name not in batch or name in returned or spec.get("error"):
                    raise ProviderProtocolError(
                        f"ToolUniverse get_tool_info did not define locked leaf {name!r}"
                    )
                returned.add(name)
                summary = by_name[name]
                # Normalize before both ``_metadata`` and ``tool_spec_digest``
                # so a leaf's identity follows the reviewed package, not the
                # directory this installation happens to live in.
                package_root = Path(self.launcher.package_root)
                if "source_file" in spec:
                    spec = {
                        **spec,
                        "source_file": _package_relative_source_file(
                            spec["source_file"], package_root
                        ),
                    }
                if "source_file" in summary:
                    summary = {
                        **summary,
                        "source_file": _package_relative_source_file(
                            summary["source_file"], package_root
                        ),
                    }
                for key in ("type", "category"):
                    if key in spec and key in summary and spec[key] != summary[key]:
                        raise ProviderProtocolError(
                            f"ToolUniverse leaf {name!r} changed {key} during sync"
                        )
                schema_errors: list[str] = []
                schema_normalizations: list[str] = []
                try:
                    normalized_input, input_notes = (
                        _normalize_property_required_markers(spec.get("parameter"))
                    )
                    schema_normalizations.extend(input_notes)
                    input_schema = _schema(
                        normalized_input,
                        field="input_schema",
                        tool_name=name,
                    )
                    if "required" not in input_schema and isinstance(
                        spec.get("required"), list
                    ):
                        input_schema = {**input_schema, "required": spec["required"]}
                        Draft202012Validator.check_schema(input_schema)
                except (ProviderProtocolError, SchemaError) as exc:
                    schema_errors.append(sanitize_text(exc, limit=1_000))
                    input_schema = {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    }
                try:
                    normalized_output, output_notes = (
                        _normalize_property_required_markers(spec.get("return_schema"))
                    )
                    schema_normalizations.extend(output_notes)
                    output_schema = _schema(
                        normalized_output,
                        field="output_schema",
                        tool_name=name,
                    )
                except ProviderProtocolError as exc:
                    schema_errors.append(sanitize_text(exc, limit=1_000))
                    output_schema = {}
                metadata = _metadata(summary, spec)
                metadata.update(
                    {
                        "collection": "tooluniverse",
                        "collection_version": self.pin["version"],
                        "collection_wheel_digest": self.pin["wheel_digest"],
                        "tool_spec_digest": sha256_digest(spec),
                    }
                )
                if schema_errors:
                    metadata["schema_errors"] = schema_errors
                if schema_normalizations:
                    metadata["schema_normalizations"] = sorted(
                        set(schema_normalizations)
                    )[:1_000]
                output.append(
                    ProviderToolV1(
                        name=name,
                        description=str(spec.get("description") or ""),
                        input_schema=input_schema,
                        output_schema=output_schema,
                        annotations={"ari_tooluniverse": metadata},
                    )
                )
            missing = sorted(set(batch) - returned)
            if missing:
                raise ProviderProtocolError(
                    f"ToolUniverse get_tool_info omitted leaves: {missing}"
                )
        return sorted(output, key=lambda tool: tool.name)

    async def list_tools(self) -> list[ProviderToolV1]:
        connection = getattr(self.transport, "connection", None)
        if connection is None:
            return await self._list_tools_connected()
        result: list[ProviderToolV1] | None = None
        failure: ProviderProtocolError | None = None
        async with connection() as connected:
            try:
                result = await self._list_tools_connected(connected)
            except ProviderProtocolError as exc:
                # Exit the AnyIO task group normally so it does not obscure the
                # leaf protocol error inside an ExceptionGroup.
                failure = exc
        if failure is not None:
            raise failure
        assert result is not None
        return result

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ProviderResponseV1:
        if self.allowed_leaf_names is None or name not in self.allowed_leaf_names:
            raise ProviderProtocolError(
                "ToolUniverse runtime accepts only a leaf from the active catalog lock"
            )
        null_fields = sorted(key for key, value in arguments.items() if value is None)
        if null_fields:
            raise ProviderProtocolError(
                "ToolUniverse strips explicit null values; locked invocation refuses "
                f"ambiguous fields {null_fields}"
            )
        response = await self.transport.invoke(
            "execute_tool", {"tool_name": name, "arguments": arguments}
        )
        try:
            value = _response_object(response, "execute_tool")
            failed = False
        except ProviderProtocolError:
            value = None
            failed = True
        text = response.text
        is_auth_failure = bool(_AUTH_FAILURE_RE.search(text))
        is_error = response.is_error or failed or is_auth_failure
        structured = dict(
            response.structured or (value if isinstance(value, dict) else {})
        )
        reserved = "_ari_collection_provenance"
        if reserved in structured:
            raise ProviderProtocolError(
                f"ToolUniverse leaf {name!r} returned reserved field {reserved!r}"
            )
        structured[reserved] = {
            "adapter_id": TOOLUNIVERSE_ADAPTER_ID,
            "adapter_version": TOOLUNIVERSE_ADAPTER_VERSION,
            "collection": "tooluniverse",
            "collection_version": self.pin["version"],
            "collection_wheel_digest": self.pin["wheel_digest"],
            "provider_digest": self.expected_provider_digest,
            "leaf_spec_digest": self.leaf_spec_digests.get(name),
            "upstream_cache": "disabled",
        }
        return ProviderResponseV1(
            text=text,
            structured=structured,
            is_error=is_error,
        )

    async def get_status(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )

    async def get_result(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )

    async def cancel(self, lifecycle, provider_handle):  # pragma: no cover
        raise ProviderProtocolError(
            "ToolUniverse compact leaves have no generic lifecycle"
        )


__all__ = [
    "TOOLUNIVERSE_ADAPTER_ID",
    "TOOLUNIVERSE_ADAPTER_VERSION",
    "TOOLUNIVERSE_COMPACT_TOOLS",
    "TOOLUNIVERSE_PROVIDER_REGISTRATION_GATES",
    "ToolUniverseCompactAdapter",
    "dangerous_leaf",
    "tooluniverse_adapter_digest",
    "tooluniverse_release_pin",
    "verify_tooluniverse_dependency_lock",
    "verify_tooluniverse_environment",
    "verify_tooluniverse_environment",
    "verify_tooluniverse_package",
    "verify_tooluniverse_pin",
    "verify_tooluniverse_verified_lock",
    "verify_tooluniverse_wheel",
]
