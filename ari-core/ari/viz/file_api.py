"""REST API: per-checkpoint file enumeration + read/save/upload/delete + LaTeX compile.

Phase 3B PR-3B-2 (viz/REFACTORING.md §2 Step 2): extracted from
``ari/viz/api_state.py``.  ``api_state.py`` keeps a re-export facade
so downstream callers (and the route table inside ``server.py``) see
the same names regardless of where each function landed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .services import file_service as _fs


log = logging.getLogger(__name__)

# Phase 3B PR-3B-2: module-level constants restored from the legacy
# ``api_state.py``.  They live here because they are only used by the
# functions in this file.
PAPER_DIR_NAME = "paper"

# Subtask 023: the editable-text extension set is now owned by the shared
# FileService (single source of truth). Alias preserves the module-local name
# used by ``_api_checkpoint_files`` and any external reference.
_TEXT_EXTENSIONS = _fs.TEXT_EXTENSIONS

_PAPER_ROOT_ARTEFACTS = (
    "full_paper.tex", "full_paper.pdf", "full_paper.bbl", "refs.bib",
)
_FIGURE_GLOBS = (
    "fig_*.pdf", "fig_*.png", "fig_*.eps", "fig_*.svg",
    "fig_*.jpg", "fig_*.jpeg", "fig_*.tiff",
)


# Phase 3B PR-3B-2: bare-name wrappers that defer to ``api_state``
# at call time so ``monkeypatch.setattr(api_state, name, ...)``
# in tests intercepts the helper this module's functions call.
def _resolve_checkpoint_dir(*args, **kwargs):  # noqa: D401
    from . import api_state as _as
    return _as._resolve_checkpoint_dir(*args, **kwargs)



def _ensure_paper_dir(ckpt_id: str) -> tuple[Path | None, str | None]:
    """Return the paper/ dir for a checkpoint, creating & seeding it if needed.

    Historically this only seeded when paper/ did not yet exist. That left
    the dir permanently empty when a first (failing) pipeline run created
    paper/figures/ and a subsequent successful run wrote full_paper.tex at
    the checkpoint root — the GUI's "Files" tab then showed "0 files".

    This version also detects drift: if any root-level paper artefact
    (full_paper.tex/pdf/bbl, refs.bib, fig_*.{pdf,png,...}) is newer than —
    or missing from — the paper/ subdir, it gets (re-)copied. mtime-based
    so user edits inside paper/ are preserved unless the root version is
    newer.

    Returns (paper_dir, error).  On success error is None.
    """
    import shutil
    d = _resolve_checkpoint_dir(ckpt_id)
    if d is None:
        return None, "checkpoint not found"
    paper = d / PAPER_DIR_NAME
    paper.mkdir(parents=True, exist_ok=True)
    fig_dir = paper / "figures"
    fig_dir.mkdir(exist_ok=True)

    def _copy_if_newer(src: Path, dst: Path) -> None:
        """Copy src → dst if dst is missing or older than src."""
        try:
            if not dst.exists():
                shutil.copy2(str(src), str(dst))
                return
            if src.stat().st_mtime > dst.stat().st_mtime + 1e-3:
                shutil.copy2(str(src), str(dst))
        except Exception as e:
            log.debug("paper-dir seed: %s → %s failed: %s", src, dst, e)

    # Root-level paper artefacts
    for name in _PAPER_ROOT_ARTEFACTS:
        src = d / name
        if src.exists() and src.is_file():
            _copy_if_newer(src, paper / name)

    # Figure images (only the primary PDF/PNG go to the LaTeX editor;
    # keep the PNG companions so the GUI can render previews).
    for pattern in _FIGURE_GLOBS:
        for src in d.glob(pattern):
            if src.is_file():
                _copy_if_newer(src, fig_dir / src.name)

    return paper, None



def _api_checkpoint_files(ckpt_id: str) -> dict:
    """List files inside checkpoint paper/ directory."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    files: list[dict] = []
    for f in sorted(paper.rglob("*")):
        if f.is_dir():
            continue
        try:
            rel = str(f.relative_to(paper))
        except ValueError:
            continue
        try:
            size = f.stat().st_size
        except Exception:
            size = 0
        ext = f.suffix.lower()
        files.append({
            "name": rel,
            "size": size,
            "editable": ext in _TEXT_EXTENSIONS,
            "ext": ext,
            "abs_path": str(f),
        })
    return {"id": ckpt_id, "path": str(paper), "files": files}



def _api_checkpoint_file_read(ckpt_id: str, filename: str) -> dict:
    """Read content of a single file in checkpoint paper/ dir."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target, err = _fs.safe_resolve(paper, filename)
    if err:
        return {"error": err}
    if not target.exists() or not target.is_file():
        return {"error": "file not found"}
    if target.stat().st_size > _fs.MAX_TEXT_READ:
        return {"error": "file too large (>5MB)"}
    try:
        content = _fs.read_text(target)
    except Exception as e:
        return {"error": str(e)}
    return {"name": filename, "content": content}



def _resolve_paper_file(ckpt_id: str, filename: str) -> tuple[Path | None, str | None]:
    """Resolve a file path inside paper/ dir.  Returns (path, error)."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return None, err
    target, err = _fs.safe_resolve(paper, filename)
    if err:
        return None, err
    if not target.exists() or not target.is_file():
        return None, "file not found"
    if target.stat().st_size > _fs.MAX_BINARY_SERVE:
        return None, "file too large (>20MB)"
    return target, None



def _api_checkpoint_file_save(body: bytes) -> dict:
    """Save (overwrite) a text file in checkpoint paper/ dir."""
    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    filename = data.get("filename", "")
    content = data.get("content", "")
    if not ckpt_id or not filename:
        return {"error": "checkpoint_id and filename required"}
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target, err = _fs.safe_resolve(paper, filename)
    if err:
        return {"error": err}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _fs.write_text(target, content)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "path": str(target), "size": len(content.encode("utf-8"))}



def _api_checkpoint_file_upload(ckpt_id: str, filename: str, data: bytes) -> dict:
    """Upload a file into checkpoint paper/ dir."""
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    safe_name = Path(filename).name
    if not safe_name:
        return {"error": "invalid filename"}
    target, err = _fs.safe_resolve(paper, safe_name)
    if err:
        return {"error": err}
    try:
        _fs.write_bytes(target, data)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "name": safe_name, "path": str(target), "size": len(data)}



def _api_checkpoint_file_delete(body: bytes) -> dict:
    """Delete a single file from checkpoint paper/ dir."""
    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    filename = data.get("filename", "")
    if not ckpt_id or not filename:
        return {"error": "checkpoint_id and filename required"}
    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}
    target, err = _fs.safe_resolve(paper, filename)
    if err:
        return {"error": err}
    if not target.exists():
        return {"error": "file not found"}
    try:
        _fs.delete(target)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "deleted": filename}



def _api_checkpoint_compile(body: bytes) -> dict:
    """Compile LaTeX in checkpoint paper/ directory.

    Runs: pdflatex → bibtex → pdflatex → pdflatex  (standard 4-pass).
    """
    import subprocess as _sp
    import shutil

    data = json.loads(body)
    ckpt_id = data.get("checkpoint_id", "")
    main_file = data.get("main_file", "full_paper.tex")
    if not ckpt_id:
        return {"error": "checkpoint_id required"}

    paper, err = _ensure_paper_dir(ckpt_id)
    if err:
        return {"error": err}

    tex_path = paper / main_file
    if not tex_path.exists():
        return {"error": f"{main_file} not found in paper/"}

    pdflatex = os.environ.get("PDFLATEX_PATH", "pdflatex")
    bibtex = os.environ.get("BIBTEX_PATH", "bibtex")
    stem = main_file.replace(".tex", "")
    cwd = str(paper)
    logs: list[str] = []

    try:
        cmds = [
            [pdflatex, "-interaction=nonstopmode", main_file],
            [bibtex, stem],
            [pdflatex, "-interaction=nonstopmode", main_file],
            [pdflatex, "-interaction=nonstopmode", main_file],
        ]
        for cmd in cmds:
            r = _sp.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
            logs.append(f"$ {' '.join(cmd)}  (exit {r.returncode})")
            if r.stdout:
                logs.append(r.stdout[-1500:])
            if r.stderr:
                logs.append(r.stderr[-500:])
    except _sp.TimeoutExpired:
        logs.append("ERROR: compilation timed out")
        return {"ok": False, "log": "\n".join(logs)}
    except FileNotFoundError:
        return {"ok": False, "log": f"pdflatex not found ({pdflatex}). Install a LaTeX distribution."}

    pdf_path = paper / f"{stem}.pdf"
    success = pdf_path.exists() and pdf_path.stat().st_size > 1024

    # Copy PDF back to checkpoint root so the PDF viewer picks it up
    if success:
        d = _resolve_checkpoint_dir(ckpt_id)
        if d:
            try:
                shutil.copy2(str(pdf_path), str(d / f"{stem}.pdf"))
            except Exception:
                pass

    return {"ok": success, "log": "\n".join(logs)}

