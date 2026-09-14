"""Restricted official Qiskit MCP circuit-transpilation bridge."""

from __future__ import annotations

import base64
import binascii
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from models import sanitize_text
from providers import ProviderAdapter, ProviderProtocolError, ProviderResponseV1
from qiskit_contracts import QiskitExperimentV1
from qiskit_identity import _file_sha256


def decode_qiskit_response(
    response: ProviderResponseV1, operation: str
) -> dict[str, Any]:
    if response.is_error:
        raise ProviderProtocolError(
            f"Qiskit MCP {operation} failed: {sanitize_text(response.text, limit=1_000)}"
        )
    value: Any = response.structured
    if not isinstance(value, dict):
        try:
            value = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProviderProtocolError(
                f"Qiskit MCP {operation} returned non-JSON"
            ) from exc
    for _depth in range(3):
        if not isinstance(value, dict) or set(value) != {"result"}:
            break
        value = value["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
    if not isinstance(value, dict):
        raise ProviderProtocolError(f"Qiskit MCP {operation} returned a non-object")
    if value.get("status") == "error" or value.get("error"):
        message = value.get("message") or value.get("error") or "unknown error"
        raise ProviderProtocolError(
            f"Qiskit MCP {operation} failed: {sanitize_text(str(message), limit=1_000)}"
        )
    return value


class QiskitCoreRuntime:
    """Call only the reviewed transpilation leaf from the official core MCP."""

    def __init__(self, transport: ProviderAdapter) -> None:
        self.transport = transport

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[ProviderAdapter]:
        connection = getattr(self.transport, "connection", None)
        if connection is None:
            yield self.transport
            return
        async with connection() as connected:
            yield connected

    async def transpile(
        self,
        profile: QiskitExperimentV1,
        workspace: Path,
        events: list[dict[str, Any]],
    ) -> tuple[Path, str, dict[str, Any]]:
        circuit_path = Path(profile.circuit.qpy_path)
        circuit_b64 = base64.b64encode(circuit_path.read_bytes()).decode("ascii")
        target = profile.backend.target
        arguments = {
            "circuit": circuit_b64,
            "optimization_level": profile.transpilation.optimization_level,
            "basis_gates": target.basis_gates,
            "coupling_map": target.coupling_map or None,
            "initial_layout": profile.transpilation.initial_layout,
            "seed_transpiler": profile.transpilation.seed_transpiler,
            "circuit_format": "qpy",
        }
        async with self._connection() as transport:
            response = await transport.invoke("transpile_circuit_tool", arguments)
        value = decode_qiskit_response(response, "transpile_circuit_tool")
        if value.get("status") != "success" or value.get("optimization_level") != (
            profile.transpilation.optimization_level
        ):
            raise ProviderProtocolError("Qiskit transpilation identity is incomplete")
        if value.get("basis_gates") != target.basis_gates:
            raise ProviderProtocolError("Qiskit transpiler changed the target basis")
        if value.get("coupling_map_type") != "custom":
            raise ProviderProtocolError("Qiskit transpiler changed the coupling policy")
        transpiled = value.get("transpiled_circuit")
        if not isinstance(transpiled, dict):
            raise ProviderProtocolError("Qiskit transpiler omitted its output circuit")
        encoded = transpiled.get("circuit_qpy")
        if not isinstance(encoded, str) or len(encoded) > 140_000_000:
            raise ProviderProtocolError("Qiskit transpiled QPY is missing or too large")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProviderProtocolError(
                "Qiskit transpiled QPY is invalid base64"
            ) from exc
        if not payload.startswith(b"QISKIT") or len(payload) > 100_000_000:
            raise ProviderProtocolError("Qiskit transpiled QPY header is invalid")
        output_qubits = transpiled.get("num_qubits")
        if (
            isinstance(output_qubits, bool)
            or not isinstance(output_qubits, int)
            or not profile.circuit.num_qubits <= output_qubits <= target.num_qubits
            or transpiled.get("num_clbits") != profile.circuit.num_clbits
        ):
            raise ProviderProtocolError(
                "Qiskit transpilation changed circuit dimensions"
            )
        output_path = workspace / "transpiled.qpy"
        output_path.write_bytes(payload)
        output_path.chmod(0o600)
        digest = _file_sha256(output_path)
        metadata = {
            key: item for key, item in transpiled.items() if key != "circuit_qpy"
        }
        events.append(
            {
                "stage": "transpile",
                "operation": "transpile_circuit_tool",
                "optimization_level": profile.transpilation.optimization_level,
                "seed_transpiler": profile.transpilation.seed_transpiler,
                "target_digest": target.target_digest,
                "output_qpy_digest": digest,
                "output": metadata,
                "improvements": value.get("improvements"),
            }
        )
        return output_path, digest, metadata


def qiskit_core_runtime_digest() -> str:
    return _file_sha256(Path(__file__).resolve())


__all__ = [
    "QiskitCoreRuntime",
    "decode_qiskit_response",
    "qiskit_core_runtime_digest",
]
