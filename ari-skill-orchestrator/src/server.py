"""ARI run control through canonical MCP stdio or MCP Streamable HTTP.

All transports call ``OrchestratorService``.  No REST route, filesystem path,
credential value, or scan-derived run state is exposed by this module.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError


_SRC_ROOT = Path(__file__).resolve().parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from ari_skill_orchestrator.auth import (  # noqa: E402
    AuthenticationError,
    AuthorizationError,
    HashedTokenVerifier,
    request_principal,
)
from ari_skill_orchestrator.contracts import PrincipalV1, RunRequestV1  # noqa: E402
from ari_skill_orchestrator.registry import (  # noqa: E402
    IdempotencyConflictError,
    QuotaExceededError,
    RegistryError,
    RunAuthorizationError,
    RunNotFoundError,
)
from ari_skill_orchestrator.service import (  # noqa: E402
    OrchestratorService,
    ResourcePolicyError,
    ServiceConfig,
    ServiceError,
)
from ari_skill_orchestrator.artifacts import ArtifactPolicyError  # noqa: E402


def _make_mcp() -> FastMCP:
    host = os.environ.get("ARI_ORCHESTRATOR_HTTP_HOST", "127.0.0.1").strip()
    if not host:
        raise AuthenticationError("ARI_ORCHESTRATOR_HTTP_HOST cannot be empty")
    try:
        port = int(os.environ.get("ARI_ORCHESTRATOR_HTTP_PORT", "9890"))
    except ValueError as exc:
        raise AuthenticationError(
            "ARI_ORCHESTRATOR_HTTP_PORT must be an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise AuthenticationError(
            "ARI_ORCHESTRATOR_HTTP_PORT must be between 1 and 65535"
        )
    token_file = os.environ.get("ARI_ORCHESTRATOR_HTTP_TOKENS_FILE", "").strip()
    if not token_file:
        return FastMCP(
            "ari-orchestrator",
            host=host,
            port=port,
            streamable_http_path="/mcp",
            json_response=True,
        )
    issuer = os.environ.get(
        "ARI_ORCHESTRATOR_OAUTH_ISSUER_URL", f"http://{host}:{port}"
    )
    resource = os.environ.get(
        "ARI_ORCHESTRATOR_OAUTH_RESOURCE_URL", f"http://{host}:{port}/mcp"
    )
    return FastMCP(
        "ari-orchestrator",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        token_verifier=HashedTokenVerifier(token_file),
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource,
            required_scopes=[],
        ),
    )


mcp = _make_mcp()
_network_auth_required = False


def _service() -> OrchestratorService:
    return OrchestratorService(ServiceConfig.from_environment())


def _principal() -> PrincipalV1:
    principal = request_principal()
    if _network_auth_required and principal.authentication != "bearer":
        raise AuthenticationError("authenticated bearer context is required")
    return principal


def _safe_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_input=False, include_url=False)
        first = errors[0] if errors else {"loc": (), "msg": "invalid request"}
        location = ".".join(str(item) for item in first.get("loc") or ())
        message = str(first.get("msg") or "invalid request")
        detail = f"{location}: {message}" if location else message
        return {"error": {"code": "invalid_request", "message": detail[:512]}}
    categories: tuple[tuple[type[Exception], str], ...] = (
        ((AuthorizationError, RunAuthorizationError), "forbidden"),
        ((RunNotFoundError,), "not_found"),
        ((IdempotencyConflictError,), "idempotency_conflict"),
        ((QuotaExceededError, ResourcePolicyError), "quota_exceeded"),
        ((ArtifactPolicyError,), "artifact_policy"),
        ((AuthenticationError,), "authentication_failed"),
        ((RegistryError, ServiceError), "orchestrator_error"),
    )
    for classes, code in categories:
        if isinstance(exc, classes):
            return {"error": {"code": code, "message": str(exc)[:512]}}
    return {
        "error": {
            "code": "internal_error",
            "message": f"unexpected {type(exc).__name__}",
        }
    }


def _call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except Exception as exc:  # MCP tools return a stable, non-secret error envelope.
        return _safe_error(exc)


def _optional_environment(name: str, supplied: str) -> str:
    return supplied or os.environ.get(name, "")


@mcp.tool()
def run_experiment(
    experiment_md: str,
    idempotency_key: str,
    parent_run_id: str = "",
    max_recursion_depth: int | None = None,
    max_nodes: int = 10,
    max_total_nodes: int = 100,
    max_descendant_runs: int = 32,
    estimated_cost_usd: float = 0.0,
    max_cost_usd: float = 100.0,
    cpus: int = 1,
    timeout_minutes: int = 60,
    model: str = "",
    llm_backend: str = "",
    executor: str = "",
    retrieval_backend: str = "",
) -> dict[str, Any]:
    """Idempotently submit one quota-bound ARI run and return its durable handle."""

    def operation() -> dict[str, Any]:
        inherited_parent = os.environ.get("ARI_PARENT_RUN_ID", "").strip()
        parent = parent_run_id.strip() or inherited_parent or None
        inherited_depth = os.environ.get("ARI_MAX_RECURSION_DEPTH", "").strip()
        if max_recursion_depth is None:
            try:
                effective_depth = int(inherited_depth) if inherited_depth else 3
            except ValueError as exc:
                raise ResourcePolicyError(
                    "ARI_MAX_RECURSION_DEPTH must be an integer"
                ) from exc
        else:
            effective_depth = max_recursion_depth
        request = RunRequestV1.from_parameters(
            experiment_md=experiment_md,
            idempotency_key=idempotency_key,
            parent_run_id=parent,
            max_recursion_depth=effective_depth,
            max_nodes=max_nodes,
            max_total_nodes=max_total_nodes,
            max_descendant_runs=max_descendant_runs,
            estimated_cost_usd=estimated_cost_usd,
            max_cost_usd=max_cost_usd,
            cpus=cpus,
            timeout_minutes=timeout_minutes,
            model=_optional_environment("ARI_MODEL", model),
            llm_backend=_optional_environment("ARI_BACKEND", llm_backend),
            executor=_optional_environment("ARI_EXECUTOR", executor),
            retrieval_backend=_optional_environment(
                "ARI_RETRIEVAL_BACKEND", retrieval_backend
            ),
        )
        return _service().submit(request, _principal()).model_dump(mode="json")

    return _call(operation)


@mcp.tool()
def get_status(run_id: str) -> dict[str, Any]:
    """Return the exact durable state and bounded scientific progress for a run."""

    return _call(
        lambda: _service().status(run_id, _principal()).model_dump(mode="json")
    )


@mcp.tool()
def get_result(run_id: str) -> dict[str, Any]:
    """Return terminal metadata and digest-addressed artifacts for a run."""

    return _call(
        lambda: _service().result(run_id, _principal()).model_dump(mode="json")
    )


@mcp.tool()
def stop_experiment(run_id: str) -> dict[str, Any]:
    """Cancel a run, propagate termination, and settle one terminal state."""

    return _call(lambda: _service().stop(run_id, _principal()).model_dump(mode="json"))


@mcp.tool()
def list_runs() -> dict[str, Any]:
    """List only runs owned by the authenticated principal (admins may list all)."""

    return _call(
        lambda: {
            "runs": [
                item.model_dump(mode="json")
                for item in _service().list_runs(_principal())
            ]
        }
    )


@mcp.tool()
def list_children(parent_run_id: str) -> dict[str, Any]:
    """List authorized direct descendants of one exact parent run ID."""

    return _call(
        lambda: {
            "parent_run_id": parent_run_id,
            "runs": [
                item.model_dump(mode="json")
                for item in _service().list_children(parent_run_id, _principal())
            ],
        }
    )


@mcp.tool()
def list_artifacts(run_id: str) -> dict[str, Any]:
    """List allowlisted, digest-verified artifacts without exposing paths."""

    return _call(
        lambda: {
            "run_id": run_id,
            "artifacts": _service().list_artifacts(run_id, _principal()),
        }
    )


@mcp.tool()
def read_artifact(run_id: str, artifact_id: str) -> dict[str, Any]:
    """Read a bounded admitted artifact by its exact SHA-256 identity."""

    return _call(lambda: _service().read_artifact(run_id, artifact_id, _principal()))


@mcp.tool()
def get_paper(run_id: str) -> dict[str, Any]:
    """Return paper artifact references for an authorized run."""

    return _call(lambda: _service().paper(run_id, _principal()))


@mcp.tool()
def get_ear(run_id: str) -> dict[str, Any]:
    """Return verified EAR and evidence artifact references for an authorized run."""

    return _call(lambda: _service().ear(run_id, _principal()))


@mcp.tool()
def list_skills(run_id: str) -> dict[str, Any]:
    """Return only the sanitized, immutable SKILLS.lock view for one run."""

    return _call(lambda: _service().list_skills(run_id, _principal()))


@mcp.tool()
def get_workflow(run_id: str) -> dict[str, Any]:
    """Return locked phase/tool membership without raw workflow or secret config."""

    return _call(lambda: _service().workflow(run_id, _principal()))


def main() -> None:
    global _network_auth_required

    parser = argparse.ArgumentParser(description="ARI Orchestrator MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument(
        "--repair-registry",
        action="store_true",
        help="explicitly import terminal pre-v2 checkpoints, then exit",
    )
    arguments = parser.parse_args()
    if arguments.repair_registry:
        print(
            json.dumps(
                _service().repair_legacy_registry(request_principal()),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return
    if (
        arguments.transport == "streamable-http"
        and not os.environ.get("ARI_ORCHESTRATOR_HTTP_TOKENS_FILE", "").strip()
    ):
        parser.error(
            "streamable-http requires ARI_ORCHESTRATOR_HTTP_TOKENS_FILE; "
            "unauthenticated network control is refused"
        )
    _network_auth_required = arguments.transport == "streamable-http"
    mcp.run(transport=arguments.transport)


if __name__ == "__main__":
    main()
