"""Deprecated Singularity aliases backed by the public scheduler contract."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import Any

from ari_skill_hpc.contracts import (
    ArtifactPinV1,
    BindMountV1,
    ContainerRequestV1,
    EnvironmentPolicyV1,
    JobRequestV1,
    OutputDeclarationV1,
    ResourceRequestV1,
    file_digest,
)
from ari_skill_hpc.scheduler import SchedulerError, SchedulerValidationError
from ari_skill_hpc.slurm import SlurmClient


def _handle_response(handle: Any, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": handle.schema_version,
        "handle_id": handle.handle_id,
        "job_id": handle.job_id,
        "state": handle.state,
        "status": handle.status,
        "request_digest": handle.request_digest,
        **extra,
    }


def _error(exc: Exception, **extra: Any) -> dict[str, Any]:
    return {"job_id": "", "status": "error", "message": str(exc), **extra}


def _absolute(value: str, *, field: str) -> Path:
    path = Path(value).expanduser()
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(character.isspace() for character in str(path))
        or any(character in str(path) for character in "\x00\n\r")
    ):
        raise SchedulerValidationError(f"{field} must be an inert absolute path")
    return path


def _resource(arguments: dict[str, Any], *, walltime: str) -> ResourceRequestV1:
    gres = str(arguments.get("gres") or "")
    gpus = 0
    gpu_type = None
    if gres:
        match = re.fullmatch(r"gpu(?::([A-Za-z0-9_.+-]+))?:(\d+)", gres)
        if not match:
            raise SchedulerValidationError("gres must use gpu[:type]:count")
        gpu_type = match.group(1)
        gpus = int(match.group(2))
    return ResourceRequestV1(
        partition=str(arguments.get("partition") or "default"),
        nodes=int(arguments.get("nodes") or 1),
        cpus_per_task=int(arguments.get("cpus_per_task") or 1),
        gpus_per_node=gpus,
        gpu_type=gpu_type,
        walltime=str(arguments.get("walltime") or walltime),
    )


def _request_id(prefix: str, value: bytes) -> str:
    return prefix + "-" + hashlib.sha256(value).hexdigest()[:32]


def _definition_pin(content: str, root: Path) -> ArtifactPinV1:
    raw = content.encode("utf-8")
    if not raw or len(raw) > 4 * 1024 * 1024 or b"\x00" in raw:
        raise SchedulerValidationError("container definition is empty or too large")
    digest = hashlib.sha256(raw).hexdigest()
    hpc_root = root / ".ari-hpc"
    if hpc_root.exists() and hpc_root.is_symlink():
        raise SchedulerValidationError(".ari-hpc must not be a symlink")
    definitions = hpc_root / "definitions"
    definitions.mkdir(parents=True, exist_ok=True, mode=0o700)
    if definitions.is_symlink():
        raise SchedulerValidationError("container definition scope is unsafe")
    path = definitions / f"{digest}.def"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise SchedulerValidationError("container definition digest collision")
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=definitions)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return ArtifactPinV1(
        logical_name="container-definition",
        path=str(path),
        digest="sha256:" + digest,
        size_bytes=len(raw),
        media_type="text/plain",
    )


async def build(client: SlurmClient, arguments: dict[str, Any]) -> dict[str, Any]:
    output = _absolute(str(arguments["output_path"]), field="output_path")
    work_dir = output.parent
    try:
        definition = _definition_pin(str(arguments["definition_file"]), work_dir)
        request = JobRequestV1(
            request_id=_request_id("singularity-build", definition.digest.encode()),
            job_name="singularity-build",
            work_dir=str(work_dir),
            argv=("singularity", "build", str(output), definition.path),
            resources=_resource(arguments, walltime="02:00:00"),
            inputs=(definition,),
            outputs=(
                OutputDeclarationV1(
                    logical_name="container-image",
                    path=str(output),
                    max_bytes=1_099_511_627_776,
                    media_type="application/vnd.sylabs.sif.layer.v1.sif",
                ),
            ),
            metadata={"deprecated_alias": "singularity_build"},
        )
        handle = await client.scheduler.submit(request)
    except (SchedulerError, ValueError, OSError) as exc:
        return _error(exc, output_path=str(output))
    return _handle_response(handle, output_path=str(output))


async def build_fakeroot(
    client: SlurmClient, arguments: dict[str, Any]
) -> dict[str, Any]:
    output = _absolute(str(arguments["output_path"]), field="output_path")
    work_dir = output.parent
    try:
        definition = _definition_pin(str(arguments["definition_content"]), work_dir)
        request = JobRequestV1(
            request_id=_request_id("singularity-fakeroot", definition.digest.encode()),
            job_name="singularity-fakeroot",
            work_dir=str(work_dir),
            argv=("singularity", "build", "--fakeroot", str(output), definition.path),
            resources=_resource(arguments, walltime="02:00:00"),
            inputs=(definition,),
            outputs=(
                OutputDeclarationV1(
                    logical_name="container-image",
                    path=str(output),
                    max_bytes=1_099_511_627_776,
                    media_type="application/vnd.sylabs.sif.layer.v1.sif",
                ),
            ),
            metadata={"deprecated_alias": "singularity_build_fakeroot"},
        )
        handle = await client.scheduler.submit(request)
    except (SchedulerError, ValueError, OSError) as exc:
        return _error(exc, output_path=str(output))
    return _handle_response(handle, output_path=str(output))


async def pull(client: SlurmClient, arguments: dict[str, Any]) -> dict[str, Any]:
    output = _absolute(str(arguments["output_path"]), field="output_path")
    source = str(arguments["source"])
    if (
        not source
        or len(source) > 4096
        or not re.fullmatch(
            r"(?:docker|library|oras|https?)://[A-Za-z0-9._/@:+-]+", source
        )
        or re.search(r"://[^/]*:[^/@]+@", source)
    ):
        return _error(SchedulerValidationError("container source URI is invalid"))
    try:
        request = JobRequestV1(
            request_id=_request_id("singularity-pull", source.encode()),
            job_name="singularity-pull",
            work_dir=str(output.parent),
            argv=("singularity", "pull", "--force", str(output), source),
            resources=_resource(arguments, walltime="01:00:00"),
            outputs=(
                OutputDeclarationV1(
                    logical_name="container-image",
                    path=str(output),
                    max_bytes=1_099_511_627_776,
                    media_type="application/vnd.sylabs.sif.layer.v1.sif",
                ),
            ),
            metadata={"deprecated_alias": "singularity_pull", "source": source},
        )
        handle = await client.scheduler.submit(request)
    except (SchedulerError, ValueError, OSError) as exc:
        return _error(exc, output_path=str(output), source=source)
    return _handle_response(handle, output_path=str(output), source=source)


def _image_pin(path: Path) -> ArtifactPinV1:
    if not path.is_file() or path.is_symlink():
        raise SchedulerValidationError(
            "container image must be a regular non-symlink file"
        )
    info = path.stat()
    return ArtifactPinV1(
        logical_name="container-image",
        path=str(path),
        digest=file_digest(path),
        size_bytes=info.st_size,
        media_type="application/vnd.sylabs.sif.layer.v1.sif",
    )


def _binds(values: list[str]) -> tuple[BindMountV1, ...]:
    output: list[BindMountV1] = []
    for value in values:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            raise SchedulerValidationError("bind paths must use source:target[:ro|rw]")
        read_only = len(parts) == 2 or parts[2] == "ro"
        if len(parts) == 3 and parts[2] not in {"ro", "rw"}:
            raise SchedulerValidationError("bind mode must be ro or rw")
        output.append(
            BindMountV1(source=parts[0], target=parts[1], read_only=read_only)
        )
    return tuple(output)


async def _run_container(
    client: SlurmClient, arguments: dict[str, Any], *, gpu: bool, alias: str
) -> dict[str, Any]:
    try:
        image_path = _absolute(str(arguments["image_path"]), field="image_path")
        work_dir = _absolute(
            str(arguments.get("work_dir") or os.getcwd()), field="work_dir"
        )
        argv = tuple(shlex.split(str(arguments["command"])))
        if not argv:
            raise SchedulerValidationError("container command is empty")
        image = _image_pin(image_path)
        bind_values = [str(value) for value in arguments.get("bind_paths", [])]
        container = ContainerRequestV1(
            runtime="singularity",
            image=image,
            binds=_binds(bind_values),
            gpu=gpu,
        )
        request = JobRequestV1(
            request_id=_request_id(alias, repr((image.digest, argv)).encode()),
            job_name="singularity-gpu" if gpu else "singularity-run",
            work_dir=str(work_dir),
            argv=argv,
            resources=_resource(arguments, walltime="01:00:00"),
            environment=EnvironmentPolicyV1(),
            container=container,
            inputs=(image,),
            metadata={"deprecated_alias": alias},
        )
        handle = await client.scheduler.submit(request)
    except (SchedulerError, ValueError, OSError) as exc:
        return _error(exc)
    return _handle_response(handle)


async def run(client: SlurmClient, arguments: dict[str, Any]) -> dict[str, Any]:
    return await _run_container(client, arguments, gpu=False, alias="singularity_run")


async def run_gpu(client: SlurmClient, arguments: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(arguments)
    enriched.setdefault("gres", "gpu:1")
    enriched.setdefault("cpus_per_task", 8)
    return await _run_container(client, enriched, gpu=True, alias="singularity_run_gpu")
