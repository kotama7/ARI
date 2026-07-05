"""Unit tests for the viz FileService (subtask 023).

Covers the extracted filesystem primitives in
``ari-core/ari/viz/services/file_service.py``: the single path-traversal
validator, the named byte-size limits, the file-classification sets, the
canonical content-type table (both historical fallbacks), and the
read/write/delete helpers. These are additive; the wire-contract behaviour of
``file_api`` / ``node_work_api`` remains pinned by ``test_file_explorer.py`` and
``test_workflow_contract.py``.
"""
from __future__ import annotations

import pytest

from ari.viz.services import file_service as fs


# ── traversal validator ──────────────────────────────────────────────────────

def test_safe_resolve_inside_base(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("hi")
    target, err = fs.safe_resolve(tmp_path, "sub/a.txt")
    assert err is None
    assert target == (tmp_path / "sub" / "a.txt").resolve()


def test_safe_resolve_dotdot_traversal_denied(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secret.txt").write_text("nope")
    target, err = fs.safe_resolve(base, "../secret.txt")
    assert target is None
    assert err == "path traversal denied"


def test_safe_resolve_absolute_escape_denied(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    target, err = fs.safe_resolve(base, "/etc/passwd")
    assert target is None
    assert err == "path traversal denied"


# ── content-type table (both historical fallbacks) ───────────────────────────

@pytest.mark.parametrize("ext,expected", [
    (".pdf", "application/pdf"),
    (".png", "image/png"),
    (".JPG", "image/jpeg"),      # case-insensitive
    (".jpeg", "image/jpeg"),
    (".svg", "image/svg+xml"),
    (".eps", "application/postscript"),
    (".tiff", "image/tiff"),
    (".gif", "image/gif"),
])
def test_content_type_known(ext, expected):
    assert fs.content_type_for(ext, default="x") == expected


def test_content_type_default_is_caller_chosen():
    # /codefile fallback vs /file/raw fallback — both reproducible.
    assert fs.content_type_for(".unknown", default="text/plain; charset=utf-8") == (
        "text/plain; charset=utf-8"
    )
    assert fs.content_type_for(".unknown", default="application/octet-stream") == (
        "application/octet-stream"
    )


# ── named size limits (mirror the historical literals) ───────────────────────

def test_size_limits_are_exact_literals():
    assert fs.MAX_TEXT_READ == 5_000_000
    assert fs.MAX_BINARY_SERVE == 20_000_000
    assert fs.MAX_TREE_TEXT == 10_000_000
    assert fs.MAX_POST_BODY == 10 * 1024 * 1024


# ── classification sets ───────────────────────────────────────────────────────

def test_classification_sets_members():
    assert ".tex" in fs.TEXT_EXTENSIONS and ".md" in fs.TEXT_EXTENSIONS
    assert ".png" in fs.BINARY_EXTENSIONS and ".pkl" in fs.BINARY_EXTENSIONS
    assert "__pycache__" in fs.SKIP_DIRS and ".git" in fs.SKIP_DIRS


# ── read / write / delete helpers ────────────────────────────────────────────

def test_read_write_delete_roundtrip(tmp_path):
    p = tmp_path / "f.txt"
    fs.write_text(p, "hello")
    assert fs.read_text(p) == "hello"
    b = tmp_path / "g.bin"
    fs.write_bytes(b, b"\x00\x01")
    assert b.read_bytes() == b"\x00\x01"
    fs.delete(p)
    assert not p.exists()


def test_read_text_replaces_invalid_utf8(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_bytes(b"\xff\xfe abc")
    # errors="replace" — no exception, content is a str.
    assert isinstance(fs.read_text(p), str)


# ── delegation parity: file_api / node_work_api still use the same names ──────

def test_file_api_aliases_shared_sets():
    from ari.viz import file_api, node_work_api
    assert file_api._TEXT_EXTENSIONS is fs.TEXT_EXTENSIONS
    assert node_work_api._BINARY_EXTENSIONS is fs.BINARY_EXTENSIONS
    assert node_work_api._SKIP_DIRS is fs.SKIP_DIRS
