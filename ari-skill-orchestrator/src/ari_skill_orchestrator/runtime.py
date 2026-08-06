"""Validated deployment settings and hardened runtime file/process helpers."""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def model_credential_environment() -> dict[str, str]:
    values = {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", ""),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "AWS_SESSION_TOKEN": os.environ.get("AWS_SESSION_TOKEN", ""),
        "AZURE_API_KEY": os.environ.get("AZURE_API_KEY", ""),
        "AZURE_OPENAI_API_KEY": os.environ.get("AZURE_OPENAI_API_KEY", ""),
        "COHERE_API_KEY": os.environ.get("COHERE_API_KEY", ""),
        "DATABRICKS_API_TOKEN": os.environ.get("DATABRICKS_API_TOKEN", ""),
        "DEEPINFRA_API_KEY": os.environ.get("DEEPINFRA_API_KEY", ""),
        "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", ""),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", ""),
        "GOOGLE_APPLICATION_CREDENTIALS": os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS", ""
        ),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", ""),
        "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
        "REPLICATE_API_TOKEN": os.environ.get("REPLICATE_API_TOKEN", ""),
        "TOGETHERAI_API_KEY": os.environ.get("TOGETHERAI_API_KEY", ""),
        "VERTEXAI_CREDENTIALS": os.environ.get("VERTEXAI_CREDENTIALS", ""),
        "WATSONX_APIKEY": os.environ.get("WATSONX_APIKEY", ""),
        "XAI_API_KEY": os.environ.get("XAI_API_KEY", ""),
    }
    return {name: value for name, value in values.items() if value}


def model_context_environment() -> dict[str, str]:
    values = {
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", ""),
        "AWS_REGION": os.environ.get("AWS_REGION", ""),
        "AZURE_API_BASE": os.environ.get("AZURE_API_BASE", ""),
        "AZURE_API_VERSION": os.environ.get("AZURE_API_VERSION", ""),
        "LLM_API_BASE": os.environ.get("LLM_API_BASE", ""),
        "OLLAMA_HOST": os.environ.get("OLLAMA_HOST", ""),
        "VERTEXAI_LOCATION": os.environ.get("VERTEXAI_LOCATION", ""),
        "VERTEXAI_PROJECT": os.environ.get("VERTEXAI_PROJECT", ""),
    }
    return {name: value for name, value in values.items() if value}


class ServiceError(RuntimeError):
    pass


class ResourcePolicyError(ServiceError):
    pass


@dataclass(frozen=True)
class QuotaPolicy:
    max_active_runs: int = 16
    max_nodes_per_run: int = 1_000
    max_total_nodes: int = 10_000
    max_descendant_runs: int = 1_000
    max_cost_usd: float = 10_000.0
    max_cpus: int = 256
    max_timeout_minutes: int = 2_880

    def __post_init__(self) -> None:
        positive = {
            "max_active_runs": self.max_active_runs,
            "max_nodes_per_run": self.max_nodes_per_run,
            "max_total_nodes": self.max_total_nodes,
            "max_cpus": self.max_cpus,
            "max_timeout_minutes": self.max_timeout_minutes,
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in positive.values()
        ):
            raise ResourcePolicyError(
                "positive deployment quotas must be integers >= 1"
            )
        if (
            not isinstance(self.max_descendant_runs, int)
            or isinstance(self.max_descendant_runs, bool)
            or self.max_descendant_runs < 0
        ):
            raise ResourcePolicyError(
                "max_descendant_runs must be a non-negative integer"
            )
        if (
            not isinstance(self.max_cost_usd, (int, float))
            or isinstance(self.max_cost_usd, bool)
            or not math.isfinite(self.max_cost_usd)
            or self.max_cost_usd < 0
        ):
            raise ResourcePolicyError("max_cost_usd must be finite and non-negative")

    @classmethod
    def from_environment(cls) -> "QuotaPolicy":
        return cls(
            max_active_runs=_positive_env("ARI_ORCHESTRATOR_MAX_ACTIVE_RUNS", 16),
            max_nodes_per_run=_positive_env(
                "ARI_ORCHESTRATOR_MAX_NODES_PER_RUN", 1_000
            ),
            max_total_nodes=_positive_env("ARI_ORCHESTRATOR_MAX_TOTAL_NODES", 10_000),
            max_descendant_runs=_nonnegative_env(
                "ARI_ORCHESTRATOR_MAX_DESCENDANT_RUNS", 1_000
            ),
            max_cost_usd=_nonnegative_float_env(
                "ARI_ORCHESTRATOR_MAX_COST_USD", 10_000.0
            ),
            max_cpus=_positive_env("ARI_ORCHESTRATOR_MAX_CPUS", 256),
            max_timeout_minutes=_positive_env(
                "ARI_ORCHESTRATOR_MAX_TIMEOUT_MINUTES", 2_880
            ),
        )


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ResourcePolicyError(f"{name} must be an integer") from exc
    if value < 1:
        raise ResourcePolicyError(f"{name} must be positive")
    return value


def _nonnegative_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ResourcePolicyError(f"{name} must be an integer") from exc
    if value < 0:
        raise ResourcePolicyError(f"{name} must be non-negative")
    return value


def _nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ResourcePolicyError(f"{name} must be numeric") from exc
    if value < 0 or not math.isfinite(value):
        raise ResourcePolicyError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True)
class ServiceConfig:
    workspace: Path
    logs_root: Path
    ari_cli: str
    dry_run: bool = False
    cancellation_grace_seconds: float = 5.0
    quota: QuotaPolicy = QuotaPolicy()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.cancellation_grace_seconds, (int, float))
            or isinstance(self.cancellation_grace_seconds, bool)
            or not math.isfinite(self.cancellation_grace_seconds)
            or self.cancellation_grace_seconds < 0
            or self.cancellation_grace_seconds > 60
        ):
            raise ResourcePolicyError(
                "cancellation grace must be between 0 and 60 seconds"
            )

    @classmethod
    def from_environment(cls) -> "ServiceConfig":
        repository = Path(__file__).resolve().parents[3]
        workspace = Path(os.environ.get("ARI_WORKSPACE", str(repository))).resolve()
        logs_root = Path(
            os.environ.get("ARI_ORCHESTRATOR_LOGS", str(workspace / "logs"))
        ).resolve()
        local_cli = workspace / "ari-core" / ".venv" / "bin" / "ari"
        discovered_cli = shutil.which("ari")
        cli = str(local_cli) if local_cli.is_file() else (discovered_cli or "ari")
        try:
            grace = float(os.environ.get("ARI_ORCHESTRATOR_CANCEL_GRACE_SECONDS", "5"))
        except ValueError as exc:
            raise ResourcePolicyError(
                "ARI_ORCHESTRATOR_CANCEL_GRACE_SECONDS must be numeric"
            ) from exc
        return cls(
            workspace=workspace,
            logs_root=logs_root,
            ari_cli=cli,
            dry_run=os.environ.get("ARI_ORCHESTRATOR_DRY_RUN", "") == "1",
            cancellation_grace_seconds=grace,
            quota=QuotaPolicy.from_environment(),
        )


def atomic_bytes(path: Path, payload: bytes) -> None:
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary = f".{path.name}.{secrets.token_hex(12)}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(
            temporary,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except Exception:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(directory_fd)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    atomic_bytes(path, rendered.encode("utf-8"))


def atomic_text(path: Path, value: str) -> None:
    atomic_bytes(path, value.encode("utf-8"))


def safe_bytes_file(path: Path, *, max_bytes: int) -> bytes | None:
    try:
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
        finally:
            os.close(directory_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                return None
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return None
    payload = b"".join(chunks)
    if (
        len(payload) > max_bytes
        or len(payload) != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        return None
    return payload


def process_start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw[raw.rfind(")") + 2 :].split()
        return int(tail[19])
    except (OSError, ValueError, IndexError):
        return None


def process_matches(pid: int | None, expected_ticks: int | None) -> bool:
    if pid is None or expected_ticks is None:
        return False
    return process_start_ticks(pid) == expected_ticks


def safe_json_file(
    path: Path, *, max_bytes: int = 4 * 1024 * 1024
) -> dict[str, Any] | None:
    try:
        payload = safe_bytes_file(path, max_bytes=max_bytes)
        if payload is None:
            return None
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "QuotaPolicy",
    "ResourcePolicyError",
    "ServiceConfig",
    "ServiceError",
    "atomic_json",
    "atomic_text",
    "model_context_environment",
    "model_credential_environment",
    "process_matches",
    "process_start_ticks",
    "safe_bytes_file",
    "safe_json_file",
]
