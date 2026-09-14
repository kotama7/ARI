"""Private workspace, batch identity, and artifact handling for OpenROAD HPC."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from ari.public.result import ResultArtifactV1
from ari_skill_hpc import (
    ArtifactPinV1,
    JobRequestV1,
    JobResultV1,
    OutputDeclarationV1,
)

from models import sha256_digest
from providers import ProviderProtocolError


_BATCH_WORKER = Path(__file__).resolve().with_name("openroad_worker.py")
_SAFE_METRICS_PATH = re.compile(r"[A-Za-z0-9_./:+%=,@-]+")


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProviderProtocolError(f"cannot hash OpenROAD HPC file: {exc}") from exc
    return "sha256:" + digest.hexdigest()


def workspace_runtime_digest() -> str:
    return sha256_digest(
        {
            "workspace_source": _digest_file(Path(__file__).resolve()),
            "batch_worker": _digest_file(_BATCH_WORKER),
        }
    )


def openroad_batch_tcl(profile: Any) -> str:
    """Compile commands plus a trusted, explicit metrics sink lifecycle."""

    metric_sources = sorted({metric.source_artifact for metric in profile.metrics})
    if len(metric_sources) != 1 or not _SAFE_METRICS_PATH.fullmatch(
        metric_sources[0]
    ):
        raise ProviderProtocolError(
            "OpenROAD batch execution requires one inert metrics artifact path"
        )
    metrics_path = metric_sources[0]
    lines = [
        f"utl::open_metrics {{{metrics_path}}}",
        *(command.text for command in profile.commands),
        f"utl::close_metrics {{{metrics_path}}}",
    ]
    return "\n".join(lines) + "\n"


def verify_openroad_hpc_files(execution: Any) -> None:
    """Verify host-visible container and shared-work identities before admission."""

    if execution.backend != "slurm":
        return
    if execution.work_root is None:
        raise ProviderProtocolError("OpenROAD scheduler execution is incomplete")
    if execution.container is not None:
        pins = (execution.container.image,)
    elif execution.portable_runtime is not None:
        if execution.worker_python_pin is None:
            raise ProviderProtocolError("OpenROAD portable worker pin is missing")
        pins = (
            execution.portable_runtime.proot,
            execution.portable_runtime.image,
            execution.portable_runtime.unsquashfs,
            execution.worker_python_pin,
        )
    else:
        raise ProviderProtocolError("OpenROAD scheduler substrate is missing")
    for pin in pins:
        path = Path(pin.path)
        if path.is_symlink() or not path.is_file():
            raise ProviderProtocolError(
                f"OpenROAD runtime artifact {pin.logical_name} must be a regular non-symlink"
            )
        if path.stat().st_size != pin.size_bytes or _digest_file(path) != pin.digest:
            raise ProviderProtocolError(
                f"OpenROAD runtime artifact {pin.logical_name} digest drifted"
            )
    work_root = Path(execution.work_root)
    if work_root.is_symlink() or not work_root.is_dir():
        raise ProviderProtocolError(
            "OpenROAD scheduler work_root must be an existing non-symlink directory"
        )
    if not _BATCH_WORKER.is_file() or _BATCH_WORKER.is_symlink():
        raise ProviderProtocolError("OpenROAD batch worker is unavailable")


class OpenRoadHpcWorkspace:
    """Build and reap a private typed-job workspace."""

    def __init__(self, artifact_store: Any | None) -> None:
        self.artifact_store = artifact_store

    @staticmethod
    def _write_private_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    def prepare_request(
        self, results: Any, job: Any
    ) -> tuple[JobRequestV1, frozenset[str]]:
        profile = job.experiment
        execution = profile.execution
        if (
            execution.backend != "slurm"
            or execution.work_root is None
            or execution.resources is None
            or (execution.container is None and execution.portable_runtime is None)
        ):
            raise ProviderProtocolError("OpenROAD batch execution is incomplete")
        root = Path(execution.work_root)
        if (
            root.is_symlink()
            or not root.is_dir()
            or root.resolve(strict=True) != root
        ):
            raise ProviderProtocolError(
                "OpenROAD scheduler work_root must be an existing canonical directory"
            )
        suffix = job.handle_id.removeprefix("openroad-")[:32]
        workspace = root / f"ari-openroad-{profile.profile_id}-{suffix}"
        if workspace.exists() or workspace.is_symlink():
            raise ProviderProtocolError(
                "OpenROAD batch workspace already exists; restart recovery is fail-closed"
            )
        workspace.mkdir(mode=0o700)
        job.batch_workspace = workspace
        results.copy_inputs(profile, workspace)
        for output in profile.output_artifacts:
            (workspace / output.relative_path).parent.mkdir(
                mode=0o700, parents=True, exist_ok=True
            )

        worker_path = workspace / "ari-openroad-worker.py"
        shutil.copyfile(_BATCH_WORKER, worker_path)
        worker_path.chmod(0o600)
        tcl_path = workspace / "ari-openroad-flow.tcl"
        tcl_path.write_text(
            openroad_batch_tcl(profile),
            encoding="utf-8",
        )
        tcl_path.chmod(0o600)
        metrics_path = workspace / sorted(
            {metric.source_artifact for metric in profile.metrics}
        )[0]
        result_path = workspace / "ari-openroad-batch-result.json"
        spec_path = workspace / "ari-openroad-batch-spec.json"
        self._write_private_json(
            spec_path,
            {
                "schema_version": "ari.openroad-batch-spec/v1",
                "experiment_digest": profile.experiment_digest,
                "work_dir": str(workspace),
                "executable_path": profile.toolchain.executable_path,
                "executable_digest": profile.toolchain.executable_digest,
                "architecture": profile.toolchain.architecture,
                "tcl_path": str(tcl_path),
                "tcl_digest": _digest_file(tcl_path),
                "metrics_path": str(metrics_path),
                "portable_runtime": (
                    execution.portable_runtime.model_dump(mode="json")
                    if execution.portable_runtime is not None
                    else None
                ),
                "result_path": str(result_path),
            },
        )

        inputs: list[ArtifactPinV1] = []
        for index, artifact in enumerate(profile.workspace.input_artifacts):
            path = workspace / artifact.relative_path
            inputs.append(
                ArtifactPinV1(
                    logical_name=f"openroad-input-{index:04d}",
                    path=str(path),
                    digest=artifact.digest,
                    size_bytes=path.stat().st_size,
                    media_type=artifact.media_type,
                )
            )
        for logical_name, path, media_type in (
            ("openroad-batch-worker", worker_path, "text/x-python"),
            ("openroad-batch-tcl", tcl_path, "text/x-tcl"),
            ("openroad-batch-spec", spec_path, "application/json"),
        ):
            inputs.append(
                ArtifactPinV1(
                    logical_name=logical_name,
                    path=str(path),
                    digest=_digest_file(path),
                    size_bytes=path.stat().st_size,
                    media_type=media_type,
                )
            )
        if execution.portable_runtime is not None:
            inputs.extend(
                (
                    execution.portable_runtime.proot,
                    execution.portable_runtime.image,
                    execution.portable_runtime.unsquashfs,
                )
            )
            assert execution.worker_python_pin is not None
            inputs.append(execution.worker_python_pin)
        outputs = [
            OutputDeclarationV1(
                logical_name=f"openroad-output-{index:04d}",
                path=str(workspace / output.relative_path),
                required=False,
                max_bytes=output.max_bytes,
                media_type=output.media_type,
            )
            for index, output in enumerate(profile.output_artifacts)
        ]
        outputs.append(
            OutputDeclarationV1(
                logical_name="openroad-batch-result",
                path=str(result_path),
                required=True,
                max_bytes=2_000_000,
                media_type="application/json",
            )
        )
        request_id = (
            "openroad-job-"
            + sha256_digest(
                {
                    "handle_id": job.handle_id,
                    "experiment_digest": profile.experiment_digest,
                }
            ).removeprefix("sha256:")[:24]
        )
        request = JobRequestV1(
            request_id=request_id,
            job_name=("openroad-" + profile.profile_id)[:128],
            work_dir=str(workspace),
            argv=(execution.worker_python, str(worker_path), str(spec_path)),
            resources=execution.resources,
            environment=execution.environment,
            container=execution.container,
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            metadata={
                "domain": "openroad",
                "profile_id": profile.profile_id,
                "experiment_digest": profile.experiment_digest,
            },
        )
        return request, frozenset(
            {worker_path.name, tcl_path.name, spec_path.name, result_path.name}
        )

    @staticmethod
    def batch_result(path: Path, profile: Any) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ProviderProtocolError("OpenROAD batch result is missing or unsafe")
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError(
                f"OpenROAD batch result is invalid JSON: {exc}"
            ) from exc
        expected_keys = {
            "schema_version",
            "experiment_digest",
            "started_at",
            "completed_at",
            "architecture",
            "executable_digest",
            "tcl_digest",
            "return_code",
            "error",
            "metrics_materialization",
        }
        if not isinstance(result, dict) or set(result) != expected_keys:
            raise ProviderProtocolError("OpenROAD batch result shape drifted")
        expected_tcl_digest = "sha256:" + hashlib.sha256(
            openroad_batch_tcl(profile).encode("utf-8")
        ).hexdigest()
        identity_matches = (
            result["schema_version"] == "ari.openroad-batch-result/v1"
            and result["experiment_digest"] == profile.experiment_digest
            and result["architecture"] == profile.toolchain.architecture
            and result["executable_digest"] == profile.toolchain.executable_digest
            and result["tcl_digest"] == expected_tcl_digest
            and result["metrics_materialization"]
            in {"direct-workspace", "portable-rootfs-export"}
        )
        if not identity_matches or result["return_code"] != 0 or result["error"] is not None:
            raise ProviderProtocolError(
                "OpenROAD batch worker reported an identity or execution failure"
            )
        return result

    def store_hpc_artifacts(
        self, result: JobResultV1
    ) -> tuple[list[dict[str, Any]], list[ResultArtifactV1]]:
        metadata: list[dict[str, Any]] = []
        refs: list[ResultArtifactV1] = []
        values: list[tuple[str, str, int, str, str]] = []
        for item in result.provenance:
            values.append(
                (
                    item.path,
                    item.digest,
                    item.size_bytes,
                    item.media_type,
                    f"openroad-hpc-{item.logical_name}",
                )
            )
        for item in result.logs:
            metadata.append(item.model_dump(mode="json", exclude={"text"}))
            if item.digest is not None and item.size_bytes is not None:
                values.append(
                    (
                        item.path,
                        item.digest,
                        item.size_bytes,
                        "text/plain",
                        f"openroad-scheduler-{item.stream}",
                    )
                )
        for path_text, digest, size, media_type, role in values:
            path = Path(path_text)
            item_meta = {
                "path": path_text,
                "digest": digest,
                "size": size,
                "media_type": media_type,
                "logical_role": role,
                "captured": False,
            }
            if (
                self.artifact_store is not None
                and path.is_file()
                and not path.is_symlink()
                and path.stat().st_size == size
                and _digest_file(path) == digest
            ):
                hexadecimal = digest.removeprefix("sha256:")
                suffix = path.suffix or ".bin"
                logical_name = (
                    f"openroad/sha256/{hexadecimal[:2]}/{hexadecimal}{suffix}"
                )
                self.artifact_store.put(logical_name, path)
                refs.append(
                    ResultArtifactV1(
                        digest=digest,
                        media_type=media_type,
                        size=size,
                        logical_role=role,
                        logical_name=logical_name,
                    )
                )
                item_meta.update({"captured": True, "logical_name": logical_name})
            metadata.append(item_meta)
        return metadata, refs

    @staticmethod
    def cleanup_workspace(job: Any) -> None:
        workspace = job.batch_workspace
        execution = job.experiment.execution
        if workspace is None or execution.work_root is None or not workspace.exists():
            return
        root = Path(execution.work_root).resolve(strict=True)
        if workspace.is_symlink() or workspace.parent.resolve(strict=True) != root:
            raise ProviderProtocolError("refusing unsafe OpenROAD workspace cleanup")
        shutil.rmtree(workspace)
        job.batch_workspace = None


__all__ = [
    "OpenRoadHpcWorkspace",
    "_digest_file",
    "openroad_batch_tcl",
    "verify_openroad_hpc_files",
    "workspace_runtime_digest",
]
