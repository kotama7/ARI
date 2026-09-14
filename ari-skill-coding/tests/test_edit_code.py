"""edit_code must fail rather than land an edit in the wrong place.

92.2% of writes in the previous campaign rewrote a file that already existed.
Re-emitting a whole kernel to change a few lines costs tokens and risks dropping
working code, which is what this tool exists to avoid. The important property is
not that it edits — it is that an AMBIGUOUS edit is refused: an edit that
silently lands somewhere else is worse than one that fails, because the agent
then reports success on a kernel it did not change.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from server import _edit_code  # noqa: E402


def test_replaces_a_unique_snippet(tmp_path):
    (tmp_path / "k.c").write_text("int a;\nint b;\nint c;\n")
    r = _edit_code("k.c", "int b;", "long b;", False, str(tmp_path))
    assert r["status"] == "edited" and r["replacements"] == 1
    assert (tmp_path / "k.c").read_text() == "int a;\nlong b;\nint c;\n"


def test_refuses_an_ambiguous_edit(tmp_path):
    (tmp_path / "k.c").write_text("x = 1;\nx = 1;\n")
    r = _edit_code("k.c", "x = 1;", "x = 2;", False, str(tmp_path))
    assert r["status"] == "error" and "appears 2 times" in r["error"]
    assert (tmp_path / "k.c").read_text() == "x = 1;\nx = 1;\n", "file was modified anyway"


def test_replace_all_is_opt_in(tmp_path):
    (tmp_path / "k.c").write_text("x = 1;\nx = 1;\n")
    r = _edit_code("k.c", "x = 1;", "x = 2;", True, str(tmp_path))
    assert r["status"] == "edited" and r["replacements"] == 2
    assert (tmp_path / "k.c").read_text() == "x = 2;\nx = 2;\n"


def test_missing_snippet_is_an_error_not_a_no_op(tmp_path):
    (tmp_path / "k.c").write_text("int a;\n")
    r = _edit_code("k.c", "int zzz;", "int b;", False, str(tmp_path))
    assert r["status"] == "error" and "not found" in r["error"]
    assert (tmp_path / "k.c").read_text() == "int a;\n"


def test_missing_file_points_at_write_code(tmp_path):
    r = _edit_code("nope.c", "a", "b", False, str(tmp_path))
    assert r["status"] == "error" and "write_code" in r["error"]


def test_whitespace_must_match_exactly(tmp_path):
    """A tab is not four spaces.

    Note what does NOT hold: fewer spaces than the file has still matches, since
    "  int a;" is a substring of "    int a;". Matching is plain substring
    matching, not line-aware, and the tool's guarantee is uniqueness rather than
    line alignment.
    """
    (tmp_path / "k.c").write_text("void f(){\n    int a;\n}\n")
    assert _edit_code("k.c", "int a;", "int b;", False, str(tmp_path))["status"] == "edited"
    (tmp_path / "k.c").write_text("void f(){\n    int a;\n}\n")
    r = _edit_code("k.c", "\tint a;", "\tint b;", False, str(tmp_path))
    assert r["status"] == "error" and "not found" in r["error"]
