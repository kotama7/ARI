"""Test that the wizard's include_ear=False toggle disables EAR stages
in the per-checkpoint workflow.yaml without breaking write_paper /
finalize_paper (which depend on generate_ear / ear_curate)."""

import json
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import yaml


def _run_launch(monkeypatch, tmp_path: Path, payload: dict) -> Path:
    """Invoke _api_launch with subprocess mocked; return the new checkpoint dir."""
    from ari.viz import state as _st
    from ari.viz.api_experiment import _api_launch

    monkeypatch.setattr(_st, "_ari_root", tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text("{}")

    with mock.patch("subprocess.Popen") as mock_popen:
        proc = MagicMock()
        proc.pid = 12345
        mock_popen.return_value = proc
        result = _api_launch(json.dumps(payload).encode())

    assert result.get("ok"), f"Launch failed: {result}"
    # Discover the new checkpoint dir under tmp_path/workspace/checkpoints/
    roots = list((tmp_path / "workspace" / "checkpoints").iterdir())
    assert roots, "no checkpoint created"
    return roots[0]


def test_include_ear_true_keeps_ear_stages(monkeypatch, tmp_path):
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
        "include_ear": True,
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    # generate_ear / ear_curate stay enabled (default-true)
    assert stages["generate_ear"].get("enabled", True) is True
    assert stages["ear_curate"].get("enabled", True) is True
    # write_paper still depends on generate_ear
    assert "generate_ear" in stages["write_paper"].get("depends_on", [])
    # launch_config.json records the choice
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_ear") is True


def test_include_ear_false_disables_ear_stages(monkeypatch, tmp_path):
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
        "include_ear": False,
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    # EAR stages disabled. ors_seed_sandbox is in this set because it
    # seeds repro_sandbox/ from the EAR publish_record; disabling it forces
    # ors_build_reproduce to drive the LLM Replicator from the paper alone.
    for name in ("generate_ear", "ear_curate", "ear_publish", "ors_seed_sandbox"):
        assert stages[name]["enabled"] is False, f"{name} should be disabled"
    # depends_on stripped of EAR refs so write_paper / finalize_paper still run
    assert "generate_ear" not in stages["write_paper"].get("depends_on", [])
    assert "ear_curate" not in stages["finalize_paper"].get("depends_on", [])
    assert "ors_seed_sandbox" not in stages["ors_build_reproduce"].get("depends_on", [])
    # launch_config.json records the choice
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_ear") is False


def test_include_ear_default_is_true(monkeypatch, tmp_path):
    """Backward compat: payload without include_ear keeps EAR stages enabled."""
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    assert stages["generate_ear"].get("enabled", True) is True
    assert "generate_ear" in stages["write_paper"].get("depends_on", [])


def test_include_review_false_disables_review_stages(monkeypatch, tmp_path):
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
        "include_review": False,
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    for name in ("review_paper", "merge_reviews"):
        assert stages[name]["enabled"] is False, f"{name} should be disabled"
    # EAR / reproduce stages stay on so the rest of the paper pipeline still runs
    assert stages["generate_ear"].get("enabled", True) is True
    assert stages["ors_build_reproduce"].get("enabled", True) is True
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_review") is False
    assert cfg.get("include_ear") is True
    assert cfg.get("include_reproduce") is True


def test_include_reproduce_false_disables_ors_stages(monkeypatch, tmp_path):
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
        "include_reproduce": False,
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    for name in (
        "ors_generate_rubric",
        "ors_seed_sandbox",
        "ors_build_reproduce",
        "ors_run_reproduce",
        "ors_grade",
    ):
        assert stages[name]["enabled"] is False, f"{name} should be disabled"
    # Review / EAR untouched
    assert stages["review_paper"].get("enabled", True) is True
    assert stages["generate_ear"].get("enabled", True) is True
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_reproduce") is False
    assert cfg.get("include_review") is True
    assert cfg.get("include_ear") is True


def test_phase_toggles_compose(monkeypatch, tmp_path):
    """Disabling EAR + review + reproduce together strips every dependent edge."""
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
        "include_ear": False,
        "include_review": False,
        "include_reproduce": False,
    })
    wf = yaml.safe_load((ckpt / "workflow.yaml").read_text())
    stages = {s["stage"]: s for s in wf.get("pipeline", [])}
    disabled = {
        "generate_ear", "ear_curate", "ear_publish",
        "review_paper", "merge_reviews",
        "ors_generate_rubric", "ors_seed_sandbox",
        "ors_build_reproduce", "ors_run_reproduce", "ors_grade",
    }
    for name in disabled:
        assert stages[name]["enabled"] is False, f"{name} should be disabled"
    # write_paper / finalize_paper / generate_figures must still be runnable
    for name in ("write_paper", "finalize_paper", "generate_figures"):
        assert stages[name].get("enabled", True) is True
        for dep in stages[name].get("depends_on", []) or []:
            assert dep not in disabled, f"{name} still depends on disabled {dep}"
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_ear") is False
    assert cfg.get("include_review") is False
    assert cfg.get("include_reproduce") is False


def test_phase_toggles_default_all_true(monkeypatch, tmp_path):
    """Without any toggle in the payload, launch_config records all three as True."""
    ckpt = _run_launch(monkeypatch, tmp_path, {
        "experiment_md": "## Test\nHello",
    })
    cfg = json.loads((ckpt / "launch_config.json").read_text())
    assert cfg.get("include_ear") is True
    assert cfg.get("include_review") is True
    assert cfg.get("include_reproduce") is True


def test_language_env_propagation(monkeypatch, tmp_path):
    """The wizard's Language dropdown must reach the paper-skill via
    ARI_PAPER_LANGUAGE, and the choice is persisted to launch_config.json."""
    captured_env: dict[str, str] = {}

    def _popen_stub(*args, **kwargs):
        # Capture the env handed to the subprocess so we can assert on
        # ARI_PAPER_LANGUAGE without actually launching ari.cli.
        captured_env.update(kwargs.get("env") or {})
        m = MagicMock()
        m.pid = 12345
        return m

    from ari.viz import state as _st
    from ari.viz.api_experiment import _api_launch
    monkeypatch.setattr(_st, "_ari_root", tmp_path)
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_settings_path", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text("{}")

    with mock.patch("subprocess.Popen", side_effect=_popen_stub):
        result = _api_launch(json.dumps({
            "experiment_md": "## Test\nHello",
            "language": "ja",
        }).encode())

    assert result.get("ok"), f"Launch failed: {result}"
    assert captured_env.get("ARI_PAPER_LANGUAGE") == "ja"
    roots = list((tmp_path / "workspace" / "checkpoints").iterdir())
    cfg = json.loads((roots[0] / "launch_config.json").read_text())
    assert cfg.get("language") == "ja"


def _import_paper_server():
    """Import ``ari-skill-paper/src/server.py`` as a fresh ``server`` module.

    Several other tests (``test_ear.py`` / ``test_nodes_to_science_data_shrink.py``)
    also import a ``src/server.py`` under the unqualified ``server`` name,
    but pointing at ``ari-skill-transform``. Without invalidating the
    ``sys.modules`` cache first, whichever test ran earlier wins and the
    others import the wrong module. Mirror the cache-clear pattern the
    other tests already use so order-of-execution stops mattering.
    """
    import importlib
    import sys

    paper_src = str(Path(__file__).resolve().parents[2] / "ari-skill-paper" / "src")
    if paper_src in sys.path:
        sys.path.remove(paper_src)
    sys.path.insert(0, paper_src)
    if "server" in sys.modules:
        del sys.modules["server"]
    return importlib.import_module("server")


def test_paper_skill_language_directive_english_is_noop(monkeypatch):
    """English (default) must NOT inject a language directive, preserving
    the historical prompt verbatim — otherwise every existing prompt
    snapshot test would have to change at once."""
    monkeypatch.setenv("ARI_PAPER_LANGUAGE", "en")
    srv = _import_paper_server()
    assert srv._paper_language_directive() == ""


def test_paper_skill_language_directive_japanese(monkeypatch):
    monkeypatch.setenv("ARI_PAPER_LANGUAGE", "ja")
    srv = _import_paper_server()
    out = srv._paper_language_directive()
    assert "Japanese" in out
    # Must mention a babel/preamble package so the LaTeX actually compiles.
    assert "bxcjkjatype" in out or "CJKutf8" in out


def test_paper_skill_language_directive_chinese(monkeypatch):
    monkeypatch.setenv("ARI_PAPER_LANGUAGE", "zh")
    srv = _import_paper_server()
    out = srv._paper_language_directive()
    assert "Chinese" in out
    assert "CJKutf8" in out


def test_cli_run_does_not_overwrite_checkpoint_workflow(tmp_path, monkeypatch):
    """Regression: cli.run must not overwrite a pre-existing per-checkpoint
    workflow.yaml. The GUI launcher writes a rewritten copy (e.g. EAR /
    ors_seed_sandbox disabled when include_ear=False), and an unconditional
    ``shutil.copy2`` from the package source would silently undo that — the
    bug observed on checkpoint 20260505111819_…."""
    from unittest import mock
    from typer.testing import CliRunner

    from ari.cli import app

    exp = tmp_path / "experiment.md"
    exp.write_text("Some goal\n")
    pre_ckpt = tmp_path / "20260505_sentinel_ckpt"
    pre_ckpt.mkdir()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "llm:\n  model: fake\n"
        f"checkpoint:\n  dir: {pre_ckpt}\n"
        f"logging:\n  dir: {pre_ckpt}\n"
    )
    # Sentinel content the launcher would have written.
    sentinel = "pipeline:\n  - stage: SENTINEL_FROM_LAUNCHER\nskills: []\n"
    (pre_ckpt / "workflow.yaml").write_text(sentinel)

    monkeypatch.setenv("ARI_CHECKPOINT_DIR", str(pre_ckpt))

    with mock.patch("ari.cli.build_runtime") as mock_rt, \
         mock.patch("ari.cli._run_loop", return_value=0), \
         mock.patch("ari.cli.generate_paper_section"):
        mock_rt.return_value = (
            None, None, None, mock.MagicMock(), mock.MagicMock(), None,
        )
        result = CliRunner().invoke(app, ["run", str(exp), "--config", str(cfg)])

    assert result.exit_code == 0, (
        f"cli.run crashed: exit={result.exit_code}\n{result.output}\n{result.exception!r}"
    )
    assert (pre_ckpt / "workflow.yaml").read_text() == sentinel, (
        "cli.run must not overwrite an existing per-checkpoint workflow.yaml"
    )


def test_generate_paper_section_prefers_checkpoint_workflow(tmp_path):
    """Regression: ``generate_paper_section`` must resolve the per-checkpoint
    ``workflow.yaml`` ahead of the package source, so launch-time rewrites
    actually drive the paper pipeline (EAR / ors_seed_sandbox disabling).
    Symmetrical with the BFTS phase, which already reads the checkpoint
    copy at cli.py:478."""
    from unittest import mock

    from ari.core import generate_paper_section

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "workflow.yaml").write_text(
        "pipeline:\n  - stage: marker_ckpt\n    skill: x\n    tool: y\nskills: []\n"
    )
    # `config_path` points at a different YAML elsewhere (mimics the package
    # source). The checkpoint copy must still win.
    other = tmp_path / "other_workflow.yaml"
    other.write_text(
        "pipeline:\n  - stage: marker_other\n    skill: x\n    tool: y\nskills: []\n"
    )

    captured = {}

    def _capture_load(path):
        captured["path"] = str(path)
        return []

    with mock.patch("ari.pipeline.load_pipeline", side_effect=_capture_load):
        generate_paper_section(
            all_nodes=[], experiment_data={}, checkpoint_dir=ckpt,
            mcp=mock.MagicMock(), config_path=str(other),
        )

    assert captured.get("path") == str(ckpt / "workflow.yaml"), (
        f"checkpoint workflow.yaml must win; got {captured.get('path')!r}"
    )
