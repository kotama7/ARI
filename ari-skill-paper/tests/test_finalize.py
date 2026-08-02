"""End-to-end PaperBuild finalization and tamper rejection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ari.public.evaluation import (
    GateFindingV1,
    GateFormulaProvenanceV1,
    GateReportV1,
    SemanticReviewV1,
)
from ari.public.figures import (
    FigureArtifactV1,
    FigureAxisV1,
    FigureBatchV1,
    FigureEnvironmentV1,
    FigureManifestV1,
    FigureSourceV1,
    FigureSpecV1,
    canonical_figure_digest,
)
from ari.public.paper import (
    PaperArtifactV1,
    PaperBuildV1,
    PaperCompileV1,
    PaperRevisionV1,
    canonical_paper_digest,
    parse_paper_build,
)
from ari.public.research_contract import canonical_digest
from ari.public.science_data import (
    ScienceArtifactRefV1,
    ScienceConfigurationV1,
    ScienceDataV1,
    ScienceDerivedV1,
    ScienceInterpretationV1,
    ScienceProvenanceV1,
    ScienceRawV1,
    formula_registry_digest,
    science_data_projection,
)
from ari.public.visual_review import (
    VisualArtifactRefV1,
    VisualCriteriaProfileV1,
    VisualCriterionV1,
    VisualReviewBatchV1,
    VisualReviewV1,
)
from src.claim_links import link_paper_claims
from src.finalize import finalize_build


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write(root: Path, relative_path: str, payload: bytes) -> bytes:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _artifact(
    root: Path,
    role: str,
    relative_path: str,
    payload: bytes,
    media_type: str = "application/json",
) -> PaperArtifactV1:
    _write(root, relative_path, payload)
    return PaperArtifactV1(
        role=role,
        relative_path=relative_path,
        digest=_digest(payload),
        media_type=media_type,
        size_bytes=len(payload),
    )


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


def _science() -> ScienceDataV1:
    tree = ScienceArtifactRefV1(
        relative_path="tree.json",
        digest="sha256:" + "1" * 64,
        media_type="application/json",
        role="experiment-tree",
        size_bytes=1,
    )
    raw = ScienceRawV1.create(
        tree_artifact=tree,
        configurations=(
            ScienceConfigurationV1(
                config_id="cfg-1",
                run_id="run",
                node_id="node-1",
                rank=1,
                source_kind="legacy-untyped",
                claim_eligible=False,
                source_artifacts=(tree,),
            ),
        ),
        node_report_status="missing",
        measurement_status="missing",
    )
    return ScienceDataV1.create(
        run_id="run",
        raw=raw,
        derived=ScienceDerivedV1.create(
            formula_registry_digest=formula_registry_digest()
        ),
        interpretation=ScienceInterpretationV1.create(
            status="unavailable",
            input_raw_digest=raw.raw_digest,
            error_kind="fixture",
            error_message="fixture",
        ),
        provenance=ScienceProvenanceV1(
            producer_tool_ref="transform-skill/nodes-to-science-data@v1",
            producer_version="1",
            input_artifacts=(tree,),
        ),
    )


def _figures(root: Path, science: ScienceDataV1) -> FigureBatchV1:
    data = {"configuration": ["fixture"], "value": [1.0]}
    spec = FigureSpecV1.create(
        figure_id="figure-1",
        chart_type="bar",
        data=data,
        source=FigureSourceV1(
            artifact_digest=science.science_data_digest,
            data_digest=canonical_figure_digest(data),
            record_ids=("fixture:value",),
        ),
        x_field="configuration",
        y_field="value",
        x_axis=FigureAxisV1(label="Configuration", unit="1"),
        y_axis=FigureAxisV1(label="Value", unit="1"),
        value_unit="1",
        caption="A source-bound fixture figure.",
    )
    source_payload = _write(root, "figures/source.json", b"{}\n")
    spec_payload = _write(
        root,
        "figures/spec.json",
        _json_bytes(spec.model_dump(mode="json")),
    )
    png_payload = _write(root, "figures/figure.png", b"fixture-png")
    pdf_payload = _write(root, "figures/figure.pdf", b"fixture-figure-pdf")
    items = (
        ("source-data", "figures/source.json", source_payload, "application/json"),
        ("spec", "figures/spec.json", spec_payload, "application/json"),
        ("png", "figures/figure.png", png_payload, "image/png"),
        ("pdf", "figures/figure.pdf", pdf_payload, "application/pdf"),
    )
    manifest = FigureManifestV1.create(
        spec=spec,
        environment=FigureEnvironmentV1.create(
            renderer_version="fixture/v1",
            python_version="3.13",
            matplotlib_version="3.10",
            font_family="DejaVu Sans",
            font_digest="sha256:" + "2" * 64,
            platform="fixture",
        ),
        artifacts=tuple(
            FigureArtifactV1(
                role=role,
                relative_path=path,
                digest=_digest(payload),
                media_type=media_type,
                size_bytes=len(payload),
            )
            for role, path, payload, media_type in items
        ),
    )
    return FigureBatchV1.create(
        revision=0,
        manifests=(manifest,),
        figures={"figure-1": "figures/figure.pdf"},
        latex_snippets={
            "figure-1": (
                "\\begin{figure}\\includegraphics{figures/figure.pdf}"
                "\\caption{A fixture.}\\label{fig:figure-1}\\end{figure}"
            )
        },
        figure_kinds={"figure-1": "bar"},
    )


def _fixture(root: Path, *, blocked: bool = False) -> dict[str, str]:
    science = _science()
    figures = _figures(root, science)
    science_artifact = _artifact(
        root,
        "science-data",
        "science_data.json",
        _json_bytes(science.model_dump(mode="json")),
    )
    figures_artifact = _artifact(
        root,
        "figure-batch",
        "figures_manifest.json",
        _json_bytes(figures.model_dump(mode="json")),
    )
    references_artifact = _artifact(
        root, "retrieval-records", "related_refs.json", b"{}\n"
    )
    ear_artifact = _artifact(
        root,
        "ear-manifest",
        "ear_manifest.json",
        _json_bytes({"evidence_index_digest": "sha256:" + "3" * 64}),
    )
    template_artifact = _artifact(
        root,
        "template",
        ".ari-paper/contracts/arxiv-template.tex",
        b"fixture template\n",
        "text/x-tex; charset=utf-8",
    )
    rubric_artifact = _artifact(
        root,
        "rubric",
        ".ari-paper/contracts/generic.yaml",
        b"id: generic\nversion: '1'\n",
        "application/yaml",
    )

    tex = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Results}\nThe admitted figure summarizes the observation.\n"
        "\\includegraphics{figures/figure.pdf}\n\\end{document}\n"
    ).encode()
    bib = b"% no citations\n"
    draft_tex = _artifact(
        root,
        "draft-tex",
        ".ari-paper/revisions/00/paper.tex",
        tex,
        "text/x-tex; charset=utf-8",
    )
    draft_bib = _artifact(
        root,
        "bibtex",
        ".ari-paper/revisions/00/refs.bib",
        bib,
        "application/x-bibtex; charset=utf-8",
    )
    revision = PaperRevisionV1.create(
        revision=0,
        reason="initial",
        tex_artifact=draft_tex,
        bib_artifact=draft_bib,
        figure_ids=("figure-1",),
        math_digest=canonical_paper_digest([]),
    )
    draft = PaperBuildV1.create(
        build_id="paper-run",
        run_id="run",
        build_revision=0,
        status="draft",
        input_artifacts=(
            science_artifact,
            figures_artifact,
            references_artifact,
            ear_artifact,
            template_artifact,
            rubric_artifact,
        ),
        venue_id="arxiv",
        venue_version="ari-venue-template/v1",
        template_digest=template_artifact.digest,
        rubric_id="generic",
        rubric_version="1",
        rubric_digest=rubric_artifact.digest,
        ear_digest=ear_artifact.digest,
        revisions=(revision,),
    )
    _write(
        root,
        ".ari-paper/paper_build.draft.json",
        _json_bytes(draft.model_dump(mode="json")),
    )
    _write(root, "full_paper.tex", tex)
    _write(root, "refs.bib", bib)
    pdf = _write(root, "full_paper.pdf", b"%PDF-fixture\n")

    stdout = _artifact(
        root,
        "compile-stdout",
        ".ari-paper/compile/stdout.log",
        b"ok\n",
        "text/plain; charset=utf-8",
    )
    stderr = _artifact(
        root,
        "compile-stderr",
        ".ari-paper/compile/stderr.log",
        b"\n",
        "text/plain; charset=utf-8",
    )
    pdf_artifact = PaperArtifactV1(
        role="pdf",
        relative_path="full_paper.pdf",
        digest=_digest(pdf),
        media_type="application/pdf",
        size_bytes=len(pdf),
    )
    compile_record = PaperCompileV1.create(
        status="completed",
        commands=(("pdflatex", "-no-shell-escape", "full_paper.tex"),),
        execution_identities=("sha256:" + "4" * 64,),
        log_artifacts=(stdout, stderr),
        pdf_artifact=pdf_artifact,
        environment_digest="sha256:" + "5" * 64,
    )
    _write(
        root,
        ".ari-paper/compile/final.json",
        _json_bytes(compile_record.model_dump(mode="json")),
    )

    claim_links = link_paper_claims(
        tex.decode(),
        science.model_dump(mode="json"),
        figures.model_dump(mode="json"),
    )
    _write(root, "paper_claim_links_locked.json", _json_bytes(claim_links))
    blocking_findings = (
        (
            GateFindingV1(
                severity="blocking",
                type="missing_evidence",
                message="fixture blocking finding",
            ),
        )
        if blocked
        else ()
    )
    gate = GateReportV1.create(
        source_run_id="run",
        phase="final",
        policy_mode="strict",
        comparison_scope="any",
        status="failed" if blocked else "passed",
        should_block=blocked,
        policy_digest="sha256:" + "6" * 64,
        evidence_digest="sha256:" + "7" * 64,
        formula_provenance=GateFormulaProvenanceV1(
            registry_digest=formula_registry_digest()
        ),
        blocking_findings=blocking_findings,
        metrics={},
    )
    _write(
        root,
        "evaluation/claim_evidence_hard_gate_locked.json",
        _json_bytes(gate.model_dump(mode="json")),
    )

    semantic = SemanticReviewV1.create(
        phase="locked",
        status="ok",
        model="fixture/semantic",
        prompt_digest="sha256:" + "8" * 64,
        evidence_digest=canonical_digest(
            {
                "paper": canonical_digest(tex.decode()),
                "science_data": science_data_projection(science),
                "claim_links": claim_links,
                "hard_gate_report_digest": gate.report_digest,
            }
        ),
        hard_gate_report_digest=gate.report_digest,
        detected_overclaim_count=0,
    )
    _write(
        root,
        "evaluation/evidence_grounded_semantic_review_locked.json",
        _json_bytes(semantic.model_dump(mode="json")),
    )

    manifest = figures.manifests[0]
    png_artifact = next(item for item in manifest.artifacts if item.role == "png")
    raw_visual_payload = _write(
        root, ".ari-paper/visual-review/raw.json", b'{"score":0.9}\n'
    )
    profile = VisualCriteriaProfileV1.create(
        profile_id="figure/v1",
        target_kind="figure",
        version="1",
        criteria=(
            VisualCriterionV1(
                criterion_id="readability",
                description="figure is readable",
            ),
        ),
        passing_score=0.7,
    )
    visual_review = VisualReviewV1.create(
        target_kind="figure",
        target_id="figure-1",
        figure_id="figure-1",
        source_manifest_digest=manifest.manifest_digest,
        target_artifact=VisualArtifactRefV1(
            role="review-target",
            relative_path=png_artifact.relative_path,
            digest=png_artifact.digest,
            media_type=png_artifact.media_type,
            size_bytes=png_artifact.size_bytes,
        ),
        context_digest="sha256:" + "9" * 64,
        criteria_profile_id=profile.profile_id,
        criteria_profile_digest=profile.profile_digest,
        status="completed",
        score=0.9,
        model="fixture/vlm",
        provider="fixture",
        prompt_digest="sha256:" + "a" * 64,
        raw_response_artifact=VisualArtifactRefV1(
            role="raw-model-response",
            relative_path=".ari-paper/visual-review/raw.json",
            digest=_digest(raw_visual_payload),
            media_type="application/json",
            size_bytes=len(raw_visual_payload),
        ),
    )
    visual_batch = VisualReviewBatchV1.create(
        source_batch_digest=figures.batch_digest,
        iteration=0,
        reviews=(visual_review,),
        score=0.9,
        failure_count=0,
    )
    _write(root, "vlm_review.json", _json_bytes(visual_batch.model_dump(mode="json")))

    raw_text = _artifact(
        root,
        "raw-model-response",
        ".ari-paper/text-review/raw-responses.json",
        b"[]\n",
    )
    text_review = {
        "schema_version": "ari.paper-text-review/v1",
        "model": "fixture/reviewer",
        "model_revision": "r1",
        "provider": "fixture",
        "prompt_digest": "sha256:" + "b" * 64,
        "paper_digest": canonical_paper_digest({"paper_text": tex.decode()}),
        "source_tex_digest": draft_tex.digest,
        "source_pdf_digest": None,
        "sampling": {"temperature": 0.0},
        "raw_response_artifact": raw_text.model_dump(mode="json"),
    }
    text_review["review_digest"] = canonical_paper_digest(text_review)
    _write(root, "review_report.json", _json_bytes(text_review))
    return {
        "workspace_root": str(root),
        "draft_build_path": ".ari-paper/paper_build.draft.json",
        "tex_path": "full_paper.tex",
        "bib_path": "refs.bib",
        "pdf_path": "full_paper.pdf",
        "compile_record_path": ".ari-paper/compile/final.json",
        "figures_manifest_path": "figures_manifest.json",
        "claim_links_path": "paper_claim_links_locked.json",
        "hard_gate_path": "evaluation/claim_evidence_hard_gate_locked.json",
        "text_review_path": "review_report.json",
        "visual_review_path": "vlm_review.json",
        "semantic_review_path": (
            "evaluation/evidence_grounded_semantic_review_locked.json"
        ),
        "output_path": "paper_build.json",
    }


def test_finalizer_locks_exact_artifacts_and_independent_reviews(tmp_path: Path):
    build = finalize_build(**_fixture(tmp_path))
    assert build.status == "finalized"
    assert {artifact.role for artifact in build.final_artifacts} == {
        "final-tex",
        "bibtex",
        "pdf",
        "claim-links",
    }
    assert build.reviews.text_review is not None
    assert build.reviews.visual_review is not None
    assert build.reviews.semantic_review is not None
    assert (
        parse_paper_build(json.loads((tmp_path / "paper_build.json").read_text()))
        == build
    )


def test_finalizer_persists_blocked_build_without_claiming_success(tmp_path: Path):
    build = finalize_build(**_fixture(tmp_path, blocked=True))
    assert build.status == "blocked"
    assert any("hard gate" in reason for reason in build.blocking_reasons)
    assert (tmp_path / "paper_build.json").is_file()


def test_finalizer_rejects_claim_links_from_other_tex(tmp_path: Path):
    arguments = _fixture(tmp_path)
    path = tmp_path / "paper_claim_links_locked.json"
    document = json.loads(path.read_text())
    document["counts"]["numeric_mentions"] = 99
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="claim links differ"):
        finalize_build(**arguments)


def test_finalizer_rejects_changed_compile_log(tmp_path: Path):
    arguments = _fixture(tmp_path)
    (tmp_path / ".ari-paper/compile/stdout.log").write_text("changed\n")
    with pytest.raises(ValueError, match="compile compile-stdout artifact changed"):
        finalize_build(**arguments)


def test_finalizer_blocks_visual_score_below_explicit_threshold(tmp_path: Path):
    arguments = _fixture(tmp_path)
    build = finalize_build(**arguments, visual_passing_score=0.95)
    assert build.status == "blocked"
    assert build.reviews.visual_score == 0.9
    assert build.reviews.visual_passing_score == 0.95
    assert any("visual review score" in reason for reason in build.blocking_reasons)
