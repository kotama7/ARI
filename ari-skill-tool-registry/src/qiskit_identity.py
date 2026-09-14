"""Reviewed Qiskit MCP and scientific software release identities."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import sanitize_text, sha256_digest
from providers import ProviderProtocolError, PythonStdioLauncherV1


QISKIT_SUPPORT_MATRIX = (
    Path(__file__).resolve().parent.parent / "providers" / "qiskit-support-v1.json"
)
_SHA256_PREFIX = "sha256:"
_PROVIDER_POLICY_ENV = {
    "FASTMCP_CHECK_FOR_UPDATES": "off",
    "FASTMCP_SHOW_SERVER_BANNER": "false",
    "QISKIT_IBM_RUNTIME_LOG_LEVEL": "ERROR",
    "QISKIT_MCP_MAX_GATES": "10000",
    "QISKIT_MCP_MAX_QUBITS": "100",
}
_ROLE_PACKAGE = {
    "circuit": "qiskit_mcp_server",
    "runtime": "qiskit_ibm_runtime_mcp_server",
}


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise ProviderProtocolError(f"cannot hash Qiskit identity file: {exc}") from exc
    return _SHA256_PREFIX + hasher.hexdigest()


def _support_document() -> dict[str, Any]:
    try:
        value = json.loads(QISKIT_SUPPORT_MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(f"Qiskit support matrix is invalid: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != (
        "ari.qiskit-support/v1"
    ):
        raise ProviderProtocolError("Qiskit support matrix version is invalid")
    for key in ("provider_releases", "software_releases"):
        if not isinstance(value.get(key), list):
            raise ProviderProtocolError(f"Qiskit support matrix omitted {key}")
    return value


def qiskit_provider_release_pin(
    role: Literal["circuit", "runtime"], version: str
) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["provider_releases"]
        if item.get("role") == role and item.get("version") == version
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"unsupported Qiskit {role} MCP release {sanitize_text(version)!r}"
        )
    return dict(matches[0])


def qiskit_software_release(name: str, version: str) -> dict[str, Any]:
    matches = [
        item
        for item in _support_document()["software_releases"]
        if item.get("distribution_name") == name and item.get("version") == version
    ]
    if len(matches) != 1:
        raise ProviderProtocolError(
            f"unsupported Qiskit software release {sanitize_text(name)}@"
            f"{sanitize_text(version)}"
        )
    return dict(matches[0])


class QiskitProviderPinV1(BaseModel):
    """Exact official Qiskit MCP distribution release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["circuit", "runtime"]
    distribution_name: Literal["qiskit-mcp-server", "qiskit-ibm-runtime-mcp-server"]
    version: str
    repository_url: Literal["https://github.com/Qiskit/mcp-servers"]
    repository_commit: str
    repository_tag: str
    source_archive_digest: str
    wheel_digest: str
    license_id: Literal["Apache-2.0"]
    license_digest: str
    package_tree_digest: str
    dependency_lock_digest: str
    direct_dependencies: list[str] = Field(min_length=1)
    mcp_contract_digest: str
    python_requires: str

    @field_validator(
        "source_archive_digest",
        "wheel_digest",
        "license_digest",
        "package_tree_digest",
        "dependency_lock_digest",
        "mcp_contract_digest",
    )
    @classmethod
    def _digest(cls, value: str) -> str:
        if len(value) != 71 or not value.startswith(_SHA256_PREFIX):
            raise ValueError("Qiskit provider identities require SHA-256 digests")
        int(value.removeprefix(_SHA256_PREFIX), 16)
        return value

    @field_validator("repository_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if len(value) != 40:
            raise ValueError("Qiskit repository commit must be a full SHA-1")
        int(value, 16)
        return value

    @field_validator("direct_dependencies")
    @classmethod
    def _dependencies(cls, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values})
        if len(normalized) != len(values) or any(not item for item in normalized):
            raise ValueError("Qiskit direct dependency inventory is invalid")
        return normalized

    def verify(self) -> None:
        if self.model_dump(mode="json") != qiskit_provider_release_pin(
            self.role, self.version
        ):
            raise ProviderProtocolError("Qiskit MCP pin is not a reviewed release")


def qiskit_effective_launcher(
    launcher: PythonStdioLauncherV1, role: Literal["circuit", "runtime"]
) -> PythonStdioLauncherV1:
    environment = dict(_PROVIDER_POLICY_ENV)
    if role == "circuit":
        environment.pop("QISKIT_IBM_RUNTIME_LOG_LEVEL")
    return launcher.model_copy(update={"arguments": [], "literal_env": environment})


def verify_qiskit_provider_package(
    launcher: PythonStdioLauncherV1, pin: QiskitProviderPinV1
) -> None:
    expected_root = _ROLE_PACKAGE[pin.role]
    if Path(launcher.package_root).name != expected_root:
        raise ProviderProtocolError(
            f"Qiskit {pin.role} package_root must be {expected_root}"
        )
    root, _executable, _entrypoint = launcher.resolve()
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        size = path.stat().st_size
        total_bytes += size
        if len(files) >= 10_000 or total_bytes > 100_000_000:
            raise ProviderProtocolError("Qiskit MCP package exceeds reviewed bounds")
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": size,
                "digest": _file_sha256(path),
            }
        )
    actual = sha256_digest(files)
    if actual != pin.package_tree_digest:
        raise ProviderProtocolError(
            f"Qiskit {pin.role} MCP package tree drift: expected "
            f"{pin.package_tree_digest}, got {actual}"
        )


def verify_qiskit_python_distributions(
    launcher: PythonStdioLauncherV1,
    expected: dict[str, str],
) -> None:
    """Query only distribution versions through the pinned provider interpreter."""

    _root, executable, _entrypoint = launcher.resolve()
    names = sorted(expected)
    code = (
        "import importlib.metadata,json;"
        f"names={json.dumps(names)};"
        "print(json.dumps({n:importlib.metadata.version(n) for n in names},"
        "sort_keys=True))"
    )
    environment = {
        key: value
        for key in ("LANG", "LC_ALL", "PATH", "SSL_CERT_DIR", "SSL_CERT_FILE")
        if (value := os.environ.get(key))
    }
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    try:
        process = subprocess.run(
            [str(executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        actual = json.loads(process.stdout) if process.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ProviderProtocolError(
            f"cannot inspect Qiskit provider environment: {type(exc).__name__}"
        ) from exc
    if actual != dict(sorted(expected.items())):
        raise ProviderProtocolError(
            f"Qiskit distribution drift: expected {dict(sorted(expected.items()))}, "
            f"got {actual}"
        )


def qiskit_software_stack_digest(names: dict[str, str]) -> str:
    releases = [
        qiskit_software_release(name, version) for name, version in names.items()
    ]
    return sha256_digest(sorted(releases, key=lambda item: item["distribution_name"]))


def qiskit_identity_digest() -> str:
    return sha256_digest(
        {
            "identity_source": _file_sha256(Path(__file__).resolve()),
            "support_matrix": _file_sha256(QISKIT_SUPPORT_MATRIX),
        }
    )


__all__ = [
    "QiskitProviderPinV1",
    "qiskit_effective_launcher",
    "qiskit_identity_digest",
    "qiskit_provider_release_pin",
    "qiskit_software_release",
    "qiskit_software_stack_digest",
    "verify_qiskit_provider_package",
    "verify_qiskit_python_distributions",
]
