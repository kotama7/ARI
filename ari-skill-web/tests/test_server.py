import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def test_web_search_returns_dict():
    from server import web_search
    result = web_search("OpenMP HPC benchmark", n=2)
    assert isinstance(result, dict)
    assert "results" in result or "error" in result

def test_fetch_url_returns_dict():
    from server import fetch_url
    result = fetch_url("https://example.com", max_chars=500)
    assert isinstance(result, dict)
    assert "text" in result or "error" in result

def test_search_arxiv_returns_dict():
    from server import search_arxiv
    result = search_arxiv("OpenMP performance optimization", max_results=2)
    assert isinstance(result, dict)
    assert "papers" in result or "error" in result

def test_web_search_structure():
    from server import web_search
    result = web_search("python performance", n=3)
    if "results" in result and result["results"]:
        for r in result["results"]:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r

def test_fetch_url_error_handling():
    from server import fetch_url
    result = fetch_url("https://this-url-does-not-exist-12345.invalid")
    assert isinstance(result, dict)
    assert "error" in result or "text" in result

def test_search_arxiv_structure():
    from server import search_arxiv
    result = search_arxiv("compiler optimization benchmark", max_results=2)
    if "papers" in result and result["papers"]:
        for p in result["papers"]:
            assert "title" in p
            assert "url" in p


# ══════════════════════════════════════════════════════════════════════════════
# list_uploaded_files / read_uploaded_file
# ══════════════════════════════════════════════════════════════════════════════

import tempfile, shutil

class TestUploadedFileTools:
    """Tests for the checkpoint file-access MCP tools."""

    def _make_ckpt(self):
        d = tempfile.mkdtemp(prefix="ari_test_ckpt_")
        return d

    def test_list_uploaded_files_empty_env(self, monkeypatch):
        import server
        monkeypatch.setattr(server, "_CHECKPOINT_DIR", "")
        result = server.list_uploaded_files()
        assert result["files"] == []
        assert "error" in result

    def test_list_uploaded_files_with_files(self, monkeypatch):
        import server
        d = self._make_ckpt()
        try:
            # Create user files inside uploads/ subdirectory
            uploads = os.path.join(d, "uploads")
            os.makedirs(uploads, exist_ok=True)
            open(os.path.join(uploads, "data.csv"), "w").write("a,b\n1,2")
            open(os.path.join(uploads, "notes.md"), "w").write("# Notes")
            # System files in checkpoint root should NOT appear
            open(os.path.join(d, "launch_config.json"), "w").write("{}")
            open(os.path.join(d, "idea.json"), "w").write("{}")
            monkeypatch.setattr(server, "_CHECKPOINT_DIR", d)
            result = server.list_uploaded_files()
            names = [f["name"] for f in result["files"]]
            assert "data.csv" in names
            assert "notes.md" in names
            # System files in root should never appear
            assert "launch_config.json" not in names
            assert "idea.json" not in names
        finally:
            shutil.rmtree(d)

    def test_list_uploaded_files_nonexistent_dir(self, monkeypatch):
        import server
        monkeypatch.setattr(server, "_CHECKPOINT_DIR", "/tmp/ari_nonexistent_dir_xyz")
        result = server.list_uploaded_files()
        assert result["files"] == []

    def test_read_uploaded_file_success(self, monkeypatch):
        import server
        d = self._make_ckpt()
        try:
            uploads = os.path.join(d, "uploads")
            os.makedirs(uploads, exist_ok=True)
            open(os.path.join(uploads, "experiment.md"), "w").write("## Goal\nTest")
            monkeypatch.setattr(server, "_CHECKPOINT_DIR", d)
            result = server.read_uploaded_file("experiment.md")
            assert result["name"] == "experiment.md"
            assert "## Goal" in result["content"]
            assert result["size_bytes"] > 0
        finally:
            shutil.rmtree(d)

    def test_read_uploaded_file_not_found(self, monkeypatch):
        import server
        d = self._make_ckpt()
        try:
            monkeypatch.setattr(server, "_CHECKPOINT_DIR", d)
            result = server.read_uploaded_file("nope.txt")
            assert "error" in result
        finally:
            shutil.rmtree(d)

    def test_read_uploaded_file_path_traversal(self, monkeypatch):
        import server
        d = self._make_ckpt()
        try:
            monkeypatch.setattr(server, "_CHECKPOINT_DIR", d)
            result = server.read_uploaded_file("../../etc/passwd")
            # Should sanitize to just "passwd" which won't exist in the dir
            assert "error" in result
        finally:
            shutil.rmtree(d)

    def test_read_uploaded_file_truncation(self, monkeypatch):
        import server
        d = self._make_ckpt()
        try:
            uploads = os.path.join(d, "uploads")
            os.makedirs(uploads, exist_ok=True)
            content = "x" * 1000
            open(os.path.join(uploads, "big.txt"), "w").write(content)
            monkeypatch.setattr(server, "_CHECKPOINT_DIR", d)
            result = server.read_uploaded_file("big.txt", max_chars=100)
            assert "truncated" in result["content"]
            assert len(result["content"]) < 500
        finally:
            shutil.rmtree(d)

    def test_read_uploaded_file_no_env(self, monkeypatch):
        import server
        monkeypatch.setattr(server, "_CHECKPOINT_DIR", "")
        result = server.read_uploaded_file("test.txt")
        assert "error" in result
