"""Focused tests for the canonical retrieval reranker parser."""

from server import _parse_selection_response


def test_parse_selection_valid() -> None:
    assert _parse_selection_response("[0, 2, 4]", 5) == [0, 2, 4]


def test_parse_selection_drops_out_of_range_indices() -> None:
    assert _parse_selection_response("[0, 10, 2]", 5) == [0, 2]


def test_parse_selection_accepts_embedded_array() -> None:
    assert _parse_selection_response("Selected: [1, 3]", 5) == [1, 3]


def test_parse_selection_rejects_non_array_text() -> None:
    assert _parse_selection_response("none", 5) == []


def test_parse_selection_accepts_empty_array() -> None:
    assert _parse_selection_response("[]", 5) == []
