"""`<checkpoint>/provenance.json` — the record that makes a published number re-checkable.

The goal this serves: a reader holding only the published **workspace** and the
**ARI repo** can confirm which instrument produced a score. The workspace already
carried the harness bytes (``uploads/`` copies them), but nothing bound those
bytes to the scores, and nothing named the ARI commit or the knobs the harness
read. Digests were computed and dropped.

Two things are load-bearing here and easy to get wrong:

* **Redaction.** This file ships inside an artifact the user intends to publish.
  A secret value or an absolute path in it is a leak at publish time — and a path
  is worthless to a reader re-checking the number on another machine anyway.
* **Round-trip.** Recording a digest is pointless unless it can be recomputed from
  the published workspace and compared. The last test does exactly that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ari.cli.bfts_loop import (
    _measurement_env,
    _write_run_provenance,
    _PROVENANCE_FILENAME,
)
from ari.harness_registry import load, sha256_file, workspace_harness_root
from ari.paths import PathManager

HARNESS_PY = (
    "def kernels_dir():\n"
    "    import os\n"
    "    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k')\n"
    "def seed_work_dir(work_dir):\n"
    "    return ['driver.c']\n"
    "def measure_node(work_dir, **kw):\n"
    "    return {'compile_ok': True, 'families': {}}\n"
)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """A registered harness in an isolated workspace."""
    monkeypatch.setenv("ARI_WORKSPACE", str(tmp_path / "ws"))
    d = workspace_harness_root() / "t"
    (d / "k").mkdir(parents=True)
    (d / "k" / "driver.c").write_text("int main(void){return 0;}\n")
    (d / "t_harness.py").write_text(HARNESS_PY)
    pins = {p: sha256_file(d / p) for p in ("k/driver.c", "t_harness.py")}
    (d / "harness.toml").write_text(
        '[harness]\nentry = "t_harness.py"\ntarget = 256.0\nscale = "log"\n'
        'axis = "speedup"\n\n[files]\n'
        + "".join(f'"{k}" = "{v}"\n' for k, v in pins.items())
    )
    return load("t")


def _write(tmp_path, harness) -> dict:
    _write_run_provenance(str(tmp_path / "ckpt"), harness)
    return json.loads((tmp_path / "ckpt" / _PROVENANCE_FILENAME).read_text())


# --------------------------------------------------------------------------
# What gets recorded
# --------------------------------------------------------------------------

def test_records_the_harness_that_produced_the_run(tmp_path, harness):
    p = _write(tmp_path, harness)["harness"]
    assert p["task"] == "t"
    assert (p["target"], p["scale"], p["axis"]) == (256.0, "log", "speedup")
    assert set(p["files"]) == {"k/driver.c", "t_harness.py"}


def test_origin_is_workspace_relative_not_a_machine_path(tmp_path, harness):
    """The record must name a directory inside the published artifact, not a path
    on the machine that produced it."""
    origin = _write(tmp_path, harness)["harness"]["origin"]
    assert origin == "harnesses/t"
    assert not origin.startswith("/")


def test_records_the_ari_commit(tmp_path, harness):
    """The workspace pins the instrument; this pins the framework around it."""
    ari = _write(tmp_path, harness)["ari"]
    assert len(ari["git_sha"]) == 40
    assert isinstance(ari["dirty"], bool)


def test_records_the_knobs_the_pinned_harness_reads(tmp_path, harness, monkeypatch):
    """Source is pinned by sha256, so source + env determines the compile command.
    Recording the env (not a resolved command line) keeps this harness-agnostic."""
    monkeypatch.setenv("ARI_SEED", "7")
    monkeypatch.setenv("ARI_T_CFLAGS", "-O3 -fopenmp -march=native")
    monkeypatch.setenv("OMP_NUM_THREADS", "16")
    env = _write(tmp_path, harness)["env"]
    assert env["ARI_SEED"] == "7"
    assert env["ARI_T_CFLAGS"] == "-O3 -fopenmp -march=native"
    assert env["OMP_NUM_THREADS"] == "16"


def test_ignores_unrelated_environment(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")
    assert "SOME_UNRELATED_VAR" not in _measurement_env()


def test_is_deterministic_apart_from_the_timestamp(tmp_path, harness):
    a, b = _write(tmp_path, harness), _write(tmp_path, harness)
    a.pop("recorded_at"), b.pop("recorded_at")
    assert a == b


# --------------------------------------------------------------------------
# Redaction — this file ships inside a published artifact
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["ARI_LLM_API_KEY", "ARI_AUTH_TOKEN",
                                 "ARI_CLIENT_SECRET", "ARI_DB_PASSWORD"])
def test_secret_values_are_never_written(tmp_path, harness, monkeypatch, key):
    monkeypatch.setenv(key, "sk-the-actual-secret")
    blob = json.dumps(_write(tmp_path, harness))
    assert "sk-the-actual-secret" not in blob
    assert json.loads(blob)["env"][key] == "<redacted:secret>"


def test_absolute_paths_are_never_written(tmp_path, harness, monkeypatch):
    """A path carries the account and site layout of the producing machine, and
    tells a reader re-checking the number elsewhere nothing."""
    monkeypatch.setenv("ARI_WORK_DIR", "/scratch/fs0/home/users/somebody/node_x")
    blob = json.dumps(_write(tmp_path, harness))
    assert "somebody" not in blob and "/scratch/fs0" not in blob
    assert json.loads(blob)["env"]["ARI_WORK_DIR"] == "<redacted:path>"


def test_redaction_keeps_the_key_so_the_reader_knows_it_was_set(tmp_path, harness,
                                                                monkeypatch):
    """Dropping the key entirely would make "was it set?" unanswerable."""
    monkeypatch.setenv("ARI_CHECKPOINT_DIR", "/somewhere/real")
    assert "ARI_CHECKPOINT_DIR" in _write(tmp_path, harness)["env"]


def test_non_path_values_survive_redaction(tmp_path, harness, monkeypatch):
    """The redaction must not eat the values that determine the measurement."""
    monkeypatch.setenv("ARI_ALLOWED_TOOLS", "write_code,run_bash")
    monkeypatch.setenv("ARI_T_CFLAGS", "-O3 -fopenmp")
    env = _write(tmp_path, harness)["env"]
    assert env["ARI_ALLOWED_TOOLS"] == "write_code,run_bash"
    assert env["ARI_T_CFLAGS"] == "-O3 -fopenmp"


# --------------------------------------------------------------------------
# The record must not become an input to the thing it records
# --------------------------------------------------------------------------

@pytest.mark.parametrize("scope", ["checkpoint", "node"])
def test_provenance_is_metadata_and_never_reaches_a_node(scope):
    """``_run_loop`` copies every NON-meta file at the checkpoint root into each
    node's work_dir. When this file was first added it was not metadata, so every
    node was handed the scoring configuration it is judged by: the TARGET it must
    hit, the scale, the axis, and the harness's location.

    No unit test of the writer could see that — it only appeared when the real
    ``_run_loop`` ran and logged
    ``Copied checkpoint file provenance.json -> .../node_root/provenance.json``.
    """
    assert PathManager.is_meta_file(_PROVENANCE_FILENAME, scope=scope)


def test_the_recorded_target_is_exactly_what_must_not_leak(tmp_path, harness):
    """Guards the test above against being weakened: it is only load-bearing while
    the record actually contains the scoring configuration."""
    rec = _write(tmp_path, harness)["harness"]
    assert {"target", "scale", "axis"} <= set(rec)


# --------------------------------------------------------------------------
# The point of the whole thing
# --------------------------------------------------------------------------

def test_a_reader_can_recompute_every_digest_from_the_workspace(tmp_path, harness):
    """`workspace + repo` re-checks a number: recompute the digests from the
    published workspace and compare them with what the run recorded."""
    rec = _write(tmp_path, harness)["harness"]
    ws = workspace_harness_root().parent
    for rel, want in rec["files"].items():
        assert sha256_file(ws / rec["origin"] / rel) == want


def test_a_tampered_workspace_fails_the_reader_s_check(tmp_path, harness):
    """The record is only worth something if a mismatch is detectable."""
    rec = _write(tmp_path, harness)["harness"]
    ws = workspace_harness_root().parent
    (ws / rec["origin"] / "k" / "driver.c").write_text("int main(void){return 1;}\n")
    mismatched = [rel for rel, want in rec["files"].items()
                  if sha256_file(ws / rec["origin"] / rel) != want]
    assert mismatched == ["k/driver.c"]
