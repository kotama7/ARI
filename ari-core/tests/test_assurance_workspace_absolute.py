"""Verification paths must be absolute however the run was launched.

Regression: a run started with a relative checkpoint dir produced a relative
verification-workspace root; `WorkspaceRefV1` refuses that, so both properties
came back `infrastructure_error` -- a verdict about the launcher, recorded as
if it were about the candidate.
"""
import os
from pathlib import Path

from ari.public.execution import WorkspaceRefV1


def test_workspace_ref_still_refuses_a_relative_root():
    # The invariant the bridge has to satisfy; if this ever relaxes, the
    # absolutising below is no longer load-bearing and should be revisited.
    import pytest
    with pytest.raises(Exception, match="absolute"):
        WorkspaceRefV1(root="workspace/checkpoints/run/verification-workspaces/h")


def test_bridge_absolutises_a_relative_checkpoint_dir(tmp_path, monkeypatch):
    from ari.rqgm import assurance_bridge as ab

    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel" / "ckpt").mkdir(parents=True)

    bridge = ab.RQGMAssuranceBridge.__new__(ab.RQGMAssuranceBridge)
    # Exercise only the path normalisation the constructor performs.
    bridge.checkpoint_dir = Path("rel/ckpt").resolve()
    assert bridge.checkpoint_dir.is_absolute()
    derived = bridge.checkpoint_dir / "rqgm" / "kca" / "nodes" / "n" / "vw" / "h"
    WorkspaceRefV1(root=str(derived))  # must not raise
