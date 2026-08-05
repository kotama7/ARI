"""Native evidence loading and immutable authoring provenance helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from ari.public.execution import WorkspaceRefV1
from ari.public.figures import FigureBatchV1, parse_figure_batch
from ari.public.latex_claims import find_claim_anchors
from ari.public.paper import (
    PaperArtifactV1,
    PaperBuildV1,
    PaperCompileV1,
    PaperModelCallV1,
    PaperModelUsageV1,
    PaperRevisionV1,
    canonical_paper_digest,
)
from ari.public.research_contract import (
    RetrievalRecordV1,
    SurveySnapshotV1,
    load_survey_snapshot_ref,
)
from ari.public.science_data import ScienceDataV1, parse_science_data


_CITATION = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])?\{([^}]+)\}")
_GRAPHIC = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_MATH = re.compile(
    r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]|"
    r"\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\}",
    re.DOTALL,
)
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def artifact_from_payload(
    workspace: WorkspaceRefV1,
    *,
    role: str,
    relative_path: str,
    payload: bytes,
    media_type: str,
) -> PaperArtifactV1:
    workspace.atomic_write_bytes(relative_path, payload)
    return PaperArtifactV1(
        role=role,
        relative_path=relative_path,
        digest=bytes_digest(payload),
        media_type=media_type,
        size_bytes=len(payload),
    )


def artifact_from_workspace(
    workspace: WorkspaceRefV1,
    *,
    role: str,
    relative_path: str,
    media_type: str,
    max_bytes: int = 64 * 1024 * 1024,
) -> tuple[PaperArtifactV1, bytes]:
    resolved = workspace.resolve(relative_path, require_file=True)
    canonical_path = resolved.relative_to(workspace.root).as_posix()
    payload = workspace.read_bytes(canonical_path, max_bytes=max_bytes)
    return (
        PaperArtifactV1(
            role=role,
            relative_path=canonical_path,
            digest=bytes_digest(payload),
            media_type=media_type,
            size_bytes=len(payload),
        ),
        payload,
    )


@dataclass(frozen=True)
class AuthoringInputs:
    workspace: WorkspaceRefV1
    science: ScienceDataV1
    figures: FigureBatchV1
    references: dict[str, Any]
    ear_manifest: dict[str, Any]
    input_artifacts: tuple[PaperArtifactV1, ...]
    science_payload: bytes
    figures_payload: bytes
    references_payload: bytes
    ear_payload: bytes
    verified_context: dict[str, Any] | None
    manuscript_profile: Any | None = None
    manuscript_context: Any | None = None
    manuscript_readiness: Any | None = None
    manuscript_briefs: Any | None = None
    manuscript_binding: Any | None = None


def _load_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_references(
    workspace: WorkspaceRefV1,
    document: dict[str, Any],
) -> None:
    if document.get("schema_version") != "ari.retrieval-result/v1":
        raise ValueError("paper references must use ari.retrieval-result/v1")
    snapshot = SurveySnapshotV1.model_validate(document.get("survey_snapshot"))
    if snapshot.snapshot_digest != document.get("survey_snapshot_digest"):
        raise ValueError("paper reference snapshot digest differs from result")
    records = tuple(
        RetrievalRecordV1.model_validate(record)
        for record in document.get("records") or ()
    )
    if records != snapshot.records:
        raise ValueError("paper reference records differ from the verified snapshot")
    snapshot_ref = str(document.get("snapshot_ref") or "")
    if not snapshot_ref:
        raise ValueError("paper references lack a recorded snapshot_ref")
    replayed = load_survey_snapshot_ref(workspace.root, snapshot_ref)
    if replayed != snapshot:
        raise ValueError("paper reference artifact does not reproduce the snapshot")


def _load_enforced_manuscript_inputs(
    workspace: WorkspaceRefV1,
) -> tuple[list[PaperArtifactV1], tuple[Any, Any, Any, Any, Any]]:
    """Load the exact ready bundle advertised by the fixed pipeline guard.

    Imports stay inside the opt-in enforce branch so legacy and audit authoring
    retain their historical import graph and PaperBuild bytes.
    """

    mode = os.environ.get("ARI_MANUSCRIPT_RUNTIME_MODE", "off").strip().lower()
    if mode != "enforce":
        return [], (None, None, None, None, None)
    from ari.public.manuscript import (
        ManuscriptAuthoringBindingV1,
        ManuscriptContextV1,
        ManuscriptReadinessReportV1,
        ManuscriptRequirementProfileV1,
        SectionBriefBundleV1,
    )

    specs = (
        ("manuscript-profile", "ARI_MANUSCRIPT_PROFILE_PATH", ManuscriptRequirementProfileV1),
        ("manuscript-context", "ARI_MANUSCRIPT_CONTEXT_PATH", ManuscriptContextV1),
        ("manuscript-readiness", "ARI_MANUSCRIPT_READINESS_PATH", ManuscriptReadinessReportV1),
        ("section-briefs", "ARI_MANUSCRIPT_BRIEFS_PATH", SectionBriefBundleV1),
        ("manuscript-authoring-binding", "ARI_MANUSCRIPT_BINDING_PATH", ManuscriptAuthoringBindingV1),
    )
    artifacts: list[PaperArtifactV1] = []
    documents: list[Any] = []
    for role, env_name, contract in specs:
        path = os.environ.get(env_name, "").strip()
        if not path:
            raise ValueError(f"enforced manuscript authoring lacks {env_name}")
        artifact, payload = artifact_from_workspace(
            workspace,
            role=role,
            relative_path=path,
            media_type="application/json",
            max_bytes=64 * 1024 * 1024,
        )
        document = contract.model_validate(_load_json(payload, role))
        artifacts.append(artifact)
        documents.append(document)

    profile, context, readiness, briefs, binding = documents
    if (
        context.profile_digest != profile.profile_digest
        or readiness.profile_digest != profile.profile_digest
        or briefs.profile_digest != profile.profile_digest
        or binding.profile_digest != profile.profile_digest
        or readiness.context_digest != context.context_digest
        or briefs.context_digest != context.context_digest
        or binding.context_digest != context.context_digest
        or briefs.readiness_digest != readiness.readiness_digest
        or binding.readiness_digest != readiness.readiness_digest
        or binding.brief_bundle_digest != briefs.bundle_digest
        or binding.source_snapshot_digest != context.source_snapshot_digest
    ):
        raise ValueError("manuscript authoring inputs do not share one digest lineage")
    if readiness.authoring_verdict not in {"ready", "ready_with_disclosures"}:
        raise ValueError("manuscript authoring binding is not authoring-ready")
    return artifacts, (profile, context, readiness, briefs, binding)


def load_authoring_inputs(
    *,
    workspace_root: str,
    science_data_path: str,
    figures_manifest_path: str,
    references_path: str,
    ear_manifest_path: str,
    verified_context_path: str = "",
) -> AuthoringInputs:
    workspace = WorkspaceRefV1(root=workspace_root)
    inputs = (
        ("science-data", science_data_path, "application/json", 64 * 1024 * 1024),
        ("figure-batch", figures_manifest_path, "application/json", 16 * 1024 * 1024),
        ("retrieval-records", references_path, "application/json", 64 * 1024 * 1024),
        ("ear-manifest", ear_manifest_path, "application/json", 16 * 1024 * 1024),
    )
    artifacts: list[PaperArtifactV1] = []
    payloads: list[bytes] = []
    for role, path, media_type, max_bytes in inputs:
        artifact, payload = artifact_from_workspace(
            workspace,
            role=role,
            relative_path=path,
            media_type=media_type,
            max_bytes=max_bytes,
        )
        artifacts.append(artifact)
        payloads.append(payload)
    science_payload, figures_payload, references_payload, ear_payload = payloads
    science = parse_science_data(science_payload.decode("utf-8"))
    figures = parse_figure_batch(figures_payload.decode("utf-8"))
    references = _load_json(references_payload, "paper references")
    _validate_references(workspace, references)
    ear_manifest = _load_json(ear_payload, "EAR manifest")
    evidence_digest = ear_manifest.get("evidence_index_digest")
    if not isinstance(evidence_digest, str) or not _SHA.fullmatch(evidence_digest):
        raise ValueError("EAR manifest lacks a canonical evidence index digest")
    verified_context = None
    if verified_context_path:
        context_file = workspace.resolve(verified_context_path, must_exist=False)
        if context_file.exists():
            verified_context = _load_json(
                workspace.read_bytes(
                    verified_context_path,
                    max_bytes=16 * 1024 * 1024,
                ),
                "verified context",
            )
    manuscript_artifacts, manuscript_documents = _load_enforced_manuscript_inputs(
        workspace
    )
    artifacts.extend(manuscript_artifacts)
    (
        manuscript_profile,
        manuscript_context,
        manuscript_readiness,
        manuscript_briefs,
        manuscript_binding,
    ) = manuscript_documents
    if manuscript_binding is not None:
        if manuscript_binding.run_id != science.run_id:
            raise ValueError("manuscript binding belongs to another science-data run")
        if manuscript_binding.target_build_id != f"paper-{science.run_id}":
            raise ValueError("manuscript binding targets another paper build")
    return AuthoringInputs(
        workspace=workspace,
        science=science,
        figures=figures,
        references=references,
        ear_manifest=ear_manifest,
        input_artifacts=tuple(artifacts),
        science_payload=science_payload,
        figures_payload=figures_payload,
        references_payload=references_payload,
        ear_payload=ear_payload,
        verified_context=verified_context,
        manuscript_profile=manuscript_profile,
        manuscript_context=manuscript_context,
        manuscript_readiness=manuscript_readiness,
        manuscript_briefs=manuscript_briefs,
        manuscript_binding=manuscript_binding,
    )


def model_usage_from_response(response: Any) -> PaperModelUsageV1:
    """Extract reported token/cost metadata without inventing missing values."""

    usage = getattr(response, "usage", None)

    def read(name: str) -> int | None:
        value = (
            usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        )
        return value if isinstance(value, int) and value >= 0 else None

    hidden = getattr(response, "_hidden_params", None)
    cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0:
        cost = None
    return PaperModelUsageV1(
        input_tokens=read("prompt_tokens"),
        output_tokens=read("completion_tokens"),
        cost_usd=float(cost) if cost is not None else None,
        cost_status="reported" if cost is not None else "unavailable",
    )


class AuthoringRecorder:
    """Materialize every stochastic call and immutable TeX revision."""

    def __init__(self, inputs: AuthoringInputs):
        self.inputs = inputs
        self.calls: list[PaperModelCallV1] = []
        self.revisions: list[PaperRevisionV1] = []

    def record_call(
        self,
        *,
        purpose: str,
        prompt: bytes,
        raw_response: bytes,
        response: Any,
        model: str,
        sampling: dict[str, Any],
    ) -> PaperModelCallV1:
        call_id = f"call-{len(self.calls) + 1:03d}"
        directory = f".ari-paper/model-calls/{call_id}"
        prompt_artifact = artifact_from_payload(
            self.inputs.workspace,
            role="prompt",
            relative_path=f"{directory}/prompt.txt",
            payload=prompt,
            media_type="text/plain; charset=utf-8",
        )
        raw_artifact = artifact_from_payload(
            self.inputs.workspace,
            role="raw-model-response",
            relative_path=f"{directory}/response.txt",
            payload=raw_response,
            media_type="text/plain; charset=utf-8",
        )
        revision = os.environ.get("ARI_MODEL_PAPER_REVISION") or None
        provider = os.environ.get("ARI_MODEL_PAPER_PROVIDER") or model.split("/", 1)[0]
        call = PaperModelCallV1.create(
            call_id=call_id,
            purpose=purpose,
            model=model,
            model_revision=revision,
            provider=provider,
            prompt_digest=prompt_artifact.digest,
            prompt_artifact=prompt_artifact,
            raw_response_artifact=raw_artifact,
            sampling=sampling,
            usage=model_usage_from_response(response),
        )
        self.calls.append(call)
        return call

    def record_revision(
        self,
        *,
        tex: str,
        bib: str,
        reason: str,
        call_id: str | None,
        final: bool = False,
    ) -> PaperRevisionV1:
        index = len(self.revisions)
        tex_payload = tex.encode("utf-8")
        role = "final-tex" if final else "draft-tex"
        tex_artifact = artifact_from_payload(
            self.inputs.workspace,
            role=role,
            relative_path=f".ari-paper/revisions/{index:02d}/paper.tex",
            payload=tex_payload,
            media_type="text/x-tex; charset=utf-8",
        )
        bib_artifact = artifact_from_payload(
            self.inputs.workspace,
            role="bibtex",
            relative_path=f".ari-paper/revisions/{index:02d}/refs.bib",
            payload=bib.encode("utf-8"),
            media_type="application/x-bibtex; charset=utf-8",
        )
        anchors = tuple(
            dict.fromkeys(item["anchor"] for item in find_claim_anchors(tex))
        )
        citations = tuple(
            dict.fromkeys(
                key.strip()
                for match in _CITATION.finditer(tex)
                for key in match.group(1).split(",")
                if key.strip()
            )
        )
        path_to_id = {
            path: figure_id for figure_id, path in self.inputs.figures.figures.items()
        }
        figures = tuple(
            dict.fromkeys(
                path_to_id[path] for path in _GRAPHIC.findall(tex) if path in path_to_id
            )
        )
        math_digest = canonical_paper_digest(_MATH.findall(tex))
        revision = PaperRevisionV1.create(
            revision=index,
            parent_revision_digest=(
                self.revisions[-1].revision_digest if self.revisions else None
            ),
            reason=reason,
            tex_artifact=tex_artifact,
            bib_artifact=bib_artifact,
            model_call_id=call_id,
            claim_anchors=anchors,
            citation_keys=citations,
            figure_ids=figures,
            math_digest=math_digest,
        )
        self.revisions.append(revision)
        return revision

    def draft_build(
        self,
        *,
        venue_id: str,
        venue_version: str,
        template_artifact: PaperArtifactV1,
        rubric_id: str,
        rubric_version: str,
        rubric_artifact: PaperArtifactV1,
        compile_record: PaperCompileV1 | None = None,
    ) -> PaperBuildV1:
        build = PaperBuildV1.create(
            build_id=f"paper-{self.inputs.science.run_id}",
            run_id=self.inputs.science.run_id,
            build_revision=0,
            status="draft",
            input_artifacts=(
                *self.inputs.input_artifacts,
                template_artifact,
                rubric_artifact,
            ),
            venue_id=venue_id,
            venue_version=venue_version,
            template_digest=template_artifact.digest,
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            rubric_digest=rubric_artifact.digest,
            ear_digest=self.inputs.input_artifacts[3].digest,
            revisions=tuple(self.revisions),
            model_calls=tuple(self.calls),
            compile=compile_record,
        )
        self.inputs.workspace.atomic_write_bytes(
            ".ari-paper/paper_build.draft.json",
            json_bytes(build.model_dump(mode="json")),
        )
        return build


__all__ = [
    "AuthoringInputs",
    "AuthoringRecorder",
    "artifact_from_payload",
    "artifact_from_workspace",
    "bytes_digest",
    "json_bytes",
    "load_authoring_inputs",
    "model_usage_from_response",
]
