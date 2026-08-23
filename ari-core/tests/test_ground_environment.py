"""Anti-fabrication for the agent-authored ``environment`` note.

The note is free text the agent writes about the machine it used. It is kept only
when a hard claim in it (version number, ISA name, model token) appears in the
EVIDENCE this node actually received.

The subtle part is WHAT COUNTS AS EVIDENCE. Grounding against tool results alone
turned this into a ``describe_environment``-call detector rather than a
fabrication detector: measured on a real 40-node study it deleted 4 of 17 notes
whose CPU model, thread count and compiler version all traced verbatim to the
17,921-char parent handoff the framework had injected. Those children read the
environment out of the parent's log instead of spending a ReAct step re-querying
it — the exact behaviour the full_log handoff arm exists to measure — and were
recorded as having no environment awareness for it.

So evidence = tool results + framework-authored user turns (goal, handoff), and
never the agent's own assistant turns (circular) nor the system prompt (which
names ISA examples like "AVX-512", so a note could ground against the
instructions instead of the machine).
"""
from __future__ import annotations

from ari.agent.loop import _ground_environment


def test_note_grounded_in_tool_output_is_kept():
    msgs = [{"role": "tool",
             "content": '{"cpu_model": "Intel Xeon Gold 6142", "compilers": {"gcc": "11.5.0"}}'}]
    note = "Intel Xeon Gold 6142 with gcc 11.5.0, -O3 -march=native"
    assert _ground_environment(note, msgs) == note


def test_note_grounded_only_in_the_parent_handoff_is_kept():
    """THE REGRESSION. A child that learns the machine from the injected parent
    handoff — rather than burning a step on describe_environment — must keep its
    note. The handoff is the parent's real tool output, rendered by the framework
    into a user turn; the agent cannot author it."""
    msgs = [
        {"role": "tool", "content": '{"stdout": "make: ok"}'},           # no env facts
        {"role": "user",
         "content": "[Parent handoff — execution log]\n"
                    "→ describe_environment({})\n"
                    '← {"cpu_model": "Intel Xeon Gold 6142", "threads": 64, '
                    '"compilers": {"gcc": "gcc (GCC) 11.5.0"}}'},
    ]
    note = "Intel Xeon Gold 6142, 64 threads, gcc 11.5.0"
    assert _ground_environment(note, msgs) == note


def test_fabricated_note_is_still_dropped():
    """The filter must still do its job: hardware that appears in NO evidence."""
    msgs = [
        {"role": "tool", "content": '{"cpu_model": "Intel Xeon Gold 6142"}'},
        {"role": "user", "content": "[Parent handoff — execution log]\n→ run_bash(make)\n← ok"},
    ]
    assert _ground_environment("NVIDIA A100 GPU with CUDA 12.4, 80GB HBM2e", msgs) == ""
    assert _ground_environment("AMD EPYC 9654 with gcc 13.2.0", msgs) == ""


def test_agent_cannot_ground_a_claim_against_its_own_assistant_turn():
    """Circular grounding guard: asserting a fact earlier in the conversation must
    not license repeating it in the note."""
    msgs = [
        {"role": "assistant", "content": "I am running on NVIDIA A100 with CUDA 12.4"},
        {"role": "tool", "content": '{"cpu_model": "Intel Xeon"}'},
    ]
    assert _ground_environment("NVIDIA A100 with CUDA 12.4", msgs) == ""


def test_system_prompt_examples_do_not_ground_a_note():
    """The system prompt names ISA examples ("CPU/ISA like AVX-512"). A note must
    ground against the MACHINE, never against its own instructions."""
    msgs = [
        {"role": "system",
         "content": "Report the environment you used (e.g. compiler + version, "
                    "CPU/ISA like AVX-512, GPU, MPI)."},
        {"role": "tool", "content": '{"stdout": "make: ok"}'},
    ]
    assert _ground_environment("AVX-512 capable CPU", msgs) == ""


def test_pure_prose_without_hard_claims_is_allowed():
    """No verifiable token at all -> nothing to fabricate -> keep."""
    msgs = [{"role": "tool", "content": '{"stdout": "ok"}'}]
    note = "a multicore machine with the GNU toolchain and OpenMP"
    assert _ground_environment(note, msgs) == note


def test_an_arch_token_counts_as_a_hard_claim():
    """``x86`` matches the model-token pattern, so it IS checkable — an unverified
    arch claim is dropped, a verified one is kept. (Guards the boundary between
    "pure prose" and "hard claim".)"""
    assert _ground_environment("a multicore x86 machine",
                               [{"role": "tool", "content": '{"stdout": "ok"}'}]) == ""
    note = "a multicore x86 machine"
    assert _ground_environment(note,
                               [{"role": "tool", "content": '{"arch": "x86"}'}]) == note


def test_no_evidence_at_all_means_no_note():
    assert _ground_environment("Intel Xeon Gold 6142", []) == ""
    assert _ground_environment("", [{"role": "tool", "content": "x"}]) == ""
    assert _ground_environment(None, [{"role": "tool", "content": "x"}]) == ""


def test_claim_must_match_as_a_whole_token():
    """A digit run inside a larger token is not a match: "12" from "12.9" must not
    ground against the "12" inside "avx512"."""
    msgs = [{"role": "tool", "content": '{"flags": "avx512f avx512dq"}'}]
    assert _ground_environment("CUDA 12.9 toolkit", msgs) == ""
