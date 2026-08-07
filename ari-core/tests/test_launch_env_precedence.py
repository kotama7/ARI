"""A configured key must not lose to a file nobody remembers writing.

``load_dotenv_files`` fills blanks in the subprocess environment, and the launch
paths then fall back to the key stored in Settings only when the slot is still
empty. That made a value read out of ``~/.env`` indistinguishable from one the
operator exported, so a stale global dotfile silently outranked the key the
operator had just configured -- with no diagnostic, because from the launcher's
side both look like "a key is already present".

These exercise the helper against files under ``tmp_path`` only; nothing here
reads or writes a real ``.env``.
"""

from __future__ import annotations

from ari.viz.services.launch_service import load_dotenv_files


def _dotenv(path, body: str):
    path.write_text(body)
    return path


def test_reports_which_names_came_from_a_file(tmp_path):
    env_file = _dotenv(tmp_path / ".env", "OPENAI_API_KEY=from-file\nS2_API_KEY=also-file\n")
    proc_env: dict[str, str] = {}

    introduced = load_dotenv_files(
        proc_env, [env_file], strip_quotes=True, swallow_errors=True
    )

    assert introduced == {"OPENAI_API_KEY", "S2_API_KEY"}
    assert proc_env["OPENAI_API_KEY"] == "from-file"


def test_does_not_claim_a_name_the_operator_already_exported(tmp_path):
    env_file = _dotenv(tmp_path / ".env", "OPENAI_API_KEY=from-file\n")
    proc_env = {"OPENAI_API_KEY": "exported-by-operator"}

    introduced = load_dotenv_files(
        proc_env, [env_file], strip_quotes=True, swallow_errors=True
    )

    # The exported value still wins, and the helper does not pretend it wrote it.
    assert proc_env["OPENAI_API_KEY"] == "exported-by-operator"
    assert "OPENAI_API_KEY" not in introduced


def test_a_blank_export_is_treated_as_absent(tmp_path):
    env_file = _dotenv(tmp_path / ".env", "OPENAI_API_KEY=from-file\n")
    proc_env = {"OPENAI_API_KEY": ""}

    introduced = load_dotenv_files(
        proc_env, [env_file], strip_quotes=True, swallow_errors=True
    )

    assert proc_env["OPENAI_API_KEY"] == "from-file"
    assert "OPENAI_API_KEY" in introduced


def test_both_parse_variants_report_the_same_provenance(tmp_path):
    env_file = _dotenv(tmp_path / ".env", "OPENAI_API_KEY=from-file\n")

    lenient: dict[str, str] = {}
    strict: dict[str, str] = {}
    assert load_dotenv_files(
        lenient, [env_file], strip_quotes=True, swallow_errors=True
    ) == load_dotenv_files(
        strict, [env_file], strip_quotes=False, swallow_errors=False
    )


def test_the_precedence_the_launch_paths_apply(tmp_path):
    """The rule the two call sites encode, exercised directly.

    Settings loses to an export and beats a file -- the second half is the part
    that was broken.
    """

    env_file = _dotenv(tmp_path / ".env", "OPENAI_API_KEY=stale-file-key\n")

    def resolve(exported: dict[str, str], configured: str) -> str:
        proc_env = dict(exported)
        from_file = load_dotenv_files(
            proc_env, [env_file], strip_quotes=True, swallow_errors=True
        )
        held_by_operator = (
            bool(proc_env.get("OPENAI_API_KEY"))
            and "OPENAI_API_KEY" not in from_file
        )
        if configured and not held_by_operator:
            proc_env["OPENAI_API_KEY"] = configured
        return proc_env["OPENAI_API_KEY"]

    assert resolve({"OPENAI_API_KEY": "exported"}, "configured") == "exported"
    assert resolve({}, "configured") == "configured"
    assert resolve({}, "") == "stale-file-key"
