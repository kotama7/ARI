"""Fail-closed deterministic finalization of a scientific paper build."""

from __future__ import annotations

import json
import os
import re

from ari.public.evaluation import parse_gate_report, parse_semantic_review
from ari.public.execution import WorkspaceRefV1
from ari.public.figures import parse_figure_batch
from ari.public.latex_claims import find_claim_anchors
from ari.public.paper import (
    PaperArtifactV1,
    PaperBuildV1,
    PaperCompileV1,
    PaperGateSummaryV1,
    PaperModelCallV1,
    PaperNumericCoverageV1,
    PaperReviewSetV1,
    PaperRevisionV1,
    canonical_paper_digest,
    parse_paper_build,
    parse_paper_model_call_batch,
)
from ari.public.research_contract import canonical_digest
from ari.public.science_data import science_data_projection
from ari.public.visual_review import parse_visual_review_batch

try:
    from src.authoring import artifact_from_workspace, bytes_digest, json_bytes
    from src.claim_links import link_paper_claims as recompute_claim_links
except ImportError:  # running from within src/
    from authoring import (  # type: ignore
        artifact_from_workspace,
        bytes_digest,
        json_bytes,
    )
    from claim_links import link_paper_claims as recompute_claim_links  # type: ignore


_CITATION = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])?\{([^}]+)\}")
_GRAPHIC = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_MATH = re.compile(
    r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]|"
    r"\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\}",
    re.DOTALL,
)


class PaperFinalizationError(RuntimeError):
    """Final artifacts were recorded, but scientific finalization was blocked."""


def _json(workspace: WorkspaceRefV1, path: str, max_bytes: int = 64 * 1024 * 1024):
    payload = workspace.read_bytes(path, max_bytes=max_bytes)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"paper input {path!r} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"paper input {path!r} is not a JSON object")
    return value


def _artifact(
    workspace: WorkspaceRefV1,
    path: str,
    role: str,
    media_type: str,
) -> PaperArtifactV1:
    return artifact_from_workspace(
        workspace,
        role=role,
        relative_path=path,
        media_type=media_type,
        max_bytes=256 * 1024 * 1024,
    )[0]


def _verify_artifact(
    workspace: WorkspaceRefV1,
    artifact: PaperArtifactV1,
    *,
    label: str,
    max_bytes: int = 256 * 1024 * 1024,
) -> bytes:
    payload = workspace.read_bytes(artifact.relative_path, max_bytes=max_bytes)
    if len(payload) != artifact.size_bytes or bytes_digest(payload) != artifact.digest:
        raise ValueError(f"{label} artifact changed after it was recorded")
    return payload


def _verify_model_call(
    workspace: WorkspaceRefV1,
    call: PaperModelCallV1,
) -> None:
    _verify_artifact(
        workspace,
        call.prompt_artifact,
        label=f"paper model call {call.call_id} prompt",
        max_bytes=64 * 1024 * 1024,
    )
    _verify_artifact(
        workspace,
        call.raw_response_artifact,
        label=f"paper model call {call.call_id} raw response",
        max_bytes=64 * 1024 * 1024,
    )


def _final_revision(
    *,
    workspace: WorkspaceRefV1,
    draft: PaperBuildV1,
    tex_artifact: PaperArtifactV1,
    bib_artifact: PaperArtifactV1,
    figures_path: str,
    model_call_id: str | None,
) -> PaperRevisionV1:
    tex = workspace.read_bytes(
        tex_artifact.relative_path,
        max_bytes=32 * 1024 * 1024,
    ).decode("utf-8")
    figures = parse_figure_batch(
        workspace.read_bytes(figures_path, max_bytes=16 * 1024 * 1024).decode("utf-8")
    )
    citations = tuple(
        dict.fromkeys(
            key.strip()
            for match in _CITATION.finditer(tex)
            for key in match.group(1).split(",")
            if key.strip()
        )
    )
    path_to_id = {path: figure_id for figure_id, path in figures.figures.items()}
    figure_ids = tuple(
        dict.fromkeys(
            path_to_id[path] for path in _GRAPHIC.findall(tex) if path in path_to_id
        )
    )
    return PaperRevisionV1.create(
        revision=len(draft.revisions),
        parent_revision_digest=draft.revisions[-1].revision_digest,
        reason="finalize",
        tex_artifact=tex_artifact,
        bib_artifact=bib_artifact,
        model_call_id=model_call_id,
        claim_anchors=tuple(
            dict.fromkeys(item["anchor"] for item in find_claim_anchors(tex))
        ),
        citation_keys=citations,
        figure_ids=figure_ids,
        math_digest=canonical_paper_digest(_MATH.findall(tex)),
    )


def finalize_build(
    *,
    workspace_root: str,
    draft_build_path: str,
    tex_path: str,
    bib_path: str,
    pdf_path: str,
    compile_record_path: str,
    figures_manifest_path: str,
    claim_links_path: str,
    hard_gate_path: str,
    text_review_path: str,
    visual_review_path: str,
    semantic_review_path: str,
    refinement_call_path: str = "",
    visual_passing_score: float = 0.7,
    output_path: str = "paper_build.json",
) -> PaperBuildV1:
    """Create the immutable final/blocked build record from exact artifacts."""

    workspace = WorkspaceRefV1(root=workspace_root)
    draft = parse_paper_build(
        workspace.read_bytes(draft_build_path, max_bytes=64 * 1024 * 1024).decode(
            "utf-8"
        )
    )
    if draft.status != "draft":
        raise ValueError("paper finalizer requires a draft PaperBuildV1")
    if not 0 <= visual_passing_score <= 1:
        raise ValueError("paper visual passing score must be in [0, 1]")
    for declared in draft.input_artifacts:
        _verify_artifact(
            workspace,
            declared,
            label=f"paper input {declared.role}",
        )
    for recorded_revision in draft.revisions:
        _verify_artifact(
            workspace,
            recorded_revision.tex_artifact,
            label=f"paper revision {recorded_revision.revision} TeX",
            max_bytes=32 * 1024 * 1024,
        )
        if recorded_revision.bib_artifact is not None:
            _verify_artifact(
                workspace,
                recorded_revision.bib_artifact,
                label=f"paper revision {recorded_revision.revision} bibliography",
                max_bytes=32 * 1024 * 1024,
            )
    for recorded_call in draft.model_calls:
        _verify_model_call(workspace, recorded_call)

    tex_artifact = _artifact(
        workspace,
        tex_path,
        "final-tex",
        "text/x-tex; charset=utf-8",
    )
    bib_artifact = _artifact(
        workspace,
        bib_path,
        "bibtex",
        "application/x-bibtex; charset=utf-8",
    )
    pdf_artifact = _artifact(workspace, pdf_path, "pdf", "application/pdf")
    compile_document = _json(workspace, compile_record_path)
    compile_record = PaperCompileV1.model_validate(compile_document)
    for log_artifact in compile_record.log_artifacts:
        _verify_artifact(
            workspace,
            log_artifact,
            label=f"paper compile {log_artifact.role}",
            max_bytes=64 * 1024 * 1024,
        )
    if compile_record.pdf_artifact is not None:
        _verify_artifact(
            workspace,
            compile_record.pdf_artifact,
            label="paper compile PDF",
        )

    claim_document = _json(workspace, claim_links_path)
    if (
        claim_document.get("schema_version") != "ari.paper-claim-links/v1"
        or claim_document.get("stage") != "link_paper_claims"
    ):
        raise ValueError("paper claim links have an unknown schema")
    tex_document = workspace.read_bytes(
        tex_path,
        max_bytes=32 * 1024 * 1024,
    ).decode("utf-8")
    input_by_role = {artifact.role: artifact for artifact in draft.input_artifacts}
    manuscript_publication_reasons: list[str] = []
    if os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off") == "enforce":
        from ari.public.manuscript import (
            ManuscriptAuthoringBindingV1,
            ManuscriptContextV1,
            ManuscriptReadinessReportV1,
            ManuscriptRequirementProfileV1,
            SectionBriefBundleV1,
        )

        required_manuscript_roles = {
            "manuscript-profile",
            "manuscript-context",
            "manuscript-readiness",
            "section-briefs",
            "manuscript-authoring-binding",
        }
        if not required_manuscript_roles.issubset(input_by_role):
            raise ValueError("enforced paper build lacks manuscript binding inputs")

        def _manuscript_document(role, contract):
            return contract.model_validate(
                _json(workspace, input_by_role[role].relative_path)
            )

        manuscript_profile = _manuscript_document(
            "manuscript-profile", ManuscriptRequirementProfileV1
        )
        manuscript_context = _manuscript_document(
            "manuscript-context", ManuscriptContextV1
        )
        manuscript_readiness = _manuscript_document(
            "manuscript-readiness", ManuscriptReadinessReportV1
        )
        manuscript_briefs = _manuscript_document(
            "section-briefs", SectionBriefBundleV1
        )
        manuscript_binding = _manuscript_document(
            "manuscript-authoring-binding", ManuscriptAuthoringBindingV1
        )
        if (
            manuscript_context.profile_digest != manuscript_profile.profile_digest
            or manuscript_readiness.profile_digest != manuscript_profile.profile_digest
            or manuscript_briefs.profile_digest != manuscript_profile.profile_digest
            or manuscript_binding.profile_digest != manuscript_profile.profile_digest
            or manuscript_readiness.context_digest != manuscript_context.context_digest
            or manuscript_briefs.context_digest != manuscript_context.context_digest
            or manuscript_binding.context_digest != manuscript_context.context_digest
            or manuscript_briefs.readiness_digest
            != manuscript_readiness.readiness_digest
            or manuscript_binding.readiness_digest
            != manuscript_readiness.readiness_digest
            or manuscript_binding.brief_bundle_digest
            != manuscript_briefs.bundle_digest
            or manuscript_binding.target_build_id != draft.build_id
            or manuscript_binding.run_id != draft.run_id
        ):
            raise ValueError("paper build manuscript binding lineage is incoherent")
        if manuscript_readiness.publication_verdict != "ready":
            manuscript_publication_reasons.append(
                "manuscript readiness blocks publication"
            )
    science_document = _json(
        workspace,
        input_by_role["science-data"].relative_path,
    )
    figures_document = _json(
        workspace,
        input_by_role["figure-batch"].relative_path,
    )
    expected_claim_document = recompute_claim_links(
        tex_document,
        science_document,
        figures_document,
    )
    if claim_document != expected_claim_document:
        raise ValueError("paper claim links differ from the exact final TeX/evidence")
    claim_artifact = _artifact(
        workspace,
        claim_links_path,
        "claim-links",
        "application/json",
    )
    gate_document = _json(workspace, hard_gate_path)
    gate = parse_gate_report(gate_document)
    if gate.phase != "final" or gate.source_run_id != draft.run_id:
        raise ValueError("paper hard gate belongs to another build or phase")
    gate_artifact = _artifact(
        workspace,
        hard_gate_path,
        "hard-gate",
        "application/json",
    )
    gate_summary = PaperGateSummaryV1(
        mode=gate.policy_mode,
        status=("blocked" if gate.blocking_findings else "pass"),
        blocking_error_count=len(gate.blocking_findings),
        report_digest=gate.report_digest,
    )

    text_document = _json(workspace, text_review_path)
    if text_document.get("schema_version") != "ari.paper-text-review/v1":
        raise ValueError("text review must use ari.paper-text-review/v1")
    advertised_review_digest = text_document.get("review_digest")
    expected_review_digest = canonical_paper_digest(
        {key: value for key, value in text_document.items() if key != "review_digest"}
    )
    if advertised_review_digest != expected_review_digest:
        raise ValueError("paper text review digest differs from its payload")
    if text_document.get("source_tex_digest") not in {
        revision.tex_artifact.digest for revision in draft.revisions
    }:
        raise ValueError("paper text review belongs to an unknown draft revision")
    raw_text_review = PaperArtifactV1.model_validate(
        text_document.get("raw_response_artifact")
    )
    if raw_text_review.role != "raw-model-response":
        raise ValueError("paper text review raw response has the wrong role")
    _verify_artifact(
        workspace,
        raw_text_review,
        label="paper text review raw response",
        max_bytes=64 * 1024 * 1024,
    )
    visual = parse_visual_review_batch(_json(workspace, visual_review_path))
    figures = parse_figure_batch(
        workspace.read_bytes(
            figures_manifest_path,
            max_bytes=16 * 1024 * 1024,
        ).decode("utf-8")
    )
    if visual.source_batch_digest != figures.batch_digest:
        raise ValueError("visual review belongs to another FigureBatchV1")
    manifests = {manifest.spec.figure_id: manifest for manifest in figures.manifests}
    for review in visual.reviews:
        manifest = manifests.get(review.target_id)
        if (
            manifest is None
            or review.source_manifest_digest != manifest.manifest_digest
        ):
            raise ValueError("visual review target differs from FigureBatchV1")
        admitted = {
            (artifact.relative_path, artifact.digest, artifact.size_bytes)
            for artifact in manifest.artifacts
            if artifact.role in {"png", "pdf"}
        }
        target = review.target_artifact
        if (target.relative_path, target.digest, target.size_bytes) not in admitted:
            raise ValueError("visual review artifact is not admitted by FigureBatchV1")
        target_payload = workspace.read_bytes(
            target.relative_path,
            max_bytes=64 * 1024 * 1024,
        )
        if (
            len(target_payload) != target.size_bytes
            or bytes_digest(target_payload) != target.digest
        ):
            raise ValueError("visual review target artifact changed")
        if review.raw_response_artifact is not None:
            raw = review.raw_response_artifact
            raw_payload = workspace.read_bytes(
                raw.relative_path,
                max_bytes=64 * 1024 * 1024,
            )
            if (
                len(raw_payload) != raw.size_bytes
                or bytes_digest(raw_payload) != raw.digest
            ):
                raise ValueError("visual review raw response artifact changed")
    semantic = parse_semantic_review(_json(workspace, semantic_review_path))
    expected_semantic_evidence = canonical_digest(
        {
            "paper": canonical_digest(tex_document),
            "science_data": science_data_projection(science_document),
            "claim_links": claim_document,
            "hard_gate_report_digest": gate.report_digest,
        }
    )
    if (
        semantic.evidence_digest != expected_semantic_evidence
        or semantic.hard_gate_report_digest != gate.report_digest
    ):
        raise ValueError("semantic review belongs to another paper evidence set")
    reviews = PaperReviewSetV1(
        text_review=_artifact(
            workspace,
            text_review_path,
            "text-review",
            "application/json",
        ),
        visual_review=_artifact(
            workspace,
            visual_review_path,
            "visual-review",
            "application/json",
        ),
        semantic_review=_artifact(
            workspace,
            semantic_review_path,
            "semantic-review",
            "application/json",
        ),
        hard_gate=gate_artifact,
        visual_score=visual.score,
        visual_passing_score=visual_passing_score,
    )

    counts = claim_document.get("counts") or {}
    result_mentions = int(counts.get("result_claim_mentions") or 0)
    uncovered = len(claim_document.get("uncovered_numeric_candidates") or ())
    unresolved = len(claim_document.get("unresolved_anchors") or ())
    coverage = PaperNumericCoverageV1(
        result_mentions=result_mentions,
        linked_mentions=max(0, result_mentions - uncovered),
        excluded_mentions=0,
        unresolved_anchors=unresolved,
        uncovered_mentions=uncovered,
    )

    model_calls = list(draft.model_calls)
    final_call_id = None
    if refinement_call_path:
        refinement_path = workspace.resolve(
            refinement_call_path,
            must_exist=False,
        )
        if refinement_path.is_file():
            refinement_document = _json(workspace, refinement_call_path)
            if (
                refinement_document.get("schema_version")
                == "ari.paper-model-call-batch/v1"
            ):
                refinement_calls = list(
                    parse_paper_model_call_batch(refinement_document).calls
                )
            else:
                # Published draft fixtures may contain the pre-batch single-call
                # record.  This is a read-only migration path, never a producer.
                refinement_calls = [
                    PaperModelCallV1.model_validate(refinement_document)
                ]
            existing_ids = {call.call_id for call in model_calls}
            incoming_ids = [call.call_id for call in refinement_calls]
            if existing_ids.intersection(incoming_ids) or len(incoming_ids) != len(
                set(incoming_ids)
            ):
                raise ValueError("paper refinement call ID collides with authoring")
            model_calls.extend(refinement_calls)
            for refinement_call in refinement_calls:
                _verify_model_call(workspace, refinement_call)
            if refinement_calls:
                final_call_id = refinement_calls[-1].call_id

    revision = _final_revision(
        workspace=workspace,
        draft=draft,
        tex_artifact=tex_artifact,
        bib_artifact=bib_artifact,
        figures_path=figures_manifest_path,
        model_call_id=final_call_id,
    )
    previous = draft.revisions[-1]
    reasons: list[str] = []
    reasons.extend(manuscript_publication_reasons)
    if not set(previous.claim_anchors).issubset(revision.claim_anchors):
        reasons.append("final revision dropped a claim anchor")
    if not set(previous.citation_keys).issubset(revision.citation_keys):
        reasons.append("final revision dropped an admitted citation key")
    if not set(previous.figure_ids).issubset(revision.figure_ids):
        reasons.append("final revision dropped a canonical figure ID")
    if previous.math_digest != revision.math_digest:
        reasons.append("final revision changed mathematical content")
    if gate.policy_mode == "off":
        reasons.append("hard gate was disabled")
    if gate.blocking_findings:
        reasons.append("hard gate reported blocking findings")
    if unresolved:
        reasons.append("paper has unresolved claim anchors")
    if uncovered:
        reasons.append("paper has uncovered numeric result mentions")
    if compile_record.status != "completed":
        reasons.append("final paper compile did not complete")
    elif (
        compile_record.pdf_artifact is None
        or compile_record.pdf_artifact.digest != pdf_artifact.digest
    ):
        reasons.append("final PDF differs from the compile record")
    if visual.failure_count:
        reasons.append("visual review contains failed targets")
    elif visual.score < visual_passing_score:
        reasons.append(
            "visual review score "
            f"{visual.score:.3f} is below the required {visual_passing_score:.3f}"
        )

    if reasons:
        status = (
            "compile-error"
            if any("compile" in reason for reason in reasons)
            else "blocked"
        )
    else:
        status = "finalized"
    build = PaperBuildV1.create(
        build_id=draft.build_id,
        run_id=draft.run_id,
        build_revision=1,
        parent_build_digest=draft.build_digest,
        status=status,
        input_artifacts=draft.input_artifacts,
        venue_id=draft.venue_id,
        venue_version=draft.venue_version,
        template_digest=draft.template_digest,
        rubric_id=draft.rubric_id,
        rubric_version=draft.rubric_version,
        rubric_digest=draft.rubric_digest,
        ear_digest=draft.ear_digest,
        revisions=(*draft.revisions, revision),
        model_calls=tuple(model_calls),
        compile=compile_record,
        reviews=reviews,
        gate=gate_summary,
        numeric_coverage=coverage,
        final_artifacts=(tex_artifact, bib_artifact, pdf_artifact, claim_artifact),
        blocking_reasons=tuple(reasons),
        limitations=draft.limitations,
    )
    # Workflow interpolation commonly supplies ``{{checkpoint_dir}}/paper_build.json``
    # as an absolute path.  Reads intentionally accept absolute paths that resolve
    # inside the closed workspace, while atomic writes require a workspace-relative
    # name.  Resolve first (which rejects escapes and symlinks), then hand the
    # validated relative name to the atomic writer.
    resolved_output = workspace.resolve(output_path, must_exist=False)
    relative_output = resolved_output.relative_to(workspace.root).as_posix()
    workspace.atomic_write_bytes(
        relative_output,
        json_bytes(build.model_dump(mode="json")),
    )
    return build


__all__ = ["PaperFinalizationError", "finalize_build"]
