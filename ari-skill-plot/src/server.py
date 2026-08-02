"""Scientific figure MCP server with a fixed declarative renderer."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ari.public.figures import FigureBatchV1, FigureSpecV1, parse_figure_batch
from planning import (
    deterministic_specs,
    load_native_science_data,
    parse_feedback,
    plan_specs,
    workspace_from_output,
)
from renderer import build_batch, render_spec


mcp = FastMCP("plot-skill")

try:
    from ari.public import cost_tracker as _ari_cost_tracker

    _ari_cost_tracker.bootstrap_skill("plot")
except Exception:
    pass


def _bounded_revision(value: int | str) -> int:
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("figure revision must be an integer") from exc
    if not 0 <= revision <= 2:
        raise ValueError("figure revision must be in [0, 2]")
    return revision


def _bounded_count(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
        raise ValueError("n_figures must be an integer in [1, 12]")
    return value


def _science_path_in_workspace(output_dir: str, science_data_path: str):
    workspace, relative_directory = workspace_from_output(output_dir)
    try:
        path = workspace.resolve(science_data_path, require_file=True)
    except Exception as exc:
        raise ValueError(f"science data path rejected: {exc}") from exc
    return workspace, relative_directory, path


def _load_previous_batch(
    *,
    workspace,
    previous_batch_path: str,
    revision: int,
) -> FigureBatchV1 | None:
    if revision == 0:
        if previous_batch_path:
            raise ValueError("initial figure revision cannot name a previous batch")
        return None
    if not previous_batch_path:
        raise ValueError("feedback revisions require previous_batch_path")
    path = workspace.resolve(previous_batch_path, require_file=True)
    previous = parse_figure_batch(path.read_text(encoding="utf-8"))
    if previous.revision != revision - 1:
        raise ValueError("previous figure batch revision is not the direct parent")
    return previous


@mcp.tool()
def render_figure(request: dict[str, Any]) -> dict[str, Any]:
    """Render one canonical ``FigureSpecV1`` without executing caller code."""

    if not isinstance(request, dict) or set(request) != {
        "spec",
        "workspace",
        "relative_directory",
    }:
        raise ValueError(
            "render_figure requires exactly spec, workspace, and relative_directory"
        )
    from ari.public.execution import WorkspaceRefV1

    workspace = WorkspaceRefV1.model_validate(request["workspace"])
    spec = FigureSpecV1.model_validate(request["spec"])
    try:
        manifest = render_spec(
            spec,
            workspace=workspace,
            relative_directory=str(request["relative_directory"]),
        )
    except Exception as exc:
        raise ValueError(f"figure rendering rejected: {exc}") from exc
    return manifest.model_dump(mode="json")


@mcp.tool()
async def generate_figures(
    science_data_path: str,
    output_dir: str,
    n_figures: int = 3,
    revision: int | str = 0,
) -> dict[str, Any]:
    """Render deterministic default specs from native ``ScienceDataV1``."""

    count = _bounded_count(n_figures)
    revision_number = _bounded_revision(revision)
    if revision_number != 0:
        raise ValueError("deterministic default generation supports revision 0 only")
    workspace, relative_directory, source_path = _science_path_in_workspace(
        output_dir, science_data_path
    )
    science, artifact_digest, _ = load_native_science_data(str(source_path))
    specs = deterministic_specs(
        science,
        artifact_digest,
        revision=revision_number,
        limit=count,
    )
    manifests = [
        render_spec(
            spec,
            workspace=workspace,
            relative_directory=relative_directory,
        )
        for spec in specs
    ]
    batch = build_batch(manifests)
    return batch.model_dump(mode="json")


@mcp.tool()
async def generate_figures_llm(
    science_data_path: str,
    output_dir: str,
    experiment_summary: str = "",
    n_figures: int = 3,
    vlm_feedback: str = "",
    revision: int | str = 0,
    previous_batch_path: str = "",
) -> dict[str, Any]:
    """Let an LLM choose admitted fields, then use the fixed renderer.

    The model can emit only ``metric_id``, ``chart_type``, and ``x_mode``.
    Numeric values, units, captions, paths, code, SVG, and artifact bytes are
    selected or produced deterministically from the verified science record.
    """

    count = _bounded_count(n_figures)
    revision_number = _bounded_revision(revision)
    workspace, relative_directory, source_path = _science_path_in_workspace(
        output_dir, science_data_path
    )
    previous = _load_previous_batch(
        workspace=workspace,
        previous_batch_path=previous_batch_path,
        revision=revision_number,
    )
    if revision_number == 0 and vlm_feedback.strip():
        raise ValueError("initial figure generation cannot include VLM feedback")
    if revision_number > 0 and not vlm_feedback.strip():
        raise ValueError("feedback figure revisions require a review document")

    science, artifact_digest, _ = load_native_science_data(str(source_path))
    required_metrics = None
    if previous is not None:
        required_metrics = tuple(item.spec.y_field for item in previous.manifests)
        count = len(required_metrics)
    specs, prompt, raw, model, model_revision, sampling = await plan_specs(
        science,
        artifact_digest,
        revision=revision_number,
        n_figures=count,
        context=experiment_summary,
        feedback_text=vlm_feedback,
        required_metric_ids=required_metrics,
    )

    previous_by_id = (
        {item.spec.figure_id: item for item in previous.manifests}
        if previous is not None
        else {}
    )
    manifests = []
    for spec in specs:
        parent = previous_by_id.get(spec.figure_id)
        if previous is not None and parent is None:
            raise ValueError("feedback revision changed a stable figure ID")
        feedback = parse_feedback(
            vlm_feedback,
            revision=revision_number,
            figure_id=spec.figure_id,
        )
        if parent is not None and feedback is not None:
            if feedback.source_manifest_digest != parent.manifest_digest:
                raise ValueError("VLM feedback does not bind the previous manifest")
        manifests.append(
            render_spec(
                spec,
                workspace=workspace,
                relative_directory=relative_directory,
                planner_model=model,
                planner_model_revision=model_revision,
                prompt_payload=prompt,
                raw_response_payload=raw,
                sampling=sampling,
                feedback=feedback,
                parent_manifest_digest=(parent.manifest_digest if parent else None),
            )
        )
    batch = build_batch(manifests)
    return batch.model_dump(mode="json")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
