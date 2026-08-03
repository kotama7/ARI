"""Subtask 041 — extracted paper-generation prompts stay byte-identical.

The supported whole-paper and claim-declaration prompts were moved
out of ``src/server.py`` into ``src/prompts/*.md`` and are loaded through the
skill-local ``_load_prompt`` helper (a copied mirror of ari-core's
``load_versioned`` contract; no ari-core import, so the one-way
``ari-skill-* -> ari-core`` boundary is preserved):

  * ``fill_in_writer``     <- ``_system_prompt_a`` body (was :1487) — raw-loaded
    static rules; the ``f"…Target venue: {venue_info['name']}. "`` prefix and the
    ``+ _paper_language_directive() + _grounded_block`` suffixes stay in Python.
  * ``paper_writer``       <- ``_system_prompt`` static (was :1660); the
    ``+ _paper_language_directive()`` suffix stays in Python.
  * ``global_coherence``   <- editor ``system_prompt`` static (was :2544); the
    ``+ _paper_language_directive()`` suffix stays in Python.
  * ``forward_declaration`` <- static claim/formula instructions appended to
    experiment context; dynamic config rows stay in Python.

``_RENDERED_SHA`` values were captured from the ORIGINAL inline literals (git
HEAD) immediately before extraction; a drift here means the bytes reaching the
paper LLM changed and P2 (determinism) / reproducibility would break.

The deleted per-section writer/reviewer and model-based figure inserter prompts
are intentionally absent from the runtime package.
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
# These equal the SHA-256 of the pre-extraction inline bytes, byte-for-byte.
_RENDERED_SHA = {
    "fill_in_writer": "7da830d8ef88ef732795f2a889bb1d8a01d9f88349e0966db71efcf04e3a5978",
    "paper_writer": "719b77809032972683e04a4ac3964aa5ce319ee0af6a242217a4f9e5c3f6f31c",
    "global_coherence": "a5ef7c47ed6c184614bfb52c944fd59a1c326e94300733d67e984b3eba92594b",
    "forward_declaration": "e9335d5a123b83067d5ad6a380f1feff50575860e6833b2e3940281a90b34f31",
}

# key -> sha256[:12] of the RAW on-disk template body (what ``load_versioned`` pins).
_VERSIONED_HASH = {
    "fill_in_writer": "feeaf046eda2",
    "paper_writer": "f38a15f0f140",
    "global_coherence": "f0cb1a9a5ce4",
    "forward_declaration": "629514a45c66",
}

_FORWARD_DECLARATION_COMPOSED_SHA = (
    "550a08ed6c217cf350652d60ce2be2a9f3ecb495b9a45957d5495ce9fccc3dab"
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


def test_prompt_files_present_on_disk():
    for key in _RENDERED_SHA:
        assert _prompt_path(key).is_file()


def test_forward_declaration_composition_is_byte_identical():
    """Static extraction must not alter the bytes sent with dynamic config rows."""
    reconstructed = "\n\n" + _load_prompt("forward_declaration") + "\n{x}"
    actual = hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()
    assert actual == _FORWARD_DECLARATION_COMPOSED_SHA
