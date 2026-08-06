"""External adapters are pin-checking facades, never local benchmark forks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ari.assurance.drivers import builtin_driver_map
from ari.assurance.drivers.external import (
    ExternalHarnessParityReportV1,
    ExternalParityCheckV1,
)
from ari.assurance.drivers.harbor import HarborDriver
from ari.assurance.drivers.inspect import InspectDriver
from ari.assurance.drivers.paperbench import PaperBenchDriver
from ari.assurance.drivers.upstream import UpstreamCLIDriver


def test_external_driver_map_has_distinct_reviewed_identities():
    drivers = builtin_driver_map()
    assert len(drivers) == 5
    for revision, driver in drivers.items():
        identity = driver.identity()
        assert identity["driver_revision"] == revision
        assert identity["driver_digest"].startswith("sha256:")
        assert len(identity["driver_digest"]) == 71


@pytest.mark.parametrize(
    ("driver", "harness_id", "argv"),
    [
        (InspectDriver(), "science/scicode", ("inspect", "eval", "scicode.py")),
        (HarborDriver(), "science/scienceagentbench", ("harbor", "run", "scienceagentbench")),
        (PaperBenchDriver(), "reproduction/paperbench", ("python3", "paperbench_assurance_worker.py")),
        (UpstreamCLIDriver(), "gpu/kernelbench", ("python3", "scripts/run_and_check.py")),
    ],
)
def test_external_driver_accepts_only_reviewed_official_route(driver, harness_id, argv):
    driver.validate_locked_argv(SimpleNamespace(id=harness_id), argv)
    with pytest.raises(ValueError):
        driver.validate_locked_argv(SimpleNamespace(id=harness_id), ("bash", "arbitrary.sh"))


def test_external_driver_parity_is_explicitly_unavailable_without_pinned_report():
    manifest = SimpleNamespace(
        id="science/scicode",
        manifest_digest="sha256:" + "1" * 64,
        source_full_commit_sha="2" * 40,
        dataset=SimpleNamespace(sha256="sha256:" + "3" * 64),
        container=SimpleNamespace(resolved_digest="sha256:" + "4" * 64),
        driver=SimpleNamespace(sha256="sha256:" + "5" * 64),
    )
    report = InspectDriver().parity_probe(manifest)
    assert report["status"] == "not_available"
    assert report["passed"] is False


def _manifest():
    return SimpleNamespace(
        id="science/scicode",
        manifest_digest="sha256:" + "1" * 64,
        source_full_commit_sha="2" * 40,
        dataset=SimpleNamespace(sha256="sha256:" + "3" * 64),
        container=SimpleNamespace(resolved_digest="sha256:" + "4" * 64),
        driver=SimpleNamespace(sha256="sha256:" + "5" * 64),
    )


def test_partial_upstream_compatibility_cannot_be_promoted_to_official_parity():
    manifest = _manifest()
    report = ExternalHarnessParityReportV1.create(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        source_revision=manifest.source_full_commit_sha,
        dataset_digest=manifest.dataset.sha256,
        container_digest=manifest.container.resolved_digest,
        driver_digest=manifest.driver.sha256,
        reference_verdict="not_available",
        negative_control_verdict="not_available",
        result_schema_parity=False,
        official_runner_parity=False,
        status="not_available",
        unavailable_reasons=("pinned official container is unavailable",),
        non_authoritative_checks=(
            ExternalParityCheckV1(
                check_id="upstream-api-import",
                status="passed",
                evidence_digest="sha256:" + "6" * 64,
                detail="API import is not an end-to-end official runner result",
            ),
        ),
    )
    observed = InspectDriver(parity_reports={manifest.id: report}).parity_probe(
        manifest
    )
    assert observed["status"] == "not_available"
    assert observed["passed"] is False
    assert observed["non_authoritative_checks"][0]["status"] == "passed"


def test_complete_digest_bound_official_parity_passes():
    manifest = _manifest()
    report = ExternalHarnessParityReportV1.create(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        source_revision=manifest.source_full_commit_sha,
        dataset_digest=manifest.dataset.sha256,
        container_digest=manifest.container.resolved_digest,
        driver_digest=manifest.driver.sha256,
        official_runner_invocation_digest="sha256:" + "6" * 64,
        official_result_digest="sha256:" + "7" * 64,
        normalized_result_digest="sha256:" + "8" * 64,
        reference_verdict="pass",
        negative_control_verdict="fail",
        result_schema_parity=True,
        official_runner_parity=True,
        status="passed",
    )
    observed = InspectDriver(parity_reports={manifest.id: report}).parity_probe(
        manifest
    )
    assert observed["status"] == "passed"
    assert observed["passed"] is True


def test_parity_report_pin_drift_and_malformed_pass_fail_closed():
    manifest = _manifest()
    report = ExternalHarnessParityReportV1.create(
        harness_id=manifest.id,
        manifest_digest=manifest.manifest_digest,
        source_revision=manifest.source_full_commit_sha,
        dataset_digest=manifest.dataset.sha256,
        container_digest=manifest.container.resolved_digest,
        driver_digest=manifest.driver.sha256,
        official_runner_invocation_digest="sha256:" + "6" * 64,
        official_result_digest="sha256:" + "7" * 64,
        normalized_result_digest="sha256:" + "8" * 64,
        reference_verdict="pass",
        negative_control_verdict="fail",
        result_schema_parity=True,
        official_runner_parity=True,
        status="passed",
    )
    drifted = SimpleNamespace(**{**manifest.__dict__, "manifest_digest": "sha256:" + "9" * 64})
    assert (
        InspectDriver(parity_reports={manifest.id: report})
        .parity_probe(drifted)["status"]
        == "failed"
    )
    forged = report.model_dump(mode="json")
    forged["report_digest"] = "sha256:" + "0" * 64
    observed = InspectDriver(parity_reports={manifest.id: forged}).parity_probe(
        manifest
    )
    assert observed["status"] == "failed"
    assert "malformed" in observed["reason"]


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"source_revision": "abc123"}, "source_revision"),
        ({"dataset_digest": "sha256:" + "0" * 64}, "passed parity"),
    ],
)
def test_passed_parity_rejects_unpinned_revision_and_placeholder_digest(
    override, match
):
    manifest = _manifest()
    values = {
        "harness_id": manifest.id,
        "manifest_digest": manifest.manifest_digest,
        "source_revision": manifest.source_full_commit_sha,
        "dataset_digest": manifest.dataset.sha256,
        "container_digest": manifest.container.resolved_digest,
        "driver_digest": manifest.driver.sha256,
        "official_runner_invocation_digest": "sha256:" + "6" * 64,
        "official_result_digest": "sha256:" + "7" * 64,
        "normalized_result_digest": "sha256:" + "8" * 64,
        "reference_verdict": "pass",
        "negative_control_verdict": "fail",
        "result_schema_parity": True,
        "official_runner_parity": True,
        "status": "passed",
    }
    values.update(override)
    with pytest.raises(ValueError, match=match):
        ExternalHarnessParityReportV1.create(**values)


def test_external_driver_has_no_fuzzy_harness_id_fallback():
    with pytest.raises(KeyError):
        InspectDriver().validate_locked_argv(
            SimpleNamespace(id="science/scicode-lookalike"),
            ("inspect", "eval", "scicode.py"),
        )
