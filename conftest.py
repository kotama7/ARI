"""Repo-root pytest configuration.

WHY THIS FILE EXISTS. ARI decides where it reads and writes from three
environment variables, and production code legitimately WRITES one of them into
``os.environ`` — ``ARI_CHECKPOINT_DIR`` is how a child process is told where the
run lives (``ari/paths.py`` ``set_checkpoint_dir_env``, called from nine places
in the pipeline, the CLI, the viz API and the agent loop). Any test that
exercises one of those paths therefore leaves a temporary directory in the
environment of every test that runs after it, in the same process.

That is not theoretical. ``ARI_CHECKPOINT_DIR`` wins the workspace-root
precedence, so once it points at a deleted ``tmp_path`` the harness registry
resolves its harness root there and reports "no harnesses are registered" — 41
failures across the registered-harness parity suite. Both suites were green run
on their own; the failure existed only in the combination, which is exactly the
arrangement that a bare ``pytest`` at the repo root now runs.

The fixture restores the three variables around every test. It does not stop a
test from setting them (many must), only from leaving them set — which is the
property that makes the suites composable at all.
"""

import os

import pytest

_ROOT_SELECTING_ENV = ("ARI_CHECKPOINT_DIR", "ARI_WORKSPACE", "ARI_ROOT")


@pytest.fixture(autouse=True)
def _isolate_root_selecting_env():
    saved = {name: os.environ.get(name) for name in _ROOT_SELECTING_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
