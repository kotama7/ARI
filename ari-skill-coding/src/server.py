"""MCP Server for code writing and execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from ari.public.execution import (
    ContainerIdentityV1,
    ExecutionLimitsV1,
    ExecutionPolicyError,
    ExecutionRequestV1,
    ExecutionResultV1,
    MeasurementRecordV1,
    MeasurementSetV1,
    WorkspaceRefV1,
    execute_local,
)


_STDOUT_LIMIT = 4000
_READ_FILE_LIMIT = 8000
_MAX_EXECUTION_RECEIPTS = 1024
_EXECUTION_RECEIPTS: OrderedDict[str, dict] = OrderedDict()
_EXECUTION_RECEIPTS_LOCK = threading.Lock()

# ── Fail-safe: process sandbox ──────────────────────────
# Prevent fork bombs and ensure cleanup of all child processes on timeout.
# RLIMIT_NPROC is enforced per real-uid (kernel counts every task of the
# user, not just descendants of this process), so a fixed 1024 cap fires
# fork EAGAIN as soon as the user already has > 1024 threads anywhere —
# e.g. gcc->ld->collect2 during ``gcc x.c -o x && ./x`` dies with
# exit 254 on a workstation that has VSCode / multiple shells running.
# Opt in via ARI_MAX_CHILD_PROCS instead; default is no extra cap.
_MAX_CHILD_PROCS_ENV = os.environ.get("ARI_MAX_CHILD_PROCS", "").strip()
try:
    _MAX_CHILD_PROCS = int(_MAX_CHILD_PROCS_ENV) if _MAX_CHILD_PROCS_ENV else None
except ValueError:
    _MAX_CHILD_PROCS = None


def _resolve_work_dir(explicit: str | None) -> str:
    """Resolve caller subdirectories beneath the core-owned workspace root."""

    configured = Path(os.environ.get("ARI_WORK_DIR") or "/tmp/ari_work")
    if not configured.is_absolute():
        raise ExecutionPolicyError("ARI_WORK_DIR must be absolute")
    workspace = WorkspaceRefV1(root=str(configured))
    root = workspace.root
    if not explicit:
        return root
    candidate = Path(explicit)
    if not candidate.is_absolute():
        candidate = Path(root) / candidate
    if candidate == Path(root):
        return root
    return str(workspace.ensure_directory(str(candidate)))


server = Server("coding-skill")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="write_code",
            description=(
                "Write source code to a file in the specified working directory. "
                "Language is chosen by the caller; pick whatever fits the task "
                "(e.g. Python, C, C++, Fortran, Rust, Go, shell, ...). "
                "For compiled languages, invoke the compiler via run_bash afterwards."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "File name to write. The extension determines the "
                            "interpreter used by run_code and the tooling expected "
                            "from run_bash (e.g. main.py, main.c, main.cpp, "
                            "main.f90, main.rs, main.go, run.sh)."
                        ),
                    },
                    "code": {
                        "type": "string",
                        "description": "Code content to write",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                },
                "required": ["filename", "code"],
            },
        ),
        Tool(
            name="run_code",
            description=(
                "Execute a source file using an interpreter selected by its "
                "extension (.py -> python3, .sh -> bash, .js -> node, "
                ".rb -> ruby, .pl -> perl, .lua -> lua). "
                "For compiled languages (C/C++/Fortran/Rust/Go/...) or any "
                "custom build step, use run_bash to invoke the compiler and "
                "then run the resulting binary — run_code does NOT compile. "
                "Inline output is bounded; complete stdout/stderr are returned "
                "as content-addressed artifacts with SHA-256 digests."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "File name to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["filename"],
            },
        ),
        Tool(
            name="run_bash",
            description=(
                "Execute an explicitly shell-enabled bash command in the scoped "
                "workspace. Full stdout/stderr are content-addressed artifacts; "
                "the inline previews are bounded."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Bash command to execute",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="emit_results",
            description=(
                "Write a typed results.json file separating input parameters "
                "from measurements. Use this at the END of an experiment run "
                "after collecting numeric outputs — it lets downstream stages "
                "(transform → science_data, paper writing, summary stats) "
                "tell apart 'what we measured' from 'what we ran on', so a "
                "best-of reduction never accidentally picks an input size "
                "(e.g. nnz, M, K, threads) over a real metric (e.g. GFlops/s). "
                "All four dicts may be empty; fields are best-effort. The file "
                "is overwritten when called repeatedly; pass a different "
                "'file' name to keep multiple result variants."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "params": {
                        "type": "object",
                        "description": (
                            "Input/configuration parameters that DO NOT "
                            "represent measurement quality. Examples: "
                            "matrix dimensions (M, K, nnz, RHS_width), "
                            "thread count, ISA flags, packing mode, seed. "
                            "These are excluded from best-of reductions."
                        ),
                        "additionalProperties": True,
                    },
                    "measurements": {
                        "type": "object",
                        "description": (
                            "Actual measured quantities — the values a peer "
                            "reviewer would treat as the experiment's result. "
                            "Examples: GFlops_per_s, GB_per_s, latency_s, "
                            "accuracy. These ARE candidates for the best-of "
                            "primary metric."
                        ),
                        "additionalProperties": True,
                    },
                    "predictions": {
                        "type": "object",
                        "description": (
                            "Optional model-derived numbers (e.g. roofline "
                            "compute peak, memory bandwidth ceiling). Kept "
                            "separate so they cannot be mistaken for "
                            "measurements during reduction."
                        ),
                        "additionalProperties": True,
                    },
                    "scores": {
                        "type": "object",
                        "description": (
                            "Optional derived scores (e.g. parallel "
                            "efficiency, speedup ratio). Like predictions, "
                            "kept separate from raw measurements."
                        ),
                        "additionalProperties": True,
                    },
                    "provenance": {
                        "type": "object",
                        "description": (
                            "Optional {operand_name: source} tags recording HOW a "
                            "value was obtained, stored on the corresponding canonical "
                            'measurement record for the verification gate. Use "microbench" or '
                            '"benchmark" for an empirically MEASURED ceiling/peak '
                            "(so a normalized metric is not flagged as resting on a "
                            'placeholder), and "correctness" (or "reference") for a '
                            "residual computed against an INDEPENDENT reference (so the "
                            "output is not flagged as unverified). Best-effort/optional."
                        ),
                        "additionalProperties": True,
                    },
                    "units": {
                        "type": "object",
                        "description": (
                            "Optional {measurement_name: unit} declarations. "
                            "Missing units are recorded explicitly and prevent "
                            "scientific admission; units are never inferred."
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                    "execution": {
                        "type": "object",
                        "description": (
                            "Optional exact execution context copied from a prior "
                            "run_code/run_bash response: execution identity/attempt, "
                            "status, exit code, artifact digests, and server receipt. "
                            "Without it the measurements are explicitly marked "
                            "unreported and are not scientifically admissible."
                        ),
                        "properties": {
                            "execution_identity": {"type": "string"},
                            "execution_attempt_id": {"type": "string"},
                            "execution_status": {
                                "type": "string",
                                "enum": [
                                    "completed",
                                    "failed",
                                    "timed_out",
                                    "cancelled",
                                ],
                            },
                            "exit_code": {"type": ["integer", "null"]},
                            "artifact_digests": {
                                "type": "array",
                                "items": {"type": "string"},
                                "uniqueItems": True,
                            },
                            "receipt": {"type": "string"},
                        },
                        "required": [
                            "execution_identity",
                            "execution_attempt_id",
                            "execution_status",
                            "exit_code",
                            "artifact_digests",
                            "receipt",
                        ],
                        "additionalProperties": False,
                    },
                    "file": {
                        "type": "string",
                        "description": "Output file name (default: results.json)",
                        "default": "results.json",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="read_file",
            description=(
                "Read a text file from the working directory. Supports "
                "offset/limit for paginated reads of large files (use the "
                "returned 'next_offset' to continue)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File path relative to work_dir, or an absolute path "
                            "that resolves inside the same work_dir"
                        ),
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory",
                        "default": "/tmp/ari_work",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Start character offset (default 0)",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Max characters to return (default {_READ_FILE_LIMIT})",
                        "default": _READ_FILE_LIMIT,
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "write_code":
        result = _write_code(
            filename=arguments["filename"],
            code=arguments["code"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
        )
    elif name == "run_code":
        result = _run_code(
            filename=arguments["filename"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    elif name == "run_bash":
        result = _run_bash(
            command=arguments["command"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            timeout=arguments.get("timeout", 60),
        )
    elif name == "read_file":
        result = _read_file(
            path=arguments["path"],
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
            offset=arguments.get("offset", 0),
            limit=arguments.get("limit", _READ_FILE_LIMIT),
        )
    elif name == "emit_results":
        result = _emit_results(
            params=arguments.get("params") or {},
            measurements=arguments.get("measurements") or {},
            predictions=arguments.get("predictions") or {},
            scores=arguments.get("scores") or {},
            provenance=arguments.get("provenance") or {},
            units=arguments.get("units") or {},
            execution=arguments.get("execution"),
            file=arguments.get("file") or "results.json",
            work_dir=_resolve_work_dir(arguments.get("work_dir")),
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


def _write_code(filename: str, code: str, work_dir: str) -> dict:
    try:
        workspace = WorkspaceRefV1(root=work_dir)
        file_path = workspace.atomic_write_text(filename, code)
    except (ExecutionPolicyError, OSError, ValueError) as exc:
        return {"error": f"write_code rejected: {exc}"}
    return {
        "path": str(file_path),
        "digest": "sha256:" + hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "lines": len(code.splitlines()),
        "status": "written",
    }


# Schema version for the typed results contract — bumped when the on-disk
# layout changes in a way downstream readers must distinguish. Consumers
# (transform-skill, llm_evaluator) should accept any v1.* layout silently
# and warn on unknown majors.
_RESULTS_SCHEMA_VERSION = "1.0"
_TYPED_RESULTS_SCHEMA_VERSION = "ari.measurement-set/v1"


def _strict_json_dict(value: dict, *, field: str) -> dict:
    """Return a finite JSON object without changing keys or values."""

    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{field} keys must be non-empty strings")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain finite JSON values") from exc
    return dict(value)


def _emit_results(
    params: dict,
    measurements: dict,
    predictions: dict,
    scores: dict,
    file: str,
    work_dir: str,
    provenance: dict | None = None,
    units: dict | None = None,
    execution: dict | None = None,
) -> dict:
    """Write a typed results.json separating params from measurements.

    See the tool description for the contract semantics. The file is
    overwritten if it exists; callers that want to preserve prior runs
    must pass a distinct ``file`` name (e.g. ``results_seed42.json``).
    """
    try:
        parameters = _strict_json_dict(params, field="params")
        measured = _strict_json_dict(measurements, field="measurements")
        predicted = _strict_json_dict(predictions, field="predictions")
        scored = _strict_json_dict(scores, field="scores")
        declared_units = _strict_json_dict(units or {}, field="units")
        declared_provenance = _strict_json_dict(
            provenance or {}, field="provenance"
        )
    except ValueError as exc:
        return {"error": f"emit_results schema validation failed: {exc}"}
    execution_identity = None
    execution_attempt_id = None
    execution_status = "unreported"
    exit_code = None
    artifact_digests: list[str] = []
    execution_verified = False
    try:
        workspace = WorkspaceRefV1(root=work_dir)
    except (ExecutionPolicyError, OSError, ValueError) as exc:
        return {"error": f"emit_results workspace rejected: {exc}"}
    if execution is not None:
        if not isinstance(execution, dict):
            return {"error": "emit_results execution context must be an object"}
        allowed_execution = {
            "execution_identity",
            "execution_attempt_id",
            "execution_status",
            "exit_code",
            "artifact_digests",
            "receipt",
        }
        if set(execution) != allowed_execution:
            return {
                "error": "emit_results execution context has missing or unknown fields",
                "expected_fields": sorted(allowed_execution),
            }
        execution_identity = execution.get("execution_identity")
        execution_attempt_id = execution.get("execution_attempt_id")
        execution_status = execution.get("execution_status")
        exit_code = execution.get("exit_code")
        artifact_digests = execution.get("artifact_digests")
        if not isinstance(artifact_digests, list):
            return {"error": "emit_results artifact_digests must be an array"}
        receipt = execution.get("receipt")
        if not isinstance(receipt, str):
            return {"error": "emit_results execution receipt must be text"}
        with _EXECUTION_RECEIPTS_LOCK:
            issued = _EXECUTION_RECEIPTS.get(receipt)
        supplied = {
            "work_dir": workspace.root,
            "execution_identity": execution_identity,
            "execution_attempt_id": execution_attempt_id,
            "execution_status": execution_status,
            "exit_code": exit_code,
            "artifact_digests": tuple(artifact_digests),
        }
        if issued is None or any(
            supplied[key] != issued[key]
            for key in supplied
        ):
            return {"error": "emit_results execution receipt is invalid or mismatched"}
        try:
            for artifact in issued["artifacts"]:
                if workspace.file_digest(artifact["relative_path"]) != artifact["digest"]:
                    raise ValueError("artifact digest changed")
                path = workspace.resolve(artifact["relative_path"], require_file=True)
                if path.stat().st_size != artifact["size_bytes"]:
                    raise ValueError("artifact size changed")
        except (ExecutionPolicyError, FileNotFoundError, OSError, ValueError) as exc:
            return {"error": f"emit_results execution artifact verification failed: {exc}"}
        execution_verified = True
    unknown_units = sorted(set(declared_units) - set(measured))
    unknown_provenance = sorted(set(declared_provenance) - set(measured))
    if unknown_units or unknown_provenance:
        return {
            "error": "emit_results metadata refers to unknown measurements",
            "unknown_units": unknown_units,
            "unknown_provenance": unknown_provenance,
        }
    records: list[MeasurementRecordV1] = []
    try:
        for metric_id, value in sorted(measured.items()):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"measurement {metric_id!r} must be numeric")
            unit_value = declared_units.get(metric_id)
            if unit_value is not None and not isinstance(unit_value, str):
                raise ValueError(f"measurement unit for {metric_id!r} must be text")
            provenance_value = declared_provenance.get(metric_id)
            if provenance_value is not None and not isinstance(provenance_value, str):
                raise ValueError(
                    f"measurement provenance for {metric_id!r} must be text"
                )
            records.append(
                MeasurementRecordV1(
                    metric_id=metric_id,
                    value=value,
                    unit=unit_value,
                    unit_status="declared" if unit_value is not None else "missing",
                    provenance=provenance_value,
                    parameters=parameters,
                    artifact_digests=artifact_digests,
                    execution_identity=execution_identity,
                    execution_attempt_id=execution_attempt_id,
                    execution_status=execution_status,
                    exit_code=exit_code,
                )
            )
        typed = MeasurementSetV1(
            parameters=parameters,
            measurements=records,
            predictions=predicted,
            scores=scored,
            artifact_digests=artifact_digests,
        )
    except (TypeError, ValueError) as exc:
        return {"error": f"emit_results schema validation failed: {exc}"}

    payload = {
        "schema_version": _RESULTS_SCHEMA_VERSION,
        "typed_schema_version": _TYPED_RESULTS_SCHEMA_VERSION,
        "measurement_set": typed.model_dump(mode="json"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        out_path = workspace.atomic_write_text(file, serialized)
    except (ExecutionPolicyError, OSError, ValueError) as e:
        return {
            "error": f"emit_results: write failed: {e}",
            "path": file,
        }
    result = {
        "path": str(out_path),
        "schema_version": _RESULTS_SCHEMA_VERSION,
        "typed_schema_version": _TYPED_RESULTS_SCHEMA_VERSION,
        "digest": "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "params_keys": list(typed.parameters),
        "measurements_keys": [item.metric_id for item in typed.measurements],
        "predictions_keys": list(typed.predictions),
        "scores_keys": list(typed.scores),
        "missing_unit_measurements": [
            item.metric_id
            for item in typed.measurements
            if item.unit_status == "missing"
        ],
        "scientifically_admissible": bool(typed.measurements)
        and execution_verified
        and all(
            item.unit_status == "declared"
            and item.execution_status == "completed"
            and item.exit_code == 0
            and bool(item.artifact_digests)
            for item in typed.measurements
        ),
        "status": "written",
    }
    # Point-of-emission contract feedback: mirror the FINAL gate's presence checks
    # against the run-level metric_contract NOW, while the agent can still re-emit
    # (this file is overwritten on re-call). Observed failure this closes: an agent
    # VERIFIED its kernel (the correctness columns sat in its own results.csv) yet
    # emitted only throughput -- the paper then blocked at finalize for a check that
    # had passed, with no chance to fix it. Advisory only: the write above already
    # happened and is never altered; absent contract / absent ari-core => silent.
    try:
        import os as _os_ce

        _ck_ce = _os_ce.environ.get("ARI_CHECKPOINT_DIR", "").strip()
        _mc_p = Path(_ck_ce) / "metric_contract.json" if _ck_ce else None
        if _mc_p is not None and _mc_p.is_file():
            _mc = json.loads(_mc_p.read_text())
            if isinstance(_mc, dict) and _mc:
                from ari.public.claim_gate import check_emission as _check_emission

                _measurement_values = {
                    item.metric_id: item.value for item in typed.measurements
                }
                _measurement_provenance = {
                    item.metric_id: item.provenance
                    for item in typed.measurements
                    if item.provenance is not None
                }
                _warns = _check_emission(
                    _mc, _measurement_values, _measurement_provenance
                )
                if _warns:
                    result["contract_warnings"] = _warns
    except Exception:
        pass
    return result


def _execution_limits() -> ExecutionLimitsV1:
    return ExecutionLimitsV1(max_processes=_MAX_CHILD_PROCS)


def _issue_execution_receipt(
    result: ExecutionResultV1, workspace: WorkspaceRefV1
) -> str:
    artifact_digests = tuple(item.digest for item in result.artifacts)
    receipt = secrets.token_hex(32)
    issued = {
        "work_dir": workspace.root,
        "execution_identity": result.execution_identity,
        "execution_attempt_id": result.attempt_id,
        "execution_status": result.status,
        "exit_code": result.exit_code,
        "artifact_digests": artifact_digests,
        "artifacts": tuple(
            {
                "relative_path": item.relative_path,
                "digest": item.digest,
                "size_bytes": item.size_bytes,
            }
            for item in result.artifacts
        ),
    }
    with _EXECUTION_RECEIPTS_LOCK:
        _EXECUTION_RECEIPTS[receipt] = issued
        _EXECUTION_RECEIPTS.move_to_end(receipt)
        while len(_EXECUTION_RECEIPTS) > _MAX_EXECUTION_RECEIPTS:
            _EXECUTION_RECEIPTS.popitem(last=False)
    return receipt


def _execution_payload(
    result: ExecutionResultV1, workspace: WorkspaceRefV1
) -> dict:
    artifact_digests = [item.digest for item in result.artifacts]
    receipt = _issue_execution_receipt(result, workspace)
    payload = {
        "schema_version": result.schema_version,
        "stdout": result.stdout_preview,
        "stderr": result.stderr_preview,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "truncated": result.stdout_truncated or result.stderr_truncated,
        "exit_code": result.exit_code if result.exit_code is not None else -1,
        "status": (
            "success"
            if result.status == "completed"
            else "failed"
            if result.status == "failed"
            else result.status
        ),
        "execution_identity": result.execution_identity,
        "execution_status": result.status,
        "attempt_id": result.attempt_id,
        "environment_names": result.environment_names,
        "network_policy": result.network,
        "network_enforcement": result.network_report,
        "limits": result.limits.model_dump(mode="json"),
        "limit_report": result.limit_report.model_dump(mode="json"),
        "input_digests": result.input_digests,
        "input_bindings": result.input_bindings,
        "container": (
            result.container.model_dump(mode="json")
            if result.container is not None
            else None
        ),
        "artifacts": [item.model_dump(mode="json") for item in result.artifacts],
        "measurement_execution": {
            "execution_identity": result.execution_identity,
            "execution_attempt_id": result.attempt_id,
            "execution_status": result.status,
            "exit_code": result.exit_code,
            "artifact_digests": artifact_digests,
            "receipt": receipt,
        },
    }
    if result.status == "timed_out":
        payload["error"] = "execution timed out; process group was terminated"
    return payload


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _container_identity(config) -> ContainerIdentityV1:
    reference = str(config.image)
    runtime = str(config.mode)
    if runtime == "auto":
        from ari.public.container import detect_runtime

        runtime = detect_runtime()
    if runtime not in {"docker", "singularity", "apptainer"}:
        runtime = "unknown"
    digest: str | None = None
    path = Path(reference)
    if path.is_file() and not path.is_symlink():
        digest = _file_digest(path)
    else:
        match = re.search(r"@sha256:([0-9a-f]{64})$", reference)
        if match:
            digest = "sha256:" + match.group(1)
    return ContainerIdentityV1(
        runtime=runtime,
        reference=reference,
        digest=digest,
        resolution_status="resolved" if digest is not None else "unresolved",
    )


_INTERPRETERS: dict[str, list[str]] = {
    ".py": ["python3"],
    ".sh": ["bash"],
    ".js": ["node"],
    ".rb": ["ruby"],
    ".pl": ["perl"],
    ".lua": ["lua"],
}


def _run_code(filename: str, work_dir: str, timeout: int) -> dict:
    try:
        workspace = WorkspaceRefV1(root=work_dir)
        file_path = workspace.resolve(filename, require_file=True)
    except (ExecutionPolicyError, FileNotFoundError, OSError, ValueError) as exc:
        return {"error": f"run_code rejected: {exc}", "exit_code": -1}

    interp = _INTERPRETERS.get(file_path.suffix.lower())
    if interp is None:
        return {
            "error": (
                f"run_code has no interpreter for '{file_path.suffix}'. "
                "Use run_bash to compile and/or execute this file "
                "(e.g. `gcc -O3 main.c -o main && ./main`, "
                "`gfortran -O3 main.f90 -o main && ./main`, "
                "`cargo run --release`)."
            ),
            "exit_code": -1,
        }

    try:
        relative_path = file_path.relative_to(workspace.root).as_posix()
        request = ExecutionRequestV1(
            workspace=workspace,
            argv=interp + [relative_path],
            timeout_seconds=timeout,
            limits=_execution_limits(),
            input_digests={relative_path: workspace.file_digest(relative_path)},
        )
        return _execution_payload(execute_local(request), workspace)
    except (ExecutionPolicyError, OSError, ValueError) as exc:
        return {"error": f"run_code failed: {exc}", "exit_code": -1}


def _run_bash(command: str, work_dir: str, timeout: int) -> dict:
    try:
        workspace = WorkspaceRefV1(root=work_dir)
        from ari.public.container import config_from_env, container_shell_argv

        _ct_cfg = config_from_env()
        # Capture local execution env (hostname, cpu_info, …) once per
        # work_dir so the node_report builder can later record where this
        # experiment ran. Skip when running in container — host metadata
        # would be misleading and the host probes would defeat the
        # container-isolation contract.
        if _ct_cfg is None:
            try:
                from ari.public.run_env import capture_env

                capture_env(work_dir, executor="local")
            except Exception:
                pass
        if _ct_cfg is not None:
            runtime_environment = {
                name: os.environ[name]
                for name in ("APPTAINER_CACHEDIR", "SINGULARITY_CACHEDIR")
                if os.environ.get(name)
            }
            container_argv = container_shell_argv(
                _ct_cfg,
                command,
                cwd=work_dir,
                network="inherit",
            )
            if container_argv is None:
                raise ExecutionPolicyError(
                    "configured container resolved to host execution"
                )
            request = ExecutionRequestV1(
                workspace=workspace,
                argv=container_argv,
                timeout_seconds=timeout,
                environment=runtime_environment,
                limits=_execution_limits(),
                container=_container_identity(_ct_cfg),
            )
            normalized = execute_local(request)
        else:
            request = ExecutionRequestV1(
                workspace=workspace,
                shell_command=command,
                timeout_seconds=timeout,
                limits=_execution_limits(),
            )
            normalized = execute_local(request)
        return _execution_payload(normalized, workspace)
    except (ExecutionPolicyError, OSError, ValueError) as exc:
        return {"error": f"run_bash failed: {exc}", "exit_code": -1}


def _read_file(path: str, work_dir: str, offset: int, limit: int) -> dict:
    try:
        workspace = WorkspaceRefV1(root=work_dir)
        p = workspace.resolve(path, require_file=True)
        text = workspace.read_bytes(path, max_bytes=64 * 1024 * 1024).decode(
            "utf-8", errors="replace"
        )
    except (ExecutionPolicyError, FileNotFoundError, OSError, ValueError) as exc:
        return {"error": f"Read rejected: {exc}"}
    total = len(text)
    if offset < 0:
        offset = 0
    end = offset + limit
    chunk = text[offset:end]
    return {
        "path": str(p),
        "content": chunk,
        "offset": offset,
        "returned_chars": len(chunk),
        "total_chars": total,
        "truncated": end < total,
        "next_offset": end if end < total else None,
    }


async def main() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
