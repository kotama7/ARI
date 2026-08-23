"""A submitted job must run where the evaluator reads, or fail saying so.

The regression these cover: `slurm_submit` accepted the virtual container root
`/workspace`, the skill passed it straight through, and the job ran in the
submitting process's cwd instead. Every node then wrote its work into the
repository root and was scored on the untouched seed it had inherited.
"""
import pytest

from ari_skill_hpc.server import _submit_work_dir


def test_empty_means_scheduler_default():
    assert _submit_work_dir("") == ""
    assert _submit_work_dir(None) == ""


def test_existing_absolute_directory_passes_through(tmp_path):
    assert _submit_work_dir(str(tmp_path)) == str(tmp_path)


def test_virtual_container_root_is_refused():
    # This skill does no /workspace devirtualization; guessing is what broke.
    with pytest.raises(ValueError, match="virtual container root"):
        _submit_work_dir("/workspace")


def test_relative_path_is_refused():
    with pytest.raises(ValueError, match="absolute path"):
        _submit_work_dir("node_dir")


def test_absent_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not an existing directory"):
        _submit_work_dir(str(tmp_path / "never_created"))
