"""Tests for the Step 4 reproduce-plan generator.

The LLM call is replaced by an injected ``llm_call`` so these tests are
hermetic (no API key, no network) and run in milliseconds.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import reproduce_plan as RP
import rubric_template as RT


# Each value padded above the 150-char content threshold so the
# quality-validation gate accepts them. Real LLM outputs are multi-KB
# and easily clear this floor; the threshold mainly guards against the
# "DUPLICATE_KEY_PLACEHOLDER" partial-response failure mode.
FAKE_ENVELOPE = {
    "reproduce_plan_md": (
        "# Reproduce plan\n\n## Summary\nThis simulated plan covers two "
        "experiments described in the paper for unit-test purposes only. "
        "Reproducibility category: verification_only.\n\n## Hardware\n"
        "- Node: *(NOT SPECIFIED)*\n- Compiler: GCC (paper §3)\n"
    ),
    "verification_code_py": (
        "#!/usr/bin/env python3\n\"\"\"Verification stubs.\"\"\"\n\n"
        "PAPER_CLAIMS = {\n"
        "    'throughput': {'text': 'paper claim', 'expected': 1.0,\n"
        "                   'tolerance': 0.05, 'source': 'paper §4'},\n"
        "}\n\nif __name__ == '__main__':\n    print('ok')\n"
    ),
    "install_commands_txt": (
        "# (synthetic test fixture — populate from AD/AE in real runs)\n"
        "git clone https://example.com/repo.git  # AD §A2.1\n"
        "cd repo && bash install_deps.sh         # AD §A3\n"
        "export OMP_NUM_THREADS=16                # paper §3\n"
    ),
    "reproduce_log_sim": (
        "$ bash install_deps.sh\n[install] cloning submodules\n"
        "[install] OK\n\n$ bash reproduce.sh experiment_A\n"
        "[run] experiment=experiment_A params=(scale=small)\n"
        "[result] throughput: 1.0  # (from paper §4)\n"
    ),
}


def _make_call(envelope: dict | str):
    async def _call(prompt: str) -> str:
        if isinstance(envelope, str):
            return envelope
        return json.dumps(envelope)
    return _call


# ── prompt rendering ───────────────────────────────────────────────────────


def test_render_prompt_substitutes_paper_text_and_strips_placeholder():
    out = RP._render_prompt("PAPER BODY 12345", template=None)
    assert "PAPER BODY 12345" in out
    assert "{PAPER_TEXT}" not in out
    assert "{VENUE_HINT}" not in out


def test_render_prompt_with_sc_template_injects_hpc_hint():
    t = RT.load_paperbench_rubric("sc")
    prompt = RP._render_prompt("DUMMY PAPER", template=t)
    # SC template's reproduce_plan_hint mentions SLURM specifics.
    assert "SLURM" in prompt or "sbatch" in prompt
    assert "VENUE OVERRIDE" in prompt
    assert "{VENUE_HINT}" not in prompt


def test_render_prompt_with_generic_template_no_venue_block():
    t = RT.load_paperbench_rubric("generic")
    prompt = RP._render_prompt("DUMMY PAPER", template=t)
    # generic.yaml has empty hint → no override block.
    assert "VENUE OVERRIDE" not in prompt


# ── envelope parsing ───────────────────────────────────────────────────────


def test_extract_json_object_handles_code_fences():
    raw = "```json\n" + json.dumps(FAKE_ENVELOPE) + "\n```"
    assert RP._extract_json_object(raw) == FAKE_ENVELOPE


def test_extract_json_object_handles_thinking_tags():
    raw = "<think>thinking aloud</think>\n" + json.dumps(FAKE_ENVELOPE)
    assert RP._extract_json_object(raw) == FAKE_ENVELOPE


def test_extract_json_object_handles_outermost_braces():
    raw = "preamble text " + json.dumps(FAKE_ENVELOPE) + " trailing text"
    assert RP._extract_json_object(raw) == FAKE_ENVELOPE


# ── end-to-end with injected call ──────────────────────────────────────────


def test_generate_writes_four_files(tmp_path: Path):
    out = tmp_path / "submission"
    res = asyncio.run(RP.generate_reproduce_plan_async(
        paper_text="dummy paper text",
        output_dir=str(out),
        llm_call=_make_call(FAKE_ENVELOPE),
    ))
    assert "error" not in res
    for _, fname in RP.OUTPUT_FILES:
        path = out / fname
        assert path.is_file(), f"expected file {fname} not written"
        assert path.read_text().strip()


def test_generate_empty_paper_text_rejected(tmp_path: Path):
    res = asyncio.run(RP.generate_reproduce_plan_async(
        paper_text="",
        output_dir=str(tmp_path),
        llm_call=_make_call(FAKE_ENVELOPE),
    ))
    assert "error" in res
    assert "empty paper_text" in res["error"]


def test_generate_retries_on_missing_keys(tmp_path: Path):
    """When the first LLM response is missing keys, the loop should retry."""
    attempts = {"n": 0}

    async def _call(prompt: str) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return json.dumps({"reproduce_plan_md": "incomplete"})
        return json.dumps(FAKE_ENVELOPE)

    res = asyncio.run(RP.generate_reproduce_plan_async(
        paper_text="dummy",
        output_dir=str(tmp_path),
        llm_call=_call,
    ))
    assert "error" not in res, res
    assert attempts["n"] == 2
    assert any("missing keys" in w for w in res["warnings"])


def test_generate_fails_after_retry_limit(tmp_path: Path):
    """All retries return malformed JSON → terminal failure."""
    async def _bad(prompt: str) -> str:
        return "not json at all"

    res = asyncio.run(RP.generate_reproduce_plan_async(
        paper_text="dummy",
        output_dir=str(tmp_path),
        llm_call=_bad,
    ))
    assert "error" in res
    assert res["warnings"]


# ── ARI generality: HPC vocabulary must NOT be in core/prompt ─────────────


def test_bundled_prompt_is_domain_agnostic():
    """The bundled reproduce_plan.md prompt that goes to the LLM must
    not mention HPC / SLURM / NeurIPS / Nature vocabulary — those live
    in ari-core/config/paperbench_rubrics/<id>.yaml only. Source-code
    docstrings can mention them (architecture documentation), but
    operational LLM-facing content must stay generic."""
    prompt = (Path(__file__).resolve().parent.parent / "src" / "prompts" /
              "reproduce_plan.md").read_text()
    forbidden = ["SLURM", "sbatch", "mpirun", "NeurIPS", "wet-lab",
                 "protocols.io", "CUDA"]
    for f in forbidden:
        assert f not in prompt, (
            f"venue-specific term {f!r} leaked into bundled prompt — must "
            "live in ari-core/config/paperbench_rubrics/<id>.yaml only"
        )
