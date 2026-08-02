"""Fixed renderer for declarative scientific figure specifications."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ari.public.execution import WorkspaceRefV1
from ari.public.figures import (
    FigureArtifactV1,
    FigureBatchV1,
    FigureEnvironmentV1,
    FigureFeedbackV1,
    FigureManifestV1,
    FigureSpecV1,
)


RENDERER_VERSION = "ari.figure-renderer/v1"


def bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _artifact(
    *,
    role: str,
    path: str,
    payload: bytes,
    media_type: str,
) -> FigureArtifactV1:
    return FigureArtifactV1(
        role=role,
        relative_path=path,
        digest=bytes_digest(payload),
        media_type=media_type,
        size_bytes=len(payload),
    )


def _numeric_vector(value: Any, field: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"figure {field} must be a non-empty array")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"figure {field} values must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"figure {field} values must be finite")
        result.append(number)
    return result


def _x_vector(value: Any, length: int) -> list[str | int | float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError("figure x and y fields must have the same length")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (str, int, float))
        or (isinstance(item, float) and not math.isfinite(item))
        for item in value
    ):
        raise ValueError("figure x values must be finite strings or numbers")
    return list(value)


def _axis_label(label: str, unit: str) -> str:
    return label if unit == "1" else f"{label} [{unit}]"


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _render_bytes(spec: FigureSpecV1) -> tuple[bytes, bytes, FigureEnvironmentV1]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as font_manager
    import matplotlib.pyplot as plt

    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.grid": spec.chart_type != "heatmap",
            "axes.axisbelow": True,
            "figure.dpi": 100,
            "savefig.dpi": 150,
            "svg.hashsalt": RENDERER_VERSION,
        }
    ):
        fig, ax = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
        if spec.chart_type == "heatmap":
            raw = spec.data[spec.y_field]
            if not isinstance(raw, list) or not raw or not all(
                isinstance(row, list) and row for row in raw
            ):
                raise ValueError("heatmap values must be a non-empty matrix")
            width = len(raw[0])
            if any(len(row) != width for row in raw):
                raise ValueError("heatmap rows must have equal lengths")
            values = [_numeric_vector(row, spec.y_field) for row in raw]
            image = ax.imshow(values, aspect="auto", interpolation="nearest")
            colorbar = fig.colorbar(image, ax=ax)
            colorbar.set_label(_axis_label(spec.y_axis.label, spec.value_unit))
        elif spec.chart_type == "hist":
            y = _numeric_vector(spec.data[spec.y_field], spec.y_field)
            bins = min(20, max(1, int(math.sqrt(len(y)))))
            ax.hist(y, bins=bins)
        else:
            y = _numeric_vector(spec.data[spec.y_field], spec.y_field)
            assert spec.x_field is not None
            x = _x_vector(spec.data[spec.x_field], len(y))
            if spec.chart_type == "bar":
                ax.bar(x, y)
            elif spec.chart_type == "line":
                ax.plot(x, y, marker="o")
            elif spec.chart_type == "scatter":
                ax.scatter(x, y)
            elif spec.chart_type == "errorbar":
                assert spec.uncertainty.field is not None
                yerr = _numeric_vector(
                    spec.data[spec.uncertainty.field], spec.uncertainty.field
                )
                if len(yerr) != len(y):
                    raise ValueError("uncertainty and measurement arrays must match")
                ax.errorbar(x, y, yerr=yerr, marker="o", capsize=3)

        if spec.title:
            ax.set_title(spec.title)
        if spec.chart_type == "hist":
            ax.set_xlabel(_axis_label(spec.x_axis.label, spec.x_axis.unit))
            ax.set_ylabel(_axis_label(spec.y_axis.label, spec.y_axis.unit))
        elif spec.chart_type != "heatmap":
            ax.set_xlabel(_axis_label(spec.x_axis.label, spec.x_axis.unit))
            ax.set_ylabel(_axis_label(spec.y_axis.label, spec.y_axis.unit))
        if spec.x_axis.scale != "linear" and spec.chart_type != "heatmap":
            ax.set_xscale(spec.x_axis.scale)
        if spec.y_axis.scale != "linear" and spec.chart_type != "heatmap":
            ax.set_yscale(spec.y_axis.scale)

        png = io.BytesIO()
        pdf = io.BytesIO()
        fig.savefig(
            png,
            format="png",
            dpi=150,
            metadata={"Software": f"ARI matplotlib {matplotlib.__version__}"},
        )
        fixed_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
        fig.savefig(
            pdf,
            format="pdf",
            metadata={
                "Creator": "ARI deterministic figure renderer",
                "Producer": f"matplotlib {matplotlib.__version__}",
                "CreationDate": fixed_time,
                "ModDate": fixed_time,
            },
        )
        plt.close(fig)

    font_path = Path(font_manager.findfont("DejaVu Sans", fallback_to_default=False))
    font_payload = font_path.read_bytes()
    container_digest = os.environ.get("ARI_CONTAINER_DIGEST") or None
    environment = FigureEnvironmentV1.create(
        renderer_version=RENDERER_VERSION,
        python_version=sys.version.split()[0],
        matplotlib_version=matplotlib.__version__,
        backend="agg",
        font_family="DejaVu Sans",
        font_digest=bytes_digest(font_payload),
        platform=platform.platform(),
        container_digest=container_digest,
    )
    return png.getvalue(), pdf.getvalue(), environment


def render_spec(
    spec: FigureSpecV1,
    *,
    workspace: WorkspaceRefV1,
    relative_directory: str = "figures",
    planner_model: str | None = None,
    planner_model_revision: str | None = None,
    prompt_payload: bytes | None = None,
    raw_response_payload: bytes | None = None,
    sampling: dict[str, Any] | None = None,
    feedback: FigureFeedbackV1 | None = None,
    parent_manifest_digest: str | None = None,
) -> FigureManifestV1:
    """Render a validated spec and atomically materialize every source artifact."""

    revision_dir = f"{relative_directory}/revisions/{spec.revision:02d}/{spec.figure_id}"
    workspace.ensure_directory(revision_dir)
    source_payload = json_bytes(spec.data)
    spec_payload = json_bytes(spec.model_dump(mode="json"))
    png_payload, pdf_payload, environment = _render_bytes(spec)
    paths = {
        "source-data": f"{revision_dir}/source_data.json",
        "spec": f"{revision_dir}/figure_spec.json",
        "png": f"{revision_dir}/{spec.figure_id}.png",
        "pdf": f"{revision_dir}/{spec.figure_id}.pdf",
    }
    payloads = {
        "source-data": (source_payload, "application/json"),
        "spec": (spec_payload, "application/json"),
        "png": (png_payload, "image/png"),
        "pdf": (pdf_payload, "application/pdf"),
    }
    artifacts: list[FigureArtifactV1] = []
    for role in ("source-data", "spec", "png", "pdf"):
        payload, media_type = payloads[role]
        workspace.atomic_write_bytes(paths[role], payload)
        artifacts.append(
            _artifact(role=role, path=paths[role], payload=payload, media_type=media_type)
        )

    planner = "llm-spec-only" if planner_model is not None else "none"
    prompt_digest = None
    if planner == "llm-spec-only":
        if prompt_payload is None or raw_response_payload is None:
            raise ValueError("LLM-planned rendering requires prompt and raw response")
        prompt_path = f"{revision_dir}/planner_prompt.txt"
        raw_path = f"{revision_dir}/planner_response.json"
        workspace.atomic_write_bytes(prompt_path, prompt_payload)
        workspace.atomic_write_bytes(raw_path, raw_response_payload)
        artifacts.extend(
            [
                _artifact(
                    role="prompt",
                    path=prompt_path,
                    payload=prompt_payload,
                    media_type="text/plain; charset=utf-8",
                ),
                _artifact(
                    role="raw-planner-response",
                    path=raw_path,
                    payload=raw_response_payload,
                    media_type="application/json",
                ),
            ]
        )
        prompt_digest = bytes_digest(prompt_payload)

    manifest = FigureManifestV1.create(
        spec=spec,
        execution_mode="declarative-fixed-renderer",
        planner=planner,
        planner_model=planner_model,
        planner_model_revision=planner_model_revision,
        prompt_digest=prompt_digest,
        sampling=sampling or {},
        feedback=feedback,
        parent_manifest_digest=parent_manifest_digest,
        environment=environment,
        artifacts=tuple(artifacts),
        limitations=(),
    )
    manifest_path = f"{revision_dir}/figure_manifest.json"
    workspace.atomic_write_bytes(
        manifest_path,
        json_bytes(manifest.model_dump(mode="json")),
    )
    return manifest


def build_batch(manifests: list[FigureManifestV1]) -> FigureBatchV1:
    if not manifests:
        raise ValueError("figure batch must not be empty")
    revision = manifests[0].spec.revision
    figures: dict[str, str] = {}
    snippets: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for manifest in manifests:
        figure_id = manifest.spec.figure_id
        pdf = next(item for item in manifest.artifacts if item.role == "pdf")
        figures[figure_id] = pdf.relative_path
        kinds[figure_id] = manifest.spec.chart_type
        caption = _latex_escape(manifest.spec.caption or manifest.spec.title or figure_id)
        snippets[figure_id] = (
            "\\begin{figure}[H]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.85\\linewidth]{{{pdf.relative_path}}}\n"
            f"\\caption{{{caption}}}\n"
            f"\\label{{fig:{figure_id}}}\n"
            "\\end{figure}"
        )
    return FigureBatchV1.create(
        revision=revision,
        manifests=tuple(manifests),
        figures=figures,
        latex_snippets=snippets,
        figure_kinds=kinds,
    )


__all__ = [
    "RENDERER_VERSION",
    "build_batch",
    "bytes_digest",
    "json_bytes",
    "render_spec",
]
