"""Tests for ari.llm.claude_code.validation — JSON extraction + schema checks."""

from __future__ import annotations

import pytest

from ari.llm.claude_code.validation import extract_json, validate_against_schema

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


def test_plain_json():
    assert extract_json('{"ok": true}') == {"ok": True}
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_markdown_fences_stripped():
    assert extract_json('```json\n{"ok": false}\n```') == {"ok": False}
    assert extract_json('```\n{"ok": true}\n```') == {"ok": True}


def test_json_embedded_in_prose():
    assert extract_json('Here is the result:\n{"ok": true}\nDone.') == {
        "ok": True
    }


def test_prose_braces_before_json_do_not_break_extraction():
    # Regression guard (review finding): the scanner must not give up on the
    # first balanced-but-unparseable brace span.
    assert extract_json(
        'Given constraints {n>=1}, here is the result: {"ok": true}'
    ) == {"ok": True}
    assert extract_json(
        'Values in {1, 2 or 3} considered. Answer: {"ok": false}'
    ) == {"ok": False}
    # First '{' never balances at all; a later candidate does.
    assert extract_json('I said "wait {here we go: {"ok": true}') == {
        "ok": True
    }


def test_no_json_raises():
    with pytest.raises(ValueError, match="no JSON value"):
        extract_json("there is no json here, only {braces}")
    with pytest.raises(ValueError, match="no JSON value"):
        extract_json("")


def test_validate_against_schema():
    assert validate_against_schema({"ok": True}, SCHEMA) == []
    errors = validate_against_schema({"ok": "nope"}, SCHEMA)
    assert errors and "ok" in errors[0]
    errors = validate_against_schema({}, SCHEMA)
    assert errors and "required" in errors[0]


def test_validate_null_when_schema_allows():
    assert validate_against_schema(None, {"type": "null"}) == []
