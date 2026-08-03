"""Golden compare for the ``writer_prompt_override`` on-ramp seam
(docs/plans/ari_rqgm_paper/03 §9 Regression + §12 deletion criterion + R3).

The seam is additive: ``writer_prompt_override=""`` (the linear default, and any
non-RQGM caller) MUST produce byte-identical behaviour to the pre-change tool —
the writer's system prompt is the loaded ``paper_writer.md`` / ``global_coherence.md``
exactly as before. A non-empty override is the epoch's ACTIVE governed
``paper_writer`` bytes DRIVING the reflection/refine instruction; the skill still
evolves nothing and imports no ``ari.rqgm``.

These are the tests R3's mitigation ("a skill test asserts ``""`` ⇒ byte-identical")
rests on; before this file the argument had zero coverage in the skill suite.
"""
from __future__ import annotations

import json
import sys

import pytest
from unittest.mock import patch

from src import server
from test_verified_context_wiring import _native_inputs

_GOVERNED = "GOVERNED-XYZ: reject overclaims; anchor every numeric result."


def _latex_doc() -> str:
    return (
        "```latex\n"
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Results}\nThe value is X.\nI am done\n"
        "\\end{document}\n```"
    )


def _mock_resp(content: str):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    return r


async def _run_writer(tmp_path, override: str) -> list[str]:
    """Drive ``write_paper_iterative`` end-to-end with a litellm spy; return the
    system prompt of every call it issued (the reflection loop always runs, so
    the writer-prompt call is always among them)."""
    systems: list[str] = []

    async def _spy(**kwargs):
        systems.append(kwargs["messages"][0]["content"])
        return _mock_resp(_latex_doc())

    with patch("src.server.litellm.acompletion", new=_spy):
        native_inputs = _native_inputs(tmp_path)
        await server.write_paper_iterative(
            **native_inputs,
            experiment_summary="a small experiment",
            venue="arxiv", max_revision_rounds=1,
            writer_prompt_override=override,
        )
    assert systems, "litellm.acompletion was never reached"
    return systems


@pytest.mark.asyncio
async def test_write_paper_iterative_default_is_the_loaded_writer_prompt(tmp_path):
    """Default (``override=""``) => the reflection system prompt is EXACTLY
    ``_load_prompt("paper_writer") + _paper_language_directive()`` — the
    pre-change expression, byte-for-byte (server.py:1685-1688)."""
    expected = server._load_prompt("paper_writer") + server._paper_language_directive()
    systems = await _run_writer(tmp_path, "")
    assert expected in systems, "reflection loop did not use the loaded paper_writer prompt"
    # No governance string leaks into ANY call on the linear path.
    assert all("GOVERNED-XYZ" not in s for s in systems)


@pytest.mark.asyncio
async def test_write_paper_iterative_override_drives_the_governed_bytes(tmp_path):
    """A non-empty override => the reflection system prompt is the GOVERNED bytes
    + the language directive, and the ``paper_writer.md`` body is ABSENT — the
    evolving bytes actually reach the model (server.py:1686)."""
    expected = _GOVERNED + server._paper_language_directive()
    systems = await _run_writer(tmp_path, _GOVERNED)
    assert expected in systems
    writer_md = server._load_prompt("paper_writer")
    # the governed call must NOT also carry the founding paper_writer.md text
    governed_calls = [s for s in systems if s == expected]
    assert governed_calls
    assert all(writer_md not in s for s in governed_calls)


async def _refine_systems(tmp_path, override: str) -> list[str]:
    p = tmp_path / "full_paper.tex"
    p.write_text("\\section{R}\n% CLAIM:C1:NC1\nThe value is X.\n")
    revs = json.dumps([{"section": "results", "instruction": "tighten the claim"}])
    systems: list[str] = []

    async def _spy(**kwargs):
        systems.append(kwargs["messages"][0]["content"])
        return _mock_resp('```json\n[]\n```')

    with patch("src.server.litellm.acompletion", new=_spy):
        await server.paper_refine(tex_path=str(p), suggested_revisions_json=revs,
                                  writer_prompt_override=override)
    assert systems, "paper_refine issued no LLM call"
    return systems


@pytest.mark.asyncio
async def test_paper_refine_default_is_byte_identical(tmp_path):
    """Default (``override=""``) => system == ``global_coherence`` + directive,
    with NO override prefix (server.py:2581-2583) — byte-identical to today."""
    expected = server._load_prompt("global_coherence") + server._paper_language_directive()
    systems = await _refine_systems(tmp_path, "")
    assert expected in systems


@pytest.mark.asyncio
async def test_paper_refine_override_prepends_the_governed_bytes(tmp_path):
    """Override => system == ``override + "\\n\\n" + global_coherence + directive``
    (server.py:2581-2583); the governed bytes lead."""
    expected = (_GOVERNED + "\n\n"
                + server._load_prompt("global_coherence")
                + server._paper_language_directive())
    systems = await _refine_systems(tmp_path, _GOVERNED)
    assert expected in systems


def test_skill_imports_no_ari_rqgm():
    """§12 deletion criterion: the skill governs nothing — importing the server
    must not drag in any ``ari.rqgm`` module (mirrors the ari-core clean-room
    boundary assertion)."""
    import src.server  # noqa: F401  (already imported; assert the module graph)
    leaked = [m for m in sys.modules
              if m == "ari.rqgm" or m.startswith("ari.rqgm.")]
    assert not leaked, f"skill leaked ari.rqgm modules: {leaked}"
