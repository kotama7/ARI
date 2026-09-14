"""The scoring path must point the governed Harness at what it scored.

The regression: nothing in the repository wrote ``assurance_target.json``. A
governed run therefore resolved its Harness, locked it, and recorded
``tampered`` with no verdicts on every node, because the verifier had no target
declaration to load. The scoring path measures a driver EXECUTABLE; the Harness
verifies a shared LIBRARY.
"""
import os

import pytest

from ari.evaluator import assurance_measure as am

pytestmark = pytest.mark.skipif(
    not os.environ.get("ARI_PROBLEM"),
    reason="needs a pinned problem; the module refuses to guess one",
)


def test_declaration_names_a_library_that_exists_with_a_live_digest(tmp_path):
    work = tmp_path / "node"
    work.mkdir()
    am.seed_work_dir(work)
    document = am.declare_target(work)
    assert document is not None
    library = work / document["logical_name"]
    assert library.is_file(), "the declaration must point at a real artifact"

    from ari.assurance.request import load_target_declaration
    from ari.public.execution import WorkspaceRefV1

    # The loader re-digests the named file and refuses a stale declaration.
    declaration = load_target_declaration(WorkspaceRefV1(root=str(work)))
    assert declaration.target_digest == document["target_digest"]


def test_a_stale_declaration_is_refused(tmp_path):
    work = tmp_path / "node"
    work.mkdir()
    am.seed_work_dir(work)
    document = am.declare_target(work)
    (work / document["logical_name"]).write_bytes(b"not the library that was scored")

    from ari.assurance.request import HarnessRequestError, load_target_declaration
    from ari.public.execution import WorkspaceRefV1

    with pytest.raises(HarnessRequestError, match="stale digest"):
        load_target_declaration(WorkspaceRefV1(root=str(work)))
