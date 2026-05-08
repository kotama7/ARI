r"""Tests for the Code Availability injector.

Covers:
- Idempotent / replace semantics of inject_code_availability
- T-PA-skip: when ref/sha are both empty, the section is omitted (and
  any prior injected block is stripped on re-run)
- LaTeX safety: macros and section header land before \end{document}
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.server import (  # type: ignore
    inject_code_availability,
    _CODE_AVAIL_BEGIN,
    _CODE_AVAIL_END,
)


_BASIC_TEX = (
    r"""\documentclass{article}
\begin{document}
\section{Hello}
World.
\end{document}
"""
)


def _write_tex(tmp_path: Path, body: str = _BASIC_TEX) -> Path:
    p = tmp_path / "paper.tex"
    p.write_text(body, encoding="utf-8")
    return p


def test_inject_creates_section(tmp_path: Path):
    tex = _write_tex(tmp_path)
    digest = "f" * 64
    res = inject_code_availability(str(tex), ref="ari://abc123", sha256=digest)
    assert res["injected"] is True
    content = tex.read_text(encoding="utf-8")
    assert _CODE_AVAIL_BEGIN in content
    assert _CODE_AVAIL_END in content
    assert r"\section*{Code Availability}" in content
    assert r"\coderef{ari://abc123}" in content
    assert r"\codedigest{" + digest + "}" in content
    # The block sits before \end{document}, never after.
    assert content.find(_CODE_AVAIL_BEGIN) < content.find(r"\end{document}")


def test_inject_is_idempotent(tmp_path: Path):
    tex = _write_tex(tmp_path)
    digest = "a" * 64
    inject_code_availability(str(tex), ref="ari://abc", sha256=digest)
    snapshot = tex.read_text(encoding="utf-8")
    res2 = inject_code_availability(str(tex), ref="ari://abc", sha256=digest)
    assert res2["injected"] is True
    assert res2.get("noop") is True
    assert tex.read_text(encoding="utf-8") == snapshot


def test_inject_replaces_on_digest_change(tmp_path: Path):
    tex = _write_tex(tmp_path)
    inject_code_availability(str(tex), ref="ari://v1", sha256="1" * 64)
    res2 = inject_code_availability(str(tex), ref="ari://v2", sha256="2" * 64)
    assert res2["injected"] is True
    assert res2.get("replaced") is True
    content = tex.read_text(encoding="utf-8")
    # Only one block — the new one.
    assert content.count(_CODE_AVAIL_BEGIN) == 1
    assert "ari://v1" not in content
    assert "1" * 64 not in content
    assert "ari://v2" in content
    assert "2" * 64 in content


# T-PA-skip: empty ref + empty sha → no section (and prior block stripped)
def test_inject_skips_when_no_context(tmp_path: Path):
    tex = _write_tex(tmp_path)
    res = inject_code_availability(str(tex), ref="", sha256="")
    assert res["injected"] is False
    assert _CODE_AVAIL_BEGIN not in tex.read_text(encoding="utf-8")


def test_inject_strips_prior_block_when_context_clears(tmp_path: Path):
    tex = _write_tex(tmp_path)
    inject_code_availability(str(tex), ref="ari://abc", sha256="b" * 64)
    assert _CODE_AVAIL_BEGIN in tex.read_text(encoding="utf-8")
    # A subsequent finalize without ref/sha should clean up.
    res = inject_code_availability(str(tex), ref="", sha256="")
    assert res["injected"] is False
    assert res.get("stripped_prior") is True
    assert _CODE_AVAIL_BEGIN not in tex.read_text(encoding="utf-8")


def test_inject_handles_missing_end_document(tmp_path: Path):
    """Partial drafts may lack \\end{document}; the injector should append at end."""
    tex = tmp_path / "draft.tex"
    tex.write_text(r"\documentclass{article}\begin{document}Body", encoding="utf-8")
    res = inject_code_availability(str(tex), ref="ari://x", sha256="c" * 64)
    assert res["injected"] is True
    content = tex.read_text(encoding="utf-8")
    assert _CODE_AVAIL_BEGIN in content
    assert content.endswith("\n")


def test_inject_doi_and_license(tmp_path: Path):
    tex = _write_tex(tmp_path)
    res = inject_code_availability(
        str(tex),
        ref="ari://abc",
        sha256="d" * 64,
        doi="10.5281/zenodo.123456",
        license_id="MIT",
    )
    assert res["injected"] is True
    content = tex.read_text(encoding="utf-8")
    assert "10.5281/zenodo.123456" in content
    assert "MIT" in content


def test_inject_missing_tex_returns_error(tmp_path: Path):
    res = inject_code_availability(str(tmp_path / "nope.tex"), ref="ari://x", sha256="0" * 64)
    assert res["injected"] is False
    assert "not found" in res.get("error", "")
