"""Subtask 041 — extracted paper-generation prompts stay byte-identical.

The five paper system prompts the Subtask 036 census flags EXTRACT_TEMPLATE for
041 (``docs/refactoring/reports/hardcoded_prompt_inventory.md`` §3.2) were moved
out of ``src/server.py`` into ``src/prompts/*.md`` and are loaded through the
skill-local ``_load_prompt`` helper (a copied mirror of ari-core's
``load_versioned`` contract; no ari-core import, so the one-way
``ari-skill-* -> ari-core`` boundary is preserved):

  * ``academic_reviewer``  <- ``review_section`` ``system_prompt`` (was :542) —
    the one ``str.format`` template (single ``{venue_upper}`` placeholder).
  * ``fill_in_writer``     <- ``_system_prompt_a`` body (was :1487) — raw-loaded
    static rules; the ``f"…Target venue: {venue_info['name']}. "`` prefix and the
    ``+ _paper_language_directive() + _grounded_block`` suffixes stay in Python.
  * ``figure_inserter``    <- the LaTeX-inserter role line (was :1638).
  * ``paper_writer``       <- ``_system_prompt`` static (was :1660); the
    ``+ _paper_language_directive()`` suffix stays in Python.
  * ``global_coherence``   <- editor ``system_prompt`` static (was :2544); the
    ``+ _paper_language_directive()`` suffix stays in Python.

``_RENDERED_SHA`` values were captured from the ORIGINAL inline literals (git
HEAD) immediately before extraction; a drift here means the bytes reaching the
paper/reviewer LLM changed and P2 (determinism) / reproducibility would break.

Intentionally NOT extracted (036 verdicts, kept inline): the short f-string
revisers ``venue_drafting`` :353 / ``title_reviser`` :622 / ``abstract_reviser``
:631 / ``section_reviser`` :639 (REVIEW_REQUIRED), ``SECTION_PROMPTS`` /
``_FORBIDDEN_NOTICE`` (not in the 036 census as EXTRACT), and
``review_engine.py`` ``build_system_prompt`` / area-chair (MOVE_TO_CONFIGURABLE /
MERGE_DUPLICATE, routed to 040 and deferred — do NOT merge here).
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server import (  # noqa: E402
    _load_prompt,
    _load_prompt_versioned,
    _prompt_path,
)

# key -> sha256 of the loaded template/static (what ``_load_prompt`` returns).
# For the four raw-loaded prompts this equals sha256 of the pre-extraction inline
# bytes, byte-for-byte. For ``academic_reviewer`` (the format template) it is the
# sha of the ``{venue_upper}`` template; the byte-identity of the RENDERED prompt
# is asserted separately below against the original ``venue.upper()`` rendering.
_RENDERED_SHA = {
    "academic_reviewer": "cd459ecbb2c2e96c271e31c6081a9b848aeab9c25ac749b7ea6d649bb71a3a64",
    "fill_in_writer": "7da830d8ef88ef732795f2a889bb1d8a01d9f88349e0966db71efcf04e3a5978",
    "figure_inserter": "6343023cf92004fdbe58945aef7cc6566a2e044832f2a26c85ddeb5fc30ac8fc",
    "paper_writer": "719b77809032972683e04a4ac3964aa5ce319ee0af6a242217a4f9e5c3f6f31c",
    "global_coherence": "a5ef7c47ed6c184614bfb52c944fd59a1c326e94300733d67e984b3eba92594b",
}

# key -> sha256[:12] of the RAW on-disk template body (what ``load_versioned`` pins).
_VERSIONED_HASH = {
    "academic_reviewer": "04b3c49d070d",
    "fill_in_writer": "feeaf046eda2",
    "figure_inserter": "a7069bfe1096",
    "paper_writer": "f38a15f0f140",
    "global_coherence": "f0cb1a9a5ce4",
}

# sha256 of ``academic_reviewer`` template rendered with venue="arxiv" (the code
# path ``.format(venue_upper=venue.upper())``), captured from the original inline
# ``"You are an expert academic reviewer for " + venue.upper() + …`` at venue="arxiv".
_ACADEMIC_REVIEWER_ARXIV_SHA = (
    "95fea6e12d57b57f0ef2fdc830c8d1f2b6e7cbcdf1aaab47b922327b00fdda06"
)


def test_loaded_templates_byte_identical():
    """Loaded template/static bytes must match the pre-extraction inline bytes."""
    for key, expected in _RENDERED_SHA.items():
        actual = hashlib.sha256(_load_prompt(key).encode("utf-8")).hexdigest()
        assert actual == expected, (
            f"prompt '{key}' drifted: expected {expected}, got {actual}. "
            "If the change is intentional, update _RENDERED_SHA."
        )


def test_load_versioned_returns_stable_hash_prefix():
    """``load_versioned`` returns the loaded text plus a deterministic sha256[:12]."""
    for key, expected12 in _VERSIONED_HASH.items():
        text, version = _load_prompt_versioned(key)
        assert text == _load_prompt(key)
        assert len(version) == 12
        assert version == expected12


def test_academic_reviewer_render_byte_identical_to_original():
    """``academic_reviewer`` is the one format template: rendering it with a venue
    must reproduce the original ``"You are an expert academic reviewer for " +
    venue.upper() + …`` bytes exactly (no brace/placeholder drift)."""
    rendered = _load_prompt("academic_reviewer").format(venue_upper="arxiv".upper())
    actual = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    assert actual == _ACADEMIC_REVIEWER_ARXIV_SHA


def test_prompt_files_present_on_disk():
    for key in _RENDERED_SHA:
        assert _prompt_path(key).is_file()
