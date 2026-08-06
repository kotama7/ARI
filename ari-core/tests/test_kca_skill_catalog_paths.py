"""The KCA query skills must find their catalogs with nothing configured.

WHY THIS FILE EXISTS. Both `ari-skill-harness` and `ari-skill-knowledge` computed
their repository root as ``Path(__file__).resolve().parents[2].parent`` — one
directory ABOVE the repo, because a skill server already lives at
``<repo>/<package>/src/server.py`` and ``parents[2]`` IS the root.
``ari-skill-paper-re/src/server.py`` has it right at the same depth.

The bug was invisible for the worst possible reason: every failure in these
servers is returned as DATA in a versioned error envelope rather than raised, so
a catalog that could not be found came back as an empty result — the shape of
"nothing is registered", not the shape of "this is misconfigured". A default
deployment therefore told an agent there were no harnesses and no knowledge
skills, and nothing anywhere said otherwise.

These tests pin the resolution itself rather than the arithmetic, so a future
refactor that moves the file is caught by the same assertion.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# package -> the catalog it must resolve to under ari-core/config/
SKILLS = {
    "ari-skill-harness": "harnesses",
    "ari-skill-knowledge": "knowledge_skills",
}


def _server(package: str):
    path = ROOT / package / "src" / "server.py"
    spec = importlib.util.spec_from_file_location(f"_kca_{package.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    """The point is the DEFAULT path, so every override has to be absent."""
    for name in ("ARI_ROOT", "ARI_HARNESS_CATALOG", "ARI_KNOWLEDGE_CATALOG"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("package", sorted(SKILLS))
def test_the_repo_root_is_the_repo_root(package):
    assert _server(package)._repo_root() == ROOT, (
        f"{package} resolves a repository root that is not this repository. A "
        f"skill server lives at <repo>/<package>/src/server.py, so the root is "
        f"parents[2] — a trailing .parent walks out of the tree."
    )


@pytest.mark.parametrize("package,config_dir", sorted(SKILLS.items()))
def test_the_default_catalog_exists(package, config_dir):
    """Resolving to a path is not enough; the path has to be the real catalog."""
    path = _server(package)._catalog_path()
    assert path == ROOT / "ari-core" / "config" / config_dir / "catalog.yaml"
    assert path.is_file(), (
        f"{package}'s default catalog does not exist. Because these servers "
        f"return failures as data, this reads to an agent as 'nothing is "
        f"registered' rather than as a broken deployment."
    )


def test_the_harness_skill_actually_reads_the_registered_harnesses():
    """The end the bug was hiding: a default deployment must see the catalog.

    An empty list here is precisely what the old path produced, and it is
    indistinguishable from a genuinely empty catalog at the tool boundary.
    """
    manifests = _server("ari-skill-harness")._manifests()
    assert manifests, "the harness skill sees no manifests with nothing configured"
    ids = {item["id"] for item in manifests}
    assert ids == {
        "hpc/gemm-correctness",
        "hpc/spmm-correctness",
        "hpc/stencil-correctness",
    }, ids


def test_an_override_still_wins():
    """ARI_ROOT is the documented escape hatch and must keep working."""
    import os

    server = _server("ari-skill-harness")
    os.environ["ARI_ROOT"] = str(ROOT / "ari-core")
    try:
        assert server._repo_root() == (ROOT / "ari-core").resolve()
    finally:
        del os.environ["ARI_ROOT"]


# --- the catalog row must describe the manifest it points at -----------------

def _catalog_copy(tmp_path, mutate):
    import shutil
    import yaml

    src = ROOT / "ari-core" / "config" / "harnesses"
    dst = tmp_path / "harnesses"
    shutil.copytree(src, dst)
    path = dst / "catalog.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_the_shipped_catalog_still_loads():
    from ari.assurance.catalog import load_harness_catalog

    snapshot = load_harness_catalog(
        ROOT / "ari-core" / "config" / "harnesses" / "catalog.yaml")
    assert {m.id for m in snapshot.manifests} == {
        "hpc/gemm-correctness", "hpc/spmm-correctness", "hpc/stencil-correctness"}


def test_a_row_whose_id_does_not_match_its_manifest_is_refused(tmp_path):
    """The `id` column is what a human reads to audit the catalog, and nothing
    compared it against the manifest it names — so a mis-paired row loaded clean
    and a rename there changed nothing."""
    from ari.assurance.catalog import load_harness_catalog

    path = _catalog_copy(tmp_path, lambda raw: raw["entries"][0].__setitem__(
        "id", "this-id-is-a-lie"))
    with pytest.raises(ValueError, match="the row and the manifest disagree"):
        load_harness_catalog(path)


def test_a_row_with_no_id_is_refused(tmp_path):
    """Checked-when-present would be an opt-out by deleting a line — the same
    shape as an optional integrity digest."""
    from ari.assurance.catalog import load_harness_catalog

    path = _catalog_copy(tmp_path, lambda raw: raw["entries"][0].pop("id"))
    with pytest.raises(ValueError, match="cannot be audited"):
        load_harness_catalog(path)
