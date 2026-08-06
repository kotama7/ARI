"""Evaluator prompt identity and ownership tests."""

from __future__ import annotations

import hashlib

from src.server import _load_prompt, _load_prompt_versioned, _prompt_path


_PROMPTS = {
    "metric_contract_proposal_sys": {
        "rendered": "b45983ada64073624c85a96edb3b065ab188c873c11ce95a41fe389d6c590336",
        "raw": "b1df137939e302c61de444f68b8262b7bf26c6245ff19c938cf42f5ebc38b56c",
    },
    "semantic_review_sys": {
        "rendered": "58dcfda334c303312bccaf3787052a53512ea1c83e7114baf82408f81604936a",
        "raw": "91cf457ee465da5154264965eebac76c6a2b7afd5d6672bb71d7a17aa7529e97",
    },
}


def test_prompt_bytes_and_full_provenance_digest_are_stable():
    for key, expected in _PROMPTS.items():
        rendered, version = _load_prompt_versioned(key)
        assert hashlib.sha256(rendered.encode()).hexdigest() == expected["rendered"]
        assert version == "sha256:" + expected["raw"]
        assert _prompt_path(key).is_file()


def test_removed_implicit_extraction_prompts_are_absent():
    for key in ("metric_extract_sys", "claims_extract_sys", "contract_flags_sys"):
        assert not _prompt_path(key).exists()
