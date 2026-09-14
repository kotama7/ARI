"""Regression tests for anonymous, digest-only scheduler site identity."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from providers import ProviderProtocolError
from site_privacy import (
    assert_no_private_site_identity,
    assert_repository_site_anonymous,
    load_private_site_config,
)


CHECK_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_site_privacy.py"


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _site() -> dict[str, str]:
    return {
        "schema_version": "ari.openroad-slurm-site/v1",
        "site_nonce": "a" * 64,
        "cluster_name": "private-cluster-fixture-17",
        "partition": "private-partition-fixture-17",
        "node_name": "private-node-fixture-17",
    }


def _repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    (repository / ".gitignore").write_text("/workspace/\n", encoding="utf-8")
    site_path = repository / "workspace/site-v1.json"
    site_path.parent.mkdir()
    site_path.write_text(json.dumps(_site()), encoding="utf-8")
    return repository, site_path


def test_private_site_config_must_be_ignored_and_untracked(tmp_path: Path):
    repository, site_path = _repository(tmp_path)

    assert load_private_site_config(site_path, repository=repository) == _site()

    _git(repository, "add", "-f", "workspace/site-v1.json")
    with pytest.raises(ProviderProtocolError, match="must not be Git-tracked"):
        load_private_site_config(site_path, repository=repository)


def test_private_site_config_requires_high_entropy_nonce(tmp_path: Path):
    repository, site_path = _repository(tmp_path)
    value = _site()
    value["site_nonce"] = "predictable"
    site_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ProviderProtocolError, match="256-bit nonce"):
        load_private_site_config(site_path, repository=repository)


def test_git_candidate_scan_rejects_node_cluster_and_nonce_without_disclosure(
    tmp_path: Path,
):
    repository, site_path = _repository(tmp_path)
    site = load_private_site_config(site_path, repository=repository)
    public = repository / "public.json"
    public.write_text(
        json.dumps(
            {
                "identity_disclosure": "salted-digest-only",
                "site_identity_digest": "sha256:" + "1" * 64,
            }
        ),
        encoding="utf-8",
    )

    assert_repository_site_anonymous(repository, site=site)

    for field in ("node_name", "cluster_name", "site_nonce"):
        public.write_text(
            json.dumps({"accidental_disclosure": site[field]}), encoding="utf-8"
        )
        with pytest.raises(ProviderProtocolError) as raised:
            assert_repository_site_anonymous(repository, site=site)
        assert site[field] not in str(raised.value)


def test_publishable_bundle_rejects_partition_but_global_scan_does_not_guess(
    tmp_path: Path,
):
    repository, site_path = _repository(tmp_path)
    site = load_private_site_config(site_path, repository=repository)
    public = repository / "provider-manifest-v1.json"
    public.write_text(
        json.dumps({"scheduler_partition": site["partition"]}), encoding="utf-8"
    )

    # A generic partition word can occur elsewhere in a repository; the
    # global guard targets uniquely identifying values.  Promotion applies
    # the stricter bounded-token check to its finite publishable bundle.
    assert_repository_site_anonymous(repository, site=site)
    with pytest.raises(ProviderProtocolError, match="field partition"):
        assert_no_private_site_identity((public,), site=site)


def test_git_candidate_filename_cannot_expose_node_name(tmp_path: Path):
    repository, site_path = _repository(tmp_path)
    site = load_private_site_config(site_path, repository=repository)
    leaked = repository / f"report-{site['node_name']}.json"
    leaked.write_text("{}", encoding="utf-8")

    with pytest.raises(ProviderProtocolError, match="field node_name") as raised:
        assert_repository_site_anonymous(repository, site=site)
    assert site["node_name"] not in str(raised.value)


def test_staged_blob_is_checked_even_after_worktree_is_sanitized(tmp_path: Path):
    repository, site_path = _repository(tmp_path)
    site = load_private_site_config(site_path, repository=repository)
    public = repository / "public.json"
    public.write_text(
        json.dumps({"accidental_disclosure": site["node_name"]}), encoding="utf-8"
    )
    _git(repository, "add", "public.json")
    public.write_text(json.dumps({"site_identity": "digest-only"}), encoding="utf-8")

    with pytest.raises(ProviderProtocolError, match="Git index.*node_name") as raised:
        assert_repository_site_anonymous(repository, site=site)
    assert site["node_name"] not in str(raised.value)


def test_git_candidate_symlink_target_cannot_expose_node_name(tmp_path: Path):
    repository, site_path = _repository(tmp_path)
    site = load_private_site_config(site_path, repository=repository)
    leaked = repository / "public-link"
    leaked.symlink_to(Path("runtime") / site["node_name"] / "result.json")

    with pytest.raises(ProviderProtocolError, match="field node_name") as raised:
        assert_repository_site_anonymous(repository, site=site)
    assert site["node_name"] not in str(raised.value)


def test_site_privacy_command_is_fail_closed_and_redacted(tmp_path: Path):
    repository, site_path = _repository(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--repository",
            str(repository),
            "--site-config",
            str(site_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "site-privacy-audit: PASS"

    public = repository / "public.json"
    public.write_text(
        json.dumps({"accidental_disclosure": _site()["node_name"]}),
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--repository",
            str(repository),
            "--site-config",
            str(site_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected.returncode == 1
    assert "site-privacy-audit: FAIL" in rejected.stderr
    assert _site()["node_name"] not in rejected.stderr
