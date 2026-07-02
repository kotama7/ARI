"""Subtask 040 — extracted evaluator/LLM-judge prompts stay byte-identical.

The two judge system prompts formerly inline in ``src/server.py`` —
``_METRIC_EXTRACT_SYS`` -> ``prompts/metric_extract_sys.md`` and
``_SEMANTIC_SYSTEM_PROMPT`` -> ``prompts/semantic_review_sys.md`` — are now loaded
from ``src/prompts/*.md`` via the skill-local ``_load_prompt`` loader (a copied
mirror of ari-core's ``load_versioned`` contract; no ari-core import). The
``_RENDERED_SHA`` values were captured from the original string constants
immediately before extraction; a drift here means the bytes reaching the judge
LLM changed and evaluation behaviour would shift.

Only the two prompts the Subtask 036 census flags for the 040 extraction are
covered. ``_CLAIMS_EXTRACT_SYS`` / ``_CONTRACT_FLAGS_SYS`` were NOT in that
census (036 §4) and remain inline module constants — intentionally not extracted
here.
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

# key -> sha256 of the RENDERED prompt (the system-message content actually sent
# to the judge). Equals sha256 of the pre-extraction Python constant, byte-for-byte.
_RENDERED_SHA = {
    "metric_extract_sys": "937f446c55aa07750919c6e1fc11aecd991d3e7b18cc37d7793e2634dda2c81e",
    "semantic_review_sys": "875fbf4086a5e7ed51e2c8e538ee62b907d06e71f0b1fcb566f14822c22a05cc",
}

# key -> sha256[:12] of the RAW on-disk template body (what ``load_versioned`` pins).
_VERSIONED_HASH = {
    "metric_extract_sys": "7f7e1d5cbb12",
    "semantic_review_sys": "697ded3c969c",
}


def test_rendered_prompts_byte_identical_to_original_constants():
    """Rendered prompt bytes must match the pre-extraction inline constants."""
    for key, expected in _RENDERED_SHA.items():
        rendered = _load_prompt(key)
        actual = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        assert actual == expected, (
            f"prompt '{key}' drifted: expected {expected}, got {actual}. "
            "If the change is intentional, update _RENDERED_SHA."
        )


def test_load_versioned_returns_stable_hash_prefix():
    """``load_versioned`` returns the rendered text plus a deterministic sha256[:12]."""
    for key, expected12 in _VERSIONED_HASH.items():
        text, version = _load_prompt_versioned(key)
        assert text == _load_prompt(key)
        assert len(version) == 12
        assert version == expected12


def test_prompt_files_present_on_disk():
    for key in _RENDERED_SHA:
        assert _prompt_path(key).is_file()
