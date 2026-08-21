"""A resume is judged under the admission its own run persisted.

``ari.rqgm.admission`` mints, publishes and re-reads the single record that
fixes a run's Knowledge, Provider and Harness identity, and nothing imported it:
every refusal it contains could be deleted and the suite would stay green.
These drive the production path -- ``build_kca_admission`` ->
``persist_run_admission`` -> ``load_admission_artifacts`` -- against the shipped
catalogs, then bring the same checkpoint a *newer* catalog and require the
resume to keep what the run was admitted under.

Task 20 criteria 12, 28 and 50 state that shape from three sides: a resume does
not resolve against the latest Knowledge catalog, never automatically rebinds to
a newer Provider, and does not resolve against the latest Harness catalog.  The
mechanism is the same one in all three: the admitted digest is authoritative,
and a newer catalog can neither replace it in place nor be re-admitted over it.

The last two tests enter where a resumed run actually enters --
``RQGMRuntime.admit_from_checkpoint`` -- because a record that cannot be
exchanged still says nothing about whether the resume reads it or resolves the
catalogs again.  There the Knowledge, Capability and Harness views the resumed
run will use are read back off the bridges it installs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ari
import ari.config.finder
from ari.config import ARIConfig, SkillConfig
from ari.config.skill_runtime import manifest_runtime_metadata
from ari.mcp.dispatch_support import runtime_tool_ref
from ari.protocols.immutable_store import rendered_json
from ari.protocols.integrity import bytes_digest
from ari.public.research_contract import (
    IdeaCandidateV1,
    IdeaGenerationLockV1,
    IdeaGenerationProvenanceV1,
    IdeaSetV1,
    MetricContractV1,
    MetricCorrectnessV1,
    MetricFormulaProvenanceV1,
    MetricToleranceV1,
    RetrievalRecordV1,
    SurveySnapshotV1,
    canonical_digest,
    mint_research_contract,
)
from ari.rqgm.admission import (
    ADMISSION_FILENAME,
    ADMISSION_RELATIVE_DIR,
    KCARunAdmissionV1,
    load_admission_artifacts,
    load_run_admission,
    persist_run_admission,
)
from ari.rqgm.admission_builder import build_kca_admission
from ari.rqgm.runtime import RQGMRuntime
from ari.skill_lock import build_skills_lock
from ari.skill_manifest import load_skill_manifest

#: The Knowledge Skill the shipped catalog offers for this task tag, the
#: Provider whose reviewed classification satisfies the capabilities it then
#: requires, and the tag that makes the pair applicable at all.  A fixture that
#: admitted nothing would let every assertion below hold over empty sets.
TASK_TAGS = ("dense-linear-algebra", "gemm")
PROVIDER_PACKAGE_DIR = "ari-skill-coding"
RUN_ID = "kca-admission-fixture"


def _repo_root() -> Path:
    """The checkout that holds both ``ari-core`` and the Provider packages."""

    return Path(ari.__file__).resolve().parents[2]


def _research_contract():
    """A mint-once typed Research Contract, the one input admission demands."""

    moment = datetime(2026, 8, 2, tzinfo=timezone.utc)
    record = RetrievalRecordV1(
        canonical_id="s2:paper-1",
        provider="semantic-scholar",
        provider_record_id="paper-1",
        provider_version="graph-v1",
        query="dense gemm optimization",
        retrieved_at=moment,
        title="Prior dense GEMM result",
        payload_digest=canonical_digest({"paperId": "paper-1"}),
    )
    snapshot = SurveySnapshotV1.create(
        mode="record",
        provider="semantic-scholar",
        provider_version="graph-v1",
        query="dense gemm optimization",
        retrieved_at=moment,
        byte_reproducible=False,
        records=(record,),
    )
    generation = IdeaGenerationLockV1.create(
        adapter="default-discussion",
        adapter_version="ari-skill-idea/0.2.0",
        model="provider/model-2026-08",
        prompt_digests=(canonical_digest("prompt-v1"),),
        temperatures=(0.1,),
        seed=7,
        source_snapshot_digest=snapshot.snapshot_digest,
        topic_digest=canonical_digest("dense gemm optimization"),
        experiment_context_digest=canonical_digest(""),
        model_revision="model-2026-08",
    )
    metric = MetricContractV1.create(
        name="gemm_gflops",
        unit="gflops",
        direction="higher",
        comparison_scope="same-environment",
        rationale="Directly measures the proposed dense GEMM speedup.",
        required_evidence=("gemm_gflops", "baseline_gemm_gflops", "max_abs_error"),
        correctness_required=True,
        correctness=MetricCorrectnessV1(
            expr="max_abs_error <= 1e-10", requires=("max_abs_error",)
        ),
        normalization_ceiling="not-applicable",
        formula="value",
        operands={"value": "gemm_gflops"},
        tolerance=MetricToleranceV1(absolute=0.0, relative=0.01),
        formula_provenance=MetricFormulaProvenanceV1(
            source="idea-generation-lock",
            source_digest=generation.generation_lock_digest,
            model=generation.model,
            prompt_digests=generation.prompt_digests,
        ),
        confidence=0.95,
        admission_status="admitted",
    )
    candidate = IdeaCandidateV1.create(
        title="Blocked dense GEMM for the frozen benchmark set",
        hypothesis="Cache blocking raises dense GEMM throughput over the baseline.",
        description="A controlled comparison of a blocked kernel and the baseline.",
        experiment_plan="Run both kernels on the same frozen problem instances.",
        falsification_conditions=(
            "Reject the hypothesis when the blocked kernel does not raise gemm_gflops.",
        ),
        metric_contract=metric,
        citations=(record.canonical_id,),
        limitations=("The conclusion is limited to the frozen problem set.",),
        source_snapshot_digest=snapshot.snapshot_digest,
        generation_lock_digest=generation.generation_lock_digest,
        generator_adapter="default-discussion",
        novelty_score=0.7,
        feasibility_score=0.9,
        overall_score=0.8,
    )
    provenance = IdeaGenerationProvenanceV1(
        lock=generation,
        generated_at=moment,
        output_digest=canonical_digest({"candidate": "blocked-gemm"}),
        requested_adapter="default-discussion",
        actual_adapter="default-discussion",
    )
    return mint_research_contract(
        IdeaSetV1.create(
            topic="dense gemm optimization",
            source_snapshot_digest=snapshot.snapshot_digest,
            generation=provenance,
            candidates=(candidate,),
            selected_candidate_id=candidate.candidate_id,
        )
    )


def _provider_skill() -> SkillConfig:
    """The configured Provider, built from its canonical manifest.

    Package identity and manifest digest have to be the real ones: the Provider
    catalog loader refuses a lock whose manifest does not match the reviewed
    entry, which is what makes the resulting snapshot a real Provider snapshot.
    """

    manifest_path = _repo_root() / PROVIDER_PACKAGE_DIR / "skill.yaml"
    manifest = load_skill_manifest(manifest_path)
    return SkillConfig(
        name=manifest.name,
        path=str(manifest_path.parent),
        phase=["bfts"],
        package=manifest.package,
        version=manifest.version,
        manifest_path=str(manifest_path),
        entrypoint=manifest.entrypoint.module,
        environment_policy=manifest.environment_policy,
        required_env=list(manifest.required_env),
        optional_env=list(manifest.optional_env),
        **manifest_runtime_metadata(manifest),
    )


def _provider_lock(skill: SkillConfig):
    """A run Provider Lock over that Skill's declared tools.

    Live discovery owns the schemas in production; the identity the admission
    pins is the tool set, its policies and the manifest, all of which come from
    the manifest here rather than from a running server.
    """

    schema = {"type": "object"}
    tools = []
    for name in sorted(skill.tool_policies):
        raw = {
            "name": name,
            "skill_name": skill.name,
            "inputSchema": schema,
            "outputSchema": schema,
        }
        raw["tool_ref"] = runtime_tool_ref(skill, raw)
        raw["capability_ref"] = skill.tool_capabilities[name]
        raw["policy"] = skill.tool_policies[name]
        tools.append(raw)
    return build_skills_lock(run_id=RUN_ID, skills=[skill], tools=tools)


class _FrozenMCP:
    """The seam ``build_kca_admission`` uses: a completed Provider Lock."""

    def __init__(self, lock):
        self.skills_lock = lock
        self.installed_view = None

    def list_tools(self, phase: str = "bfts"):  # pragma: no cover - lock is present
        raise AssertionError("admission must not trigger Provider discovery")

    def install_tool_authorization_view(self, view):
        """Receive the authorization view a resume activates.

        The runtime refuses a client that cannot take one, so this is required
        to reach the resume path at all; keeping the view makes the tools the
        resumed run may call observable.
        """

        self.installed_view = view


def _config(skill: SkillConfig) -> ARIConfig:
    cfg = ARIConfig()
    cfg.skills = [skill]
    cfg.knowledge.mode = "audit"
    cfg.capability_binding.mode = "audit"
    cfg.assurance.mode = "audit"
    # The reviewed Harnesses pin this policy's digest; a run that leaves it
    # empty carries the Research Contract's own pair instead, which no
    # Harness can match, so the atoms would be uncoverable by construction.
    cfg.assurance.tolerance_policy = "hpc-floating-point/v1"
    return cfg


@contextmanager
def _config_root(root: Path | None):
    """Point the trusted builder at a catalog root, and pin the problem input.

    ``ARI_PROBLEM`` selects the pinned problem whose ABI restamps the
    Verification Contract's artifact target kind, so an ambient value would make
    the admitted identity depend on the developer's shell rather than on the
    catalogs under test.
    """

    original = ari.config.finder.package_config_root
    saved = os.environ.pop("ARI_PROBLEM", None)
    if root is not None:
        ari.config.finder.package_config_root = lambda: root
    try:
        yield
    finally:
        ari.config.finder.package_config_root = original
        if saved is not None:
            os.environ["ARI_PROBLEM"] = saved


def _admit(checkpoint: Path, *, config_root: Path | None = None):
    """Run the real admission builder for one checkpoint."""

    checkpoint.mkdir(parents=True, exist_ok=True)
    contract = _research_contract()
    (checkpoint / "idea.json").write_text(
        json.dumps(
            {
                "typed_schema_version": "ari.research-contract/v1",
                "research_contract": contract.model_dump(mode="json"),
                "research_contract_digest": contract.contract_digest,
            }
        ),
        encoding="utf-8",
    )
    skill = _provider_skill()
    with _config_root(config_root):
        return build_kca_admission(
            cfg=_config(skill),
            checkpoint_dir=checkpoint,
            run_id=RUN_ID,
            mcp=_FrozenMCP(_provider_lock(skill)),
            foundation_state=None,
            task_tags=TASK_TAGS,
        )


def _bump_catalog_revision(root: Path, relative: str) -> Path:
    """Publish one catalog in ``root`` at a new revision."""

    path = root / relative
    text = path.read_text(encoding="utf-8")
    bumped, count = re.subn(
        r"(?m)^(catalog_source_revision: .*)$", r"\1-newer", text, count=1
    )
    assert count == 1, f"{relative} declares no catalog_source_revision"
    path.write_text(bumped, encoding="utf-8")
    return root


def _newer_catalog_root(destination: Path, relative: str) -> Path:
    """Copy the shipped catalogs and publish one of them at a new revision."""

    with _config_root(None):
        shutil.copytree(ari.config.finder.package_config_root(), destination)
    return _bump_catalog_revision(destination, relative)


def _publish_new_provider_release(root: Path) -> Path:
    """Re-register the run's Provider from a different source commit.

    A revision bump alone renames the catalog; this is the event the criterion
    is about -- the same runtime Provider re-registered from new sources, which
    gives it a new identity digest and therefore a different binding.
    """

    path = root / "providers" / "catalog.yaml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^(\s*full_commit_sha: )([0-9a-f]{40})$", text)
    assert match is not None, "the Provider catalog declares no source commit"
    rotated = match.group(2)[1:] + match.group(2)[0]
    assert rotated != match.group(2)
    path.write_text(
        text[: match.start()] + match.group(1) + rotated + text[match.end() :],
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope="module")
def admitted_run(tmp_path_factory):
    """One run admitted against the shipped catalogs, published atomically."""

    checkpoint = tmp_path_factory.mktemp("admitted-run")
    artifacts = _admit(checkpoint)
    persist_run_admission(checkpoint, artifacts)
    return checkpoint, artifacts


@pytest.fixture(scope="module")
def newer_knowledge(tmp_path_factory):
    root = _newer_catalog_root(
        tmp_path_factory.mktemp("newer-knowledge") / "config",
        "knowledge_skills/catalog.yaml",
    )
    return _admit(tmp_path_factory.mktemp("newer-knowledge-run"), config_root=root)


@pytest.fixture(scope="module")
def newer_providers(tmp_path_factory):
    root = _publish_new_provider_release(
        _newer_catalog_root(
            tmp_path_factory.mktemp("newer-providers") / "config",
            "providers/catalog.yaml",
        )
    )
    return _admit(tmp_path_factory.mktemp("newer-providers-run"), config_root=root)


@pytest.fixture(scope="module")
def newer_harness_root(tmp_path_factory):
    """A catalog root where only the Harness catalog moved past the run."""

    return _newer_catalog_root(
        tmp_path_factory.mktemp("newer-harnesses") / "config",
        "harnesses/catalog.yaml",
    )


@pytest.fixture(scope="module")
def newer_harnesses(tmp_path_factory, newer_harness_root):
    return _admit(
        tmp_path_factory.mktemp("newer-harnesses-run"), config_root=newer_harness_root
    )


@pytest.fixture(scope="module")
def newer_everything(tmp_path_factory):
    """One catalog root where all three catalogs moved past the admitted run.

    The three fixtures above each move one layer, which is what isolates a
    difference to that layer.  A resume is entered once and must keep all three,
    so the resume tests need the state the run would find on a later day: every
    catalog republished, and the run's own Provider re-registered from new
    sources.
    """

    root = _newer_catalog_root(
        tmp_path_factory.mktemp("newer-everything") / "config",
        "knowledge_skills/catalog.yaml",
    )
    _publish_new_provider_release(_bump_catalog_revision(root, "providers/catalog.yaml"))
    _bump_catalog_revision(root, "harnesses/catalog.yaml")
    return root, _admit(
        tmp_path_factory.mktemp("newer-everything-run"), config_root=root
    )


def _resumed(checkpoint: Path):
    return load_admission_artifacts(checkpoint)


def _copy_run(checkpoint: Path, tmp_path: Path) -> Path:
    """An independent copy of an admitted run, safe to damage."""

    target = tmp_path / "resumed-run"
    shutil.copytree(checkpoint, target, symlinks=True)
    return target


def test_admission_publishes_one_pinned_identity_for_all_three_catalogs(admitted_run):
    """The fixture is a real admission, not an empty shell.

    Every assertion in this module is about identity, so a bundle that admitted
    no Skill, snapshotted no Provider and bound no capability would satisfy them
    vacuously.  This states what the shipped catalogs actually produced.
    """

    checkpoint, artifacts = admitted_run
    admission = artifacts.admission
    documents = artifacts.documents

    assert set(admission.artifact_digests) == set(documents)
    assert (checkpoint / ADMISSION_RELATIVE_DIR / ADMISSION_FILENAME).is_file()

    knowledge_lock = documents["knowledge_skill_lock.json"].model_dump(mode="json")
    binding_lock = documents["capability_binding_lock.json"].model_dump(mode="json")
    providers = documents["provider_catalog_snapshot.json"].model_dump(mode="json")
    assert knowledge_lock["admitted"], "no Knowledge Skill was admitted"
    assert providers["providers"], "no reviewed Provider entered the snapshot"
    assert binding_lock["bindings"], "no capability was bound"

    # Each layer's lock names the catalog snapshot it was derived from; that is
    # the edge a resume must not re-derive against a newer catalog.
    assert (
        knowledge_lock["catalog_snapshot_digest"]
        == admission.knowledge_catalog_snapshot_digest
    )
    assert (
        binding_lock["provider_catalog_snapshot_digest"]
        == admission.provider_catalog_snapshot_digest
    )
    assert (
        documents["baseline_harness_lock.json"].model_dump(mode="json")[
            "harness_catalog_snapshot_digest"
        ]
        == admission.harness_catalog_snapshot_digest
    )

    resumed = _resumed(checkpoint)
    assert resumed.admission == admission
    assert set(resumed.documents) == set(documents)
    for name, value in documents.items():
        assert rendered_json(resumed.documents[name]) == rendered_json(value)


def test_resume_reads_the_admitted_knowledge_catalog_not_the_latest(
    admitted_run, newer_knowledge, tmp_path
):
    """Task 20 criterion 12: resume does not resolve against the latest
    Knowledge catalog.

    The run was admitted under one Knowledge catalog; a newer one is then
    published.  Resuming has to keep the admitted snapshot and the Skill lock
    derived from it, the newer snapshot cannot be dropped into the published
    baseline, and the newer bundle cannot be re-admitted over the run.
    """

    checkpoint, artifacts = admitted_run
    admitted = artifacts.admission
    latest = newer_knowledge.admission
    assert (
        latest.knowledge_catalog_snapshot_digest
        != admitted.knowledge_catalog_snapshot_digest
    )
    # Publishing a Knowledge catalog moves the Skill lock derived from it, which
    # is exactly the re-derivation a resume must not perform.
    assert latest.knowledge_skill_lock_digest != admitted.knowledge_skill_lock_digest
    # ... and moves nothing in the other two layers, so a difference observed
    # below is the newer Knowledge catalog and not ambient drift between builds.
    assert (
        latest.provider_catalog_snapshot_digest
        == admitted.provider_catalog_snapshot_digest
    )
    assert (
        latest.harness_catalog_snapshot_digest
        == admitted.harness_catalog_snapshot_digest
    )

    resumed = _resumed(checkpoint)
    assert (
        resumed.admission.knowledge_catalog_snapshot_digest
        == admitted.knowledge_catalog_snapshot_digest
    )
    assert (
        resumed.admission.knowledge_skill_lock_digest
        == admitted.knowledge_skill_lock_digest
    )
    assert resumed.documents["knowledge_catalog_snapshot.json"][
        "catalog_source_revision"
    ] == artifacts.documents["knowledge_catalog_snapshot.json"].catalog_source_revision

    run = _copy_run(checkpoint, tmp_path)
    with pytest.raises(
        ValueError, match="persisted KCA run admission differs from requested admission"
    ):
        persist_run_admission(run, newer_knowledge)

    published = run / ADMISSION_RELATIVE_DIR / "knowledge_catalog_snapshot.json"
    published.write_bytes(
        rendered_json(newer_knowledge.documents["knowledge_catalog_snapshot.json"])
    )
    with pytest.raises(
        ValueError,
        match="admission artifact digest mismatch: knowledge_catalog_snapshot.json",
    ):
        load_admission_artifacts(run)


def test_resume_never_rebinds_to_a_newer_provider_catalog(
    admitted_run, newer_providers, tmp_path
):
    """Task 20 criterion 28: resume never automatically rebinds to a newer
    Provider.

    A Binding Lock names the Provider catalog snapshot and the exact tool
    identities it bound.  Publishing a newer Provider catalog re-derives both;
    a resume that took the re-derivation would have rebound the run's tools
    without anyone admitting them.
    """

    checkpoint, artifacts = admitted_run
    admitted = artifacts.admission
    latest = newer_providers.admission
    assert (
        latest.provider_catalog_snapshot_digest
        != admitted.provider_catalog_snapshot_digest
    )
    # A Binding Lock names the Provider snapshot it bound against; publishing a
    # newer catalog therefore produces a different binding, and taking it would
    # be the automatic rebinding the criterion forbids.
    assert (
        latest.capability_binding_lock_digest != admitted.capability_binding_lock_digest
    )
    assert (
        latest.knowledge_catalog_snapshot_digest
        == admitted.knowledge_catalog_snapshot_digest
    )
    assert (
        latest.harness_catalog_snapshot_digest
        == admitted.harness_catalog_snapshot_digest
    )

    resumed = _resumed(checkpoint)
    assert (
        resumed.admission.provider_catalog_snapshot_digest
        == admitted.provider_catalog_snapshot_digest
    )
    assert (
        resumed.admission.capability_binding_lock_digest
        == admitted.capability_binding_lock_digest
    )
    assert resumed.admission.provider_lock_digest == admitted.provider_lock_digest
    resumed_binding = resumed.documents["capability_binding_lock.json"]
    assert (
        resumed_binding["provider_catalog_snapshot_digest"]
        == admitted.provider_catalog_snapshot_digest
    )
    admitted_binding = artifacts.documents["capability_binding_lock.json"].model_dump(
        mode="json"
    )
    latest_binding = newer_providers.documents["capability_binding_lock.json"].model_dump(
        mode="json"
    )
    bound = {
        (item["capability_ref"], item["tool_ref"], item["provider_identity_digest"])
        for item in admitted_binding["bindings"]
    }
    assert bound == {
        (item["capability_ref"], item["tool_ref"], item["provider_identity_digest"])
        for item in resumed_binding["bindings"]
    }
    # The re-registered Provider carries a new identity digest, so a resume
    # that took the newer catalog would be running the same capabilities under
    # a Provider identity this run never admitted.
    assert bound != {
        (item["capability_ref"], item["tool_ref"], item["provider_identity_digest"])
        for item in latest_binding["bindings"]
    }

    run = _copy_run(checkpoint, tmp_path)
    with pytest.raises(
        ValueError, match="persisted KCA run admission differs from requested admission"
    ):
        persist_run_admission(run, newer_providers)

    published = run / ADMISSION_RELATIVE_DIR / "provider_catalog_snapshot.json"
    published.write_bytes(
        rendered_json(newer_providers.documents["provider_catalog_snapshot.json"])
    )
    with pytest.raises(
        ValueError,
        match="admission artifact digest mismatch: provider_catalog_snapshot.json",
    ):
        load_admission_artifacts(run)


def test_resume_pins_harness_snapshot(
    admitted_run, newer_harnesses, newer_harness_root, tmp_path, no_re_resolution
):
    """Task 20 criterion 50: resume does not resolve against the latest
    Harness catalog.

    What a resume resolves Harnesses from is the persisted catalog snapshot and
    the baseline lock minted against it -- together with the environment
    identity frozen at admission, so a fresher environment does not re-resolve
    the suite either.  Which manifests that suite ends up holding depends on the
    machine the admission ran on and is deliberately not asserted here; the
    identity a resume must not exchange for a newer one is.

    Three sides, because a resume could lose the criterion at any of them: the
    record it reads back, the record it refuses to have replaced, and the live
    Harness view the resumed process actually verifies against.  The last one is
    where the criterion's word *resolve* lives -- a resume that re-entered the
    resolver and happened to keep the old bytes would satisfy the first two --
    so it enters ``admit_from_checkpoint`` with the newer catalog on disk and
    the admission builder wired to fail if it is called at all.

    The fields compared are not listed here.  They are whatever a newer Harness
    catalog actually moved in ``KCARunAdmissionV1``, derived by diffing the two
    admissions, so a field added to the record later is covered without editing
    this test.
    """

    checkpoint, artifacts = admitted_run
    admitted = artifacts.admission
    latest = newer_harnesses.admission
    moved = {
        name
        for name in KCARunAdmissionV1.model_fields
        if getattr(latest, name) != getattr(admitted, name)
    }
    assert moved, "the newer Harness catalog moved no admitted identity to keep"
    assert "harness_catalog_snapshot_digest" in moved
    # The baseline Harness Lock is resolved against a catalog snapshot, so a
    # newer catalog re-resolves it.
    assert "baseline_harness_lock_digest" in moved
    # Only the Harness layer moved, so nothing below is a catalog that happened
    # to stay still.
    assert (
        latest.knowledge_catalog_snapshot_digest
        == admitted.knowledge_catalog_snapshot_digest
    )
    assert (
        latest.provider_catalog_snapshot_digest
        == admitted.provider_catalog_snapshot_digest
    )

    resumed = _resumed(checkpoint)
    for name in sorted(moved):
        assert getattr(resumed.admission, name) == getattr(admitted, name), name
    assert resumed.documents["harness_catalog_snapshot.json"][
        "catalog_source_revision"
    ] == artifacts.documents["harness_catalog_snapshot.json"].catalog_source_revision
    assert (
        resumed.documents["harness_suite.json"]["verification_environment_digest"]
        == admitted.verification_environment_digest
    )
    assert (
        resumed.admission.oracle_bundle_digest == admitted.oracle_bundle_digest
    )

    # The seam a resumed process enters, with the newer Harness catalog the one
    # a fresh resolution would find.
    live = _copy_run(checkpoint, tmp_path / "live")
    runtime, _mcp = _runtime(live)
    with _config_root(newer_harness_root):
        replayed = runtime.admit_from_checkpoint(
            checkpoint_dir=live, run_id=RUN_ID, task_tags=TASK_TAGS
        )
    assert replayed == admitted
    assurance = runtime._assurance_bridge
    assert assurance is not None, "the resumed run installed no Harness view"
    assert assurance.catalog.snapshot_digest == admitted.harness_catalog_snapshot_digest
    assert assurance.baseline.lock_digest == admitted.baseline_harness_lock_digest

    run = _copy_run(checkpoint, tmp_path)
    with pytest.raises(
        ValueError, match="persisted KCA run admission differs from requested admission"
    ):
        persist_run_admission(run, newer_harnesses)

    published = run / ADMISSION_RELATIVE_DIR / "harness_catalog_snapshot.json"
    published.write_bytes(
        rendered_json(newer_harnesses.documents["harness_catalog_snapshot.json"])
    )
    with pytest.raises(
        ValueError,
        match="admission artifact digest mismatch: harness_catalog_snapshot.json",
    ):
        load_admission_artifacts(run)


def _runtime(checkpoint: Path):
    """The runtime a resumed process builds before it opens ``epoch_000``."""

    skill = _provider_skill()
    mcp = _FrozenMCP(_provider_lock(skill))
    runtime = RQGMRuntime(_config(skill), checkpoint, mcp=mcp)
    assert runtime._kca_feature_enabled, "the fixture config disabled every KCA layer"
    return runtime, mcp


@pytest.fixture
def no_re_resolution(monkeypatch):
    """Fail loudly if the resume resolves the catalogs a second time."""

    def refuse(**_kwargs):
        raise AssertionError("resume re-entered the admission builder")

    monkeypatch.setattr(
        "ari.rqgm.admission_builder.build_kca_admission", refuse
    )


def test_resume_activates_the_admitted_catalogs_and_never_the_latest(
    admitted_run, newer_everything, tmp_path, no_re_resolution
):
    """Task 20 criteria 12, 28 and 50 at the seam a resume enters.

    The three tests above prove the persisted record cannot be exchanged for a
    newer one.  They do not say which record the resume reads: a resume that
    re-resolved the catalogs and then used the result would satisfy every one of
    them.  This one calls ``admit_from_checkpoint`` -- what a resumed process
    calls before ``epoch_000`` -- with all three catalogs newer on disk and the
    admission builder wired to fail if it is entered at all, then reads back the
    Knowledge, Capability and Harness identities the resumed run would use.
    """

    checkpoint, artifacts = admitted_run
    admitted = artifacts.admission
    latest_root, latest_artifacts = newer_everything
    latest = latest_artifacts.admission
    # Every layer moved, so keeping the admitted identity below is a choice the
    # resume made and not a catalog that happened not to change.
    assert (
        latest.knowledge_catalog_snapshot_digest
        != admitted.knowledge_catalog_snapshot_digest
    )
    assert latest.knowledge_skill_lock_digest != admitted.knowledge_skill_lock_digest
    assert (
        latest.provider_catalog_snapshot_digest
        != admitted.provider_catalog_snapshot_digest
    )
    assert (
        latest.capability_binding_lock_digest != admitted.capability_binding_lock_digest
    )
    assert (
        latest.harness_catalog_snapshot_digest
        != admitted.harness_catalog_snapshot_digest
    )
    assert latest.baseline_harness_lock_digest != admitted.baseline_harness_lock_digest

    run = _copy_run(checkpoint, tmp_path)
    runtime, mcp = _runtime(run)
    with _config_root(latest_root):
        resumed = runtime.admit_from_checkpoint(
            checkpoint_dir=run, run_id=RUN_ID, task_tags=TASK_TAGS
        )
    assert resumed == admitted

    # What the resumed run will actually select Skills, tools and Harnesses
    # from -- not the record, the live views built out of it.
    knowledge = runtime._knowledge_bridge
    assert knowledge.catalog.snapshot_digest == admitted.knowledge_catalog_snapshot_digest
    assert knowledge.epoch_lock.lock_digest == admitted.knowledge_skill_lock_digest
    assert mcp.installed_view is not None, "no Capability Binding view was activated"
    assert mcp.installed_view.lock_digest == admitted.capability_binding_lock_digest
    assurance = runtime._assurance_bridge
    assert assurance.catalog.snapshot_digest == admitted.harness_catalog_snapshot_digest
    assert assurance.baseline.lock_digest == admitted.baseline_harness_lock_digest


def test_resume_refuses_an_admission_minted_for_a_different_run(
    admitted_run, tmp_path, no_re_resolution
):
    """A baseline is a run's own; another run's is not a starting point.

    The refusal matters because the alternative is not a clean rebuild: the
    checkpoint already holds a published admission, so a resume that ignored the
    run id would carry a foreign Knowledge, Provider and Harness identity into
    this run's epoch.
    """

    checkpoint, _artifacts = admitted_run
    run = _copy_run(checkpoint, tmp_path)
    runtime, _mcp = _runtime(run)
    with pytest.raises(
        ValueError, match="persisted KCA admission belongs to another run"
    ):
        runtime.admit_from_checkpoint(
            checkpoint_dir=run, run_id="a-different-run", task_tags=TASK_TAGS
        )
    assert runtime._run_admission is None


def test_a_document_with_no_cross_field_binding_cannot_be_swapped_either(
    admitted_run, newer_providers, tmp_path
):
    """For part of the bundle the recorded digest is the only protection.

    Admission cross-checks the documents that carry an identity field of their
    own -- a contract digest, a lock digest, a snapshot digest.  The Capability
    Binding request carries none that admission compares, so nothing but the
    per-artifact digest in the admission record stands between a resume and the
    request that a newer Provider catalog produced.
    """

    document = "capability_binding_request.json"
    checkpoint, artifacts = admitted_run
    newer = newer_providers.documents[document]
    assert rendered_json(newer) != rendered_json(artifacts.documents[document])

    run = _copy_run(checkpoint, tmp_path)
    (run / ADMISSION_RELATIVE_DIR / document).write_bytes(rendered_json(newer))
    with pytest.raises(
        ValueError, match=f"admission artifact digest mismatch: {document}"
    ):
        load_admission_artifacts(run)


def test_re_admitting_the_same_bundle_is_idempotent(admitted_run, tmp_path):
    """Resume re-publishes byte-identically or not at all."""

    checkpoint, artifacts = admitted_run
    run = _copy_run(checkpoint, tmp_path)
    final = persist_run_admission(run, artifacts)
    assert final == run / ADMISSION_RELATIVE_DIR
    assert persist_run_admission(run, _resumed(run)) == final


def test_re_admission_over_edited_baseline_bytes_is_refused(admitted_run, tmp_path):
    """An admission whose documents were edited underneath it is not baseline."""

    checkpoint, artifacts = admitted_run
    run = _copy_run(checkpoint, tmp_path)
    published = run / ADMISSION_RELATIVE_DIR / "research_contract.json"
    published.write_bytes(published.read_bytes() + b"\n")
    with pytest.raises(
        ValueError,
        match="persisted KCA admission artifact mismatch: research_contract.json",
    ):
        persist_run_admission(run, artifacts)


def test_a_symlinked_admission_is_never_resumed(admitted_run, tmp_path):
    """Neither the record nor a document may be redirected out of the run."""

    checkpoint, artifacts = admitted_run
    run = _copy_run(checkpoint, tmp_path)
    published = run / ADMISSION_RELATIVE_DIR
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    document = "verification_contract.json"
    moved = elsewhere / document
    moved.write_bytes((published / document).read_bytes())
    (published / document).unlink()
    (published / document).symlink_to(moved)
    with pytest.raises(
        ValueError, match=f"admission artifact symlink refused: {document}"
    ):
        load_admission_artifacts(run)

    record = published / ADMISSION_FILENAME
    moved_record = elsewhere / ADMISSION_FILENAME
    moved_record.write_bytes(record.read_bytes())
    record.unlink()
    record.symlink_to(moved_record)
    with pytest.raises(ValueError, match="KCA run admission symbolic link is refused"):
        load_run_admission(run)


def test_resume_refuses_an_admission_naming_an_unsupported_artifact(
    admitted_run, tmp_path
):
    """The persisted record cannot widen the set of readable documents."""

    checkpoint, artifacts = admitted_run
    run = _copy_run(checkpoint, tmp_path)
    payload = artifacts.admission.model_dump(mode="python")
    payload.pop("admission_digest")
    payload["artifact_digests"] = {
        **artifacts.admission.artifact_digests,
        "unreviewed_document.json": canonical_digest({"unreviewed": True}),
    }
    widened = KCARunAdmissionV1.create(**payload)
    published = run / ADMISSION_RELATIVE_DIR
    (published / ADMISSION_FILENAME).write_bytes(rendered_json(widened))
    (published / "unreviewed_document.json").write_bytes(
        rendered_json({"unreviewed": True})
    )
    with pytest.raises(
        ValueError, match="persisted admission names an unsupported artifact"
    ):
        load_admission_artifacts(run)


def test_a_run_without_an_admission_reports_absence_rather_than_a_default(tmp_path):
    """``admit_from_checkpoint`` distinguishes "not admitted" by this error."""

    with pytest.raises(FileNotFoundError):
        load_run_admission(tmp_path)


# ── Task 20 criterion 33: enforce admission fails below 100% coverage ────────
#
# ``admission_builder`` passes ``enforce_coverage=modes.assurance == "enforce"``
# into the resolver.  The resolver's own refusal is covered elsewhere; what is
# NOT covered is that switch -- pinning it to ``True`` or to ``False`` left
# every test in this repository green.
#
# The shortfall below is authored, not found.  Resolving the shipped contract
# against the shipped catalog can fall short for reasons that belong to the
# registered harnesses and to the host -- an admission that refuses for one of
# those reasons says nothing about the switch, and a run that happens to be
# short everywhere gives no covered control to compare against.  So this run's
# whole Harness layer is written here: one reviewed manifest, one tolerance
# policy, and a property vocabulary whose required properties this test picks.

COVERAGE_POLICY_ID = "coverage-fixture/v1"
COVERED_PROPERTY = "numerical-equivalence"
UNCOVERED_PROPERTY = "deliberately-uncovered-property"
COVERAGE_HARNESS_ID = "fixture/covered-verifier"


def _head_commit() -> str:
    """HEAD of the repository the registration gates consult.

    The source pin is checked for ANCESTRY, so a synthetic sha names nothing
    and the gate correctly refuses to call the manifest reviewed.
    """

    import subprocess

    from ari.assurance.registration_run import repository_root

    done = subprocess.run(
        ["git", "-C", str(repository_root()), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _write_harness_layer(root: Path, *, extra_required_property: str | None):
    """Replace ``root/harnesses`` with a Harness layer this test owns.

    Without *extra_required_property* the contract's every atom is covered by
    the one reviewed manifest.  With it, the contract requires a property no
    manifest declares, so coverage is short by exactly that atom and by nothing
    else: the two roots differ in one vocabulary entry.
    """

    import shutil

    import yaml

    from ari.assurance.catalog import load_harness_catalog
    from ari.assurance.contract import load_tolerance_policy
    from ari.assurance.models import (
        ContainerPinV1,
        HarnessManifestV1,
        HarnessPromotionApprovalV1,
        HarnessPropertyCoverageV1,
        HarnessRegistrationEvidenceV1,
        HarnessResourceRequirementsV1,
        PinnedHarnessAssetV1,
        VerificationScopeV1,
    )
    from ari.assurance.registration import GateEvidence, registration_report

    harnesses = root / "harnesses"
    shutil.rmtree(harnesses)
    (harnesses / "builtin").mkdir(parents=True)
    (harnesses / "policies").mkdir(parents=True)

    policy_path = (
        harnesses / "policies" / (COVERAGE_POLICY_ID.replace("/", "-") + ".yaml")
    )
    policy_path.write_text(
        yaml.safe_dump(
            {
                "id": COVERAGE_POLICY_ID,
                "description": "Fixture tolerance policy for coverage admission.",
                "absolute": 0.0,
                "relative": 1e-9,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _, policy_digest = load_tolerance_policy(policy_path)

    required = [COVERED_PROPERTY]
    if extra_required_property:
        required.append(extra_required_property)
    harnesses.joinpath("property_vocabulary.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "version": "coverage-fixture-properties/v1",
                "properties": {name: ["differential-testing"] for name in required},
                "target_kinds": {name: "shared-library" for name in required},
                "correctness_properties": list(required),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    commit = _head_commit()
    digest_of = canonical_digest

    def asset(revision):
        return PinnedHarnessAssetV1(
            revision=revision, sha256=digest_of(revision), license="MIT"
        )

    manifest = HarnessManifestV1.create(
        id=COVERAGE_HARNESS_ID,
        version="1.0.0",
        kind="artifact_verifier",
        status="verified",
        description="Fixture verifier for the admission coverage switch",
        maintainer="ari",
        tags=("fixture",),
        subject_types=("program",),
        target_kinds=("shared-library",),
        accepts_external_target=True,
        supported_languages=("c",),
        supported_hardware=("cpu",),
        supported_architectures=("x86_64",),
        supported_dtypes=("float64",),
        supported_domains=("fixture",),
        properties=(
            HarnessPropertyCoverageV1(
                property_id=COVERED_PROPERTY,
                methods=("differential-testing",),
                tiers=("screen", "validate", "certify"),
                scope=VerificationScopeV1(values={}),
                tolerance_policy_digest=policy_digest,
            ),
        ),
        target_interface_contract="fixture-c-abi/v1",
        target_interface_digest=digest_of("fixture-abi"),
        source_repository="https://example.invalid/harness",
        source_full_commit_sha=commit,
        implementation_license="MIT",
        dataset=asset("dataset-v1"),
        oracle=asset("oracle-v1"),
        driver=asset("driver-v1"),
        model=asset("none"),
        container=ContainerPinV1(
            reference="example.invalid/harness@sha256:1",
            resolved_digest=digest_of("container"),
            license="MIT",
        ),
        network_policy="deny",
        credential_policy="none",
        filesystem_policy="isolated-readonly-target",
        # No declared feature, so this manifest is compatible with whatever
        # execution substrate the host offers: the shortfall under test must be
        # the authored one, never an environment difference.
        resources=HarnessResourceRequirementsV1(
            cpu_cores=1, memory_bytes=1024, accelerators=0, disk_bytes=1024
        ),
        timeout_seconds=60,
        scorer_determinism="deterministic",
        nondeterminism_declaration="none",
        hidden_test_policy="verifier-only",
        oracle_independence="independent",
        tolerance_policy_digest=policy_digest,
        expected_result_schema="ari.native-hpc-result/v1",
        expected_result_schema_digest=digest_of("result-schema"),
        infrastructure_failure_policy="separate",
        retry_limit=1,
        negative_control_report_digest=digest_of("negative-controls"),
        upstream_parity_report_digest=digest_of("upstream-parity"),
    )

    report = registration_report(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        evidence=GateEvidence(
            manifest=manifest,
            parity={
                "driver_digest": manifest.driver.sha256,
                "passed": True,
                "controls": {
                    "clean": {"verdict": "pass", "relative_spread": 0.01, "resolved": True},
                    "negatives": [
                        {"name": "wrong", "verdict": "fail", "detail": "failed the residual bound"},
                    ],
                },
            },
            driver_digest=manifest.driver.sha256,
            report_schema={"$id": "fixture", "properties": {"verdict": {}}},
            report_schema_version=manifest.expected_result_schema,
            report_schema_digest=manifest.expected_result_schema_digest,
            stability={"runs": 3, "relative_spread": 0.02},
            repo_commit=commit,
        ),
    )
    assert report.decision == "eligible-for-verified", report.decision

    evidence_bytes = '"coverage-fixture-registration-evidence"'
    harnesses.joinpath("builtin", "fixture.json").write_text(
        evidence_bytes, encoding="utf-8"
    )
    evidence = HarnessRegistrationEvidenceV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        manifest_digest=manifest.manifest_digest,
        source_full_commit_sha=commit,
        environment_digest=digest_of("coverage-fixture-environment"),
        evidence_artifact_digests={
            "builtin/fixture.json": bytes_digest(evidence_bytes.encode("utf-8"))
        },
        attestation_digests=(digest_of("coverage-fixture-attestation"),),
        clean_control_verdict="pass",
        negative_control_verdict="fail",
        official_runner_parity=True,
        result_schema_conformant=True,
        network_isolation="proved",
        target_write_isolation="proved",
        oracle_visibility="denied",
        run_count=3,
    )
    approval = HarnessPromotionApprovalV1.create(
        harness_id=manifest.id,
        harness_version=manifest.version,
        actor_kind="human-maintainer",
        actor_id="test-maintainer",
        authorization_basis="coverage admission fixture",
        approved_date="2026-08-05",
        harness_manifest_digest=manifest.manifest_digest,
        registration_report_digest=report.report_digest,
        evidence_bundle_digest=evidence.evidence_digest,
    )
    harnesses.joinpath("builtin", "fixture.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    harnesses.joinpath("builtin", "fixture.registration.json").write_text(
        report.model_dump_json(), encoding="utf-8"
    )
    harnesses.joinpath("builtin", "fixture.evidence.json").write_text(
        evidence.model_dump_json(), encoding="utf-8"
    )
    harnesses.joinpath("builtin", "fixture.approval.json").write_text(
        approval.model_dump_json(), encoding="utf-8"
    )
    harnesses.joinpath("catalog.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "catalog_source_revision": "coverage-fixture/v1",
                "driver_protocol_version": "ari.harness-driver/v1",
                "entries": [
                    {
                        "id": manifest.id,
                        "manifest": "builtin/fixture.yaml",
                        "registration_report": "builtin/fixture.registration.json",
                        "registration_report_digest": report.report_digest,
                        "registration_evidence": "builtin/fixture.evidence.json",
                        "registration_evidence_digest": evidence.evidence_digest,
                        "promotion_approval": "builtin/fixture.approval.json",
                        "promotion_approval_digest": approval.approval_digest,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot = load_harness_catalog(harnesses / "catalog.yaml")
    assert [item.id for item in snapshot.manifests] == [COVERAGE_HARNESS_ID]
    assert snapshot.manifests[0].status == "verified", (
        "the fixture catalog holds no reviewed Harness, so nothing could cover "
        "anything and every admission below would refuse for that reason"
    )
    return root


def _coverage_root(tmp_path: Path, name: str, *, extra_required_property=None) -> Path:
    import shutil

    destination = tmp_path / name / "config"
    with _config_root(None):
        shutil.copytree(ari.config.finder.package_config_root(), destination)
    return _write_harness_layer(
        destination, extra_required_property=extra_required_property
    )


def _admit_under_assurance(checkpoint: Path, root: Path, mode: str):
    """One admission at *mode*, over the Harness layer in *root*."""

    checkpoint.mkdir(parents=True, exist_ok=True)
    contract = _research_contract()
    (checkpoint / "idea.json").write_text(
        json.dumps(
            {
                "typed_schema_version": "ari.research-contract/v1",
                "research_contract": contract.model_dump(mode="json"),
                "research_contract_digest": contract.contract_digest,
            }
        ),
        encoding="utf-8",
    )
    skill = _provider_skill()
    cfg = _config(skill)
    # Knowledge is off so the Verification Contract's requirements are exactly
    # the correctness properties this fixture's vocabulary names, and nothing
    # a Knowledge Skill happens to oblige.
    cfg.knowledge.mode = "off"
    cfg.assurance.mode = mode
    cfg.assurance.tolerance_policy = COVERAGE_POLICY_ID
    with _config_root(root):
        return build_kca_admission(
            cfg=cfg,
            checkpoint_dir=checkpoint,
            run_id=RUN_ID,
            mcp=_FrozenMCP(_provider_lock(skill)),
            foundation_state=None,
            task_tags=(),
        )


def test_required_coverage_fail_closed(tmp_path):
    """Task 20 criterion 33: enforce admission fails below 100% coverage.

    THE COVERED CONTROL comes first.  ``enforce`` over a Harness layer that
    covers every required atom admits the run and mints a baseline Lock, so the
    refusal below is not "enforce refuses".

    THE DELIBERATE SHORTFALL is one extra required property that no manifest
    declares -- the only difference between the two config roots.  Under
    ``enforce`` the admission refuses and names the atom; under ``audit``, over
    the SAME root, the admission succeeds and records that atom as unsatisfied
    while still covering the other one.

    Same inputs, two answers, and the answer follows the assurance posture:
    that is the switch.  Pinning it to ``True`` breaks the audit case, pinning
    it to ``False`` breaks the enforce case.  The refused atoms are compared
    against the ones ``audit`` recorded rather than against a digest written
    here, so the two halves have to be talking about the same shortfall.
    """

    from ari.assurance.resolver import HarnessResolutionError

    covered = _coverage_root(tmp_path, "covered")
    admitted = _admit_under_assurance(tmp_path / "covered-run", covered, "enforce")
    suite = admitted.documents["harness_suite.json"]
    lock = admitted.documents["baseline_harness_lock.json"]
    assert suite.requirements, "the control contract required nothing at all"
    assert suite.unsatisfied_atom_digests == ()
    assert set(suite.covered_atom_digests) == {
        item.atom_digest for item in suite.requirements
    }
    assert [item.harness_id for item in lock.harnesses] == [COVERAGE_HARNESS_ID]

    short = _coverage_root(
        tmp_path, "short", extra_required_property=UNCOVERED_PROPERTY
    )

    audited = _admit_under_assurance(tmp_path / "short-audit", short, "audit")
    audited_suite = audited.documents["harness_suite.json"]
    unsatisfied = set(audited_suite.unsatisfied_atom_digests)
    assert unsatisfied, "the authored shortfall did not make any atom uncoverable"
    assert set(audited_suite.covered_atom_digests), (
        "the shortfall removed ALL coverage; a total loss would also refuse "
        "under enforce, which is not the case the criterion is about"
    )
    assert unsatisfied < {item.atom_digest for item in audited_suite.requirements}
    assert audited.documents["baseline_harness_lock.json"].harnesses, (
        "audit admitted the run without locking the coverage it did have"
    )

    with pytest.raises(HarnessResolutionError) as refusal:
        _admit_under_assurance(tmp_path / "short-enforce", short, "enforce")
    message = str(refusal.value)
    assert "unsatisfied Harness coverage" in message
    assert {digest for digest in unsatisfied if digest in message} == unsatisfied, (
        "the enforce refusal does not name the atoms audit recorded as short"
    )
