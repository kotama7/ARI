"""
Tests for the File Explorer feature — backend API and frontend integration.
Covers: filetree listing, filecontent reading, path traversal protection,
binary file filtering, directory skipping, i18n keys, and component wiring.
"""
import json
from pathlib import Path

import pytest

from ari.viz import state as _st


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    """Isolate shared state for every test."""
    monkeypatch.setattr(_st, "_checkpoint_dir", None)
    monkeypatch.setattr(_st, "_last_proc", None)
    monkeypatch.setattr(_st, "_last_log_fh", None)
    monkeypatch.setattr(_st, "_last_log_path", None)
    monkeypatch.setattr(_st, "_last_experiment_md", None)
    monkeypatch.setattr(_st, "_launch_llm_model", None)
    monkeypatch.setattr(_st, "_launch_llm_provider", None)
    monkeypatch.setattr(_st, "_launch_config", None)
    monkeypatch.setattr(_st, "_gpu_monitor_proc", None)
    monkeypatch.setattr(_st, "_clients", [])
    monkeypatch.setattr(_st, "_loop", None)
    monkeypatch.setattr(_st, "_last_mtime", 0.0)
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr(_st, "_settings_path", settings)
    monkeypatch.setattr(_st, "_env_write_path", tmp_path / ".env")


def _make_checkpoint(tmp_path, name="20260101_TestExp"):
    """Create a checkpoint directory with some files and subdirectories."""
    ckpt = tmp_path / "checkpoints" / name
    ckpt.mkdir(parents=True)
    # Files at root
    (ckpt / "tree.json").write_text('{"nodes": []}')
    (ckpt / "experiment.md").write_text("# Research Goal\nTest goal\n")
    (ckpt / "results.json").write_text('{"score": 0.5}')
    # Python subdir
    code_dir = ckpt / "code"
    code_dir.mkdir()
    (code_dir / "main.py").write_text("print('hello')\n")
    (code_dir / "utils.py").write_text("def helper(): pass\n")
    # Binary file
    (ckpt / "model.pkl").write_bytes(b"\x80\x04\x95" + b"\x00" * 100)
    # Nested dirs
    sub = ckpt / "paper" / "figures"
    sub.mkdir(parents=True)
    (ckpt / "paper" / "full_paper.tex").write_text("\\documentclass{article}\n")
    (sub / "fig_01.png").write_bytes(b"\x89PNG" + b"\x00" * 50)
    # __pycache__ (should be skipped)
    pycache = ckpt / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-311.pyc").write_bytes(b"\x00" * 20)
    # .git (should be skipped)
    git_dir = ckpt / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n")
    return ckpt


# ══════════════════════════════════════════════════════════════════════════════
# 1. _api_checkpoint_filetree
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointFiletree:
    """Tests for the file tree listing API."""

    def test_filetree_not_found(self, tmp_path, monkeypatch):
        """Non-existent checkpoint returns error."""
        from ari.viz.api_state import _api_checkpoint_filetree
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree("nonexistent_checkpoint")
        assert "error" in result

    def test_filetree_returns_tree(self, tmp_path, monkeypatch):
        """Valid checkpoint returns a 'tree' list."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        assert "tree" in result
        assert isinstance(result["tree"], list)
        assert len(result["tree"]) > 0

    def test_filetree_contains_files_and_dirs(self, tmp_path, monkeypatch):
        """Tree includes both file and dir entries."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        tree = result["tree"]
        types = {e["type"] for e in tree}
        assert "file" in types
        assert "dir" in types

    def test_filetree_skips_pycache(self, tmp_path, monkeypatch):
        """__pycache__ directories are excluded."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        names = [e["name"] for e in result["tree"]]
        assert "__pycache__" not in names

    def test_filetree_skips_git(self, tmp_path, monkeypatch):
        """.git directories are excluded (starts with dot)."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        names = [e["name"] for e in result["tree"]]
        assert ".git" not in names

    def test_filetree_binary_not_readable(self, tmp_path, monkeypatch):
        """Binary files (e.g. .pkl) have readable=False."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)

        def _find(tree, name):
            for e in tree:
                if e["name"] == name:
                    return e
                if e.get("children"):
                    found = _find(e["children"], name)
                    if found:
                        return found
            return None

        pkl = _find(result["tree"], "model.pkl")
        assert pkl is not None
        assert pkl["readable"] is False

    def test_filetree_text_readable(self, tmp_path, monkeypatch):
        """Text files (e.g. .py, .md, .json) have readable=True."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)

        def _find(tree, name):
            for e in tree:
                if e["name"] == name:
                    return e
                if e.get("children"):
                    found = _find(e["children"], name)
                    if found:
                        return found
            return None

        md = _find(result["tree"], "experiment.md")
        assert md is not None
        assert md["readable"] is True

    def test_filetree_nested_structure(self, tmp_path, monkeypatch):
        """Directories contain children."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        code_dir = next((e for e in result["tree"] if e["name"] == "code"), None)
        assert code_dir is not None
        assert code_dir["type"] == "dir"
        assert "children" in code_dir
        child_names = [c["name"] for c in code_dir["children"]]
        assert "main.py" in child_names
        assert "utils.py" in child_names

    def test_filetree_has_size(self, tmp_path, monkeypatch):
        """File entries include size."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)

        def _find(tree, name):
            for e in tree:
                if e["name"] == name:
                    return e
                if e.get("children"):
                    found = _find(e["children"], name)
                    if found:
                        return found
            return None

        md = _find(result["tree"], "experiment.md")
        assert md is not None
        assert "size" in md
        assert md["size"] > 0

    def test_filetree_has_ext(self, tmp_path, monkeypatch):
        """File entries include file extension."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)

        def _find(tree, name):
            for e in tree:
                if e["name"] == name:
                    return e
                if e.get("children"):
                    found = _find(e["children"], name)
                    if found:
                        return found
            return None

        py = _find(result["tree"], "main.py")
        assert py is not None
        assert py["ext"] == ".py"

    def test_filetree_path_relative(self, tmp_path, monkeypatch):
        """File paths are relative to the checkpoint root."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)

        def _find(tree, name):
            for e in tree:
                if e["name"] == name:
                    return e
                if e.get("children"):
                    found = _find(e["children"], name)
                    if found:
                        return found
            return None

        py = _find(result["tree"], "main.py")
        assert py is not None
        assert py["path"] == "code/main.py"

    def test_filetree_dirs_sorted_first(self, tmp_path, monkeypatch):
        """Directories appear before files in each level."""
        from ari.viz.api_state import _api_checkpoint_filetree
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filetree(ckpt.name)
        tree = result["tree"]
        dir_found = False
        for entry in tree:
            if entry["type"] == "dir":
                dir_found = True
            elif entry["type"] == "file" and not dir_found:
                # Dirs come first so if we see a file before any dir, fail
                # (only if dirs exist)
                pass
        # Check that first entries are dirs
        dirs_in_tree = [e for e in tree if e["type"] == "dir"]
        if dirs_in_tree:
            first_dir_idx = tree.index(dirs_in_tree[0])
            first_file = next((e for e in tree if e["type"] == "file"), None)
            if first_file:
                first_file_idx = tree.index(first_file)
                assert first_dir_idx < first_file_idx


# ══════════════════════════════════════════════════════════════════════════════
# 2. _api_checkpoint_filecontent
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointFilecontent:
    """Tests for the file content reading API."""

    def test_filecontent_not_found_checkpoint(self, tmp_path, monkeypatch):
        """Non-existent checkpoint returns error."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent("nonexistent", "file.py")
        assert "error" in result

    def test_filecontent_not_found_file(self, tmp_path, monkeypatch):
        """Non-existent file returns error."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "nonexistent.py")
        assert "error" in result
        assert "not found" in result["error"]

    def test_filecontent_reads_text(self, tmp_path, monkeypatch):
        """Text file content is returned correctly."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "experiment.md")
        assert "error" not in result
        assert "content" in result
        assert "Research Goal" in result["content"]

    def test_filecontent_nested_file(self, tmp_path, monkeypatch):
        """Nested file content is readable."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "code/main.py")
        assert "error" not in result
        assert "print" in result["content"]

    def test_filecontent_binary_rejected(self, tmp_path, monkeypatch):
        """Binary files return an error."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "model.pkl")
        assert "error" in result
        assert "binary" in result["error"].lower()

    def test_filecontent_path_traversal_denied(self, tmp_path, monkeypatch):
        """Path traversal attempts are blocked."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        # Create a secret file outside checkpoint
        (tmp_path / "secret.txt").write_text("secret data")
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "../../secret.txt")
        assert "error" in result
        assert "traversal" in result["error"].lower() or "not found" in result["error"].lower()

    def test_filecontent_too_large(self, tmp_path, monkeypatch):
        """Files larger than 5MB are rejected."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        big_file = ckpt / "big.txt"
        big_file.write_text("x" * (5_000_001))
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "big.txt")
        assert "error" in result
        assert "large" in result["error"].lower()

    def test_filecontent_returns_name(self, tmp_path, monkeypatch):
        """Response includes the filename."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "experiment.md")
        assert result.get("name") == "experiment.md"

    def test_filecontent_png_rejected(self, tmp_path, monkeypatch):
        """Image files (binary) return an error."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "paper/figures/fig_01.png")
        assert "error" in result

    def test_filecontent_tex_readable(self, tmp_path, monkeypatch):
        """.tex files are readable."""
        from ari.viz.api_state import _api_checkpoint_filecontent
        ckpt = _make_checkpoint(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = _api_checkpoint_filecontent(ckpt.name, "paper/full_paper.tex")
        assert "error" not in result
        assert "documentclass" in result["content"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Server routing (API endpoints exist)
# ══════════════════════════════════════════════════════════════════════════════

class TestServerRouting:
    """Verify that server.py has the file explorer API routes."""

    def test_server_imports_filetree_api(self):
        """server.py imports _api_checkpoint_filetree."""
        server_src = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "_api_checkpoint_filetree" in server_src

    def test_server_imports_filecontent_api(self):
        """server.py imports _api_checkpoint_filecontent."""
        server_src = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "_api_checkpoint_filecontent" in server_src

    def test_server_has_filetree_route(self):
        """server.py has a route for /filetree."""
        server_src = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "/filetree" in server_src

    def test_server_has_filecontent_route(self):
        """server.py has a route for /filecontent."""
        server_src = (Path(__file__).parent.parent / "ari" / "viz" / "server.py").read_text()
        assert "/filecontent" in server_src


# ══════════════════════════════════════════════════════════════════════════════
# 4. Frontend integration
# ══════════════════════════════════════════════════════════════════════════════

COMPONENTS_DIR = Path(__file__).parent.parent / "ari" / "viz" / "frontend" / "src" / "components"
I18N_DIR = Path(__file__).parent.parent / "ari" / "viz" / "frontend" / "src" / "i18n"


class TestFrontendIntegration:
    """Verify frontend components and i18n keys for the file explorer."""

    def test_file_explorer_component_exists(self):
        """FileExplorer.tsx exists."""
        assert (COMPONENTS_DIR / "Tree" / "FileExplorer.tsx").exists()

    def test_tree_page_imports_file_explorer(self):
        """TreePage.tsx imports FileExplorer."""
        src = (COMPONENTS_DIR / "Tree" / "TreePage.tsx").read_text()
        assert "FileExplorer" in src

    def test_tree_page_has_toggle_button(self):
        """TreePage.tsx has a toggle button for the file explorer."""
        src = (COMPONENTS_DIR / "Tree" / "TreePage.tsx").read_text()
        assert "showFileExplorer" in src
        assert "file_explorer_btn" in src

    def test_file_explorer_uses_i18n(self):
        """FileExplorer.tsx uses useI18n for translations."""
        src = (COMPONENTS_DIR / "Tree" / "FileExplorer.tsx").read_text()
        assert "useI18n" in src

    def test_file_explorer_exported(self):
        """FileExplorer is exported from Tree/index.ts."""
        src = (COMPONENTS_DIR / "Tree" / "index.ts").read_text()
        assert "FileExplorer" in src

    def test_file_explorer_fetches_filetree(self):
        """FileExplorer.tsx fetches from /api/checkpoint/.../filetree."""
        src = (COMPONENTS_DIR / "Tree" / "FileExplorer.tsx").read_text()
        assert "/filetree" in src

    def test_file_explorer_fetches_filecontent(self):
        """FileExplorer.tsx fetches from /api/checkpoint/.../filecontent."""
        src = (COMPONENTS_DIR / "Tree" / "FileExplorer.tsx").read_text()
        assert "/filecontent" in src

    def test_file_explorer_has_tree_row(self):
        """FileExplorer.tsx renders TreeRow for directory tree."""
        src = (COMPONENTS_DIR / "Tree" / "FileExplorer.tsx").read_text()
        assert "TreeRow" in src


class TestI18NFileExplorerKeys:
    """Verify i18n keys for file explorer exist in all languages."""

    def _extract_keys(self, path):
        import re
        src = path.read_text()
        keys = set()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            m = re.match(r"(\w+)\s*:", stripped)
            if m:
                keys.add(m.group(1))
        return keys

    def test_en_has_file_explorer_keys(self):
        """en.ts has file_explorer_* keys."""
        keys = self._extract_keys(I18N_DIR / "en.ts")
        assert "file_explorer_title" in keys
        assert "file_explorer_back" in keys
        assert "file_explorer_empty" in keys
        assert "file_explorer_btn" in keys

    def test_ja_has_file_explorer_keys(self):
        """ja.ts has file_explorer_* keys."""
        keys = self._extract_keys(I18N_DIR / "ja.ts")
        assert "file_explorer_title" in keys
        assert "file_explorer_back" in keys
        assert "file_explorer_empty" in keys
        assert "file_explorer_btn" in keys

    def test_zh_has_file_explorer_keys(self):
        """zh.ts has file_explorer_* keys."""
        keys = self._extract_keys(I18N_DIR / "zh.ts")
        assert "file_explorer_title" in keys
        assert "file_explorer_back" in keys
        assert "file_explorer_empty" in keys
        assert "file_explorer_btn" in keys
