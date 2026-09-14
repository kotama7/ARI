"""Content-addressed visual target resolution with bounded image decoding."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ari.public.execution import WorkspaceRefV1
from ari.public.figures import FigureBatchV1, FigureManifestV1, parse_figure_batch
from ari.public.visual_review import VisualArtifactRefV1


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8_192
MAX_IMAGE_PIXELS = 40_000_000
MAX_METADATA_BYTES = 64 * 1024
_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class VisualTargetError(ValueError):
    def __init__(self, kind: str, message: str, artifact: VisualArtifactRefV1):
        super().__init__(message)
        self.kind = kind
        self.artifact = artifact


@dataclass(frozen=True)
class ResolvedFigureTarget:
    workspace: WorkspaceRefV1
    batch: FigureBatchV1
    manifest: FigureManifestV1
    artifact: VisualArtifactRefV1
    payload: bytes
    media_type: str
    width: int
    height: int


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def manifest_visual_artifact(manifest: FigureManifestV1) -> VisualArtifactRefV1:
    png = next(item for item in manifest.artifacts if item.role == "png")
    return VisualArtifactRefV1(
        role="review-target",
        relative_path=png.relative_path,
        digest=png.digest,
        media_type=png.media_type,
        size_bytes=png.size_bytes,
    )


def _verify_image(
    workspace: WorkspaceRefV1,
    artifact: VisualArtifactRefV1,
) -> tuple[bytes, str, int, int]:
    if artifact.size_bytes > MAX_IMAGE_BYTES:
        raise VisualTargetError("image-too-large", "image exceeds 20 MiB", artifact)
    try:
        payload = workspace.read_bytes(
            artifact.relative_path,
            max_bytes=MAX_IMAGE_BYTES,
        )
    except Exception as exc:
        raise VisualTargetError("artifact-unavailable", str(exc), artifact) from exc
    if len(payload) != artifact.size_bytes or _digest(payload) != artifact.digest:
        raise VisualTargetError(
            "artifact-digest-mismatch",
            "figure image bytes do not match the manifest",
            artifact,
        )
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        with Image.open(io.BytesIO(payload)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            metadata_size = sum(
                len(str(key).encode("utf-8")) + len(str(value).encode("utf-8"))
                for key, value in image.info.items()
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VisualTargetError("corrupt-image", "image decoding failed", artifact) from exc
    if image_format not in _FORMATS:
        raise VisualTargetError("unsupported-image", "image format is unsupported", artifact)
    if (
        width < 1
        or height < 1
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise VisualTargetError("image-dimensions", "image dimensions exceed policy", artifact)
    if metadata_size > MAX_METADATA_BYTES:
        raise VisualTargetError("image-metadata", "image metadata exceeds policy", artifact)
    return payload, _FORMATS[image_format], width, height


def load_figure_batch(path: str) -> tuple[WorkspaceRefV1, FigureBatchV1]:
    manifest_path = Path(path)
    if not manifest_path.is_absolute() or not manifest_path.is_file():
        raise ValueError("figures_manifest_path must name an existing absolute file")
    if manifest_path.is_symlink():
        raise ValueError("figures manifest cannot be a symlink")
    workspace = WorkspaceRefV1(root=str(manifest_path.parent))
    payload = workspace.read_bytes(manifest_path.name, max_bytes=16 * 1024 * 1024)
    return workspace, parse_figure_batch(payload.decode("utf-8"))


def resolve_figure_target(
    workspace: WorkspaceRefV1,
    batch: FigureBatchV1,
    figure_id: str,
) -> ResolvedFigureTarget:
    manifest = next(
        (item for item in batch.manifests if item.spec.figure_id == figure_id),
        None,
    )
    if manifest is None:
        raise ValueError(f"figure batch has no figure_id {figure_id!r}")
    artifact = manifest_visual_artifact(manifest)
    payload, media_type, width, height = _verify_image(workspace, artifact)
    return ResolvedFigureTarget(
        workspace=workspace,
        batch=batch,
        manifest=manifest,
        artifact=artifact,
        payload=payload,
        media_type=media_type,
        width=width,
        height=height,
    )


__all__ = [
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "ResolvedFigureTarget",
    "VisualTargetError",
    "load_figure_batch",
    "manifest_visual_artifact",
    "resolve_figure_target",
]
