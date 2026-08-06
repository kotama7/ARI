import os
import shutil
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_web_search_returns_dict():
    from server import web_search

    rows = [{"title": "OpenMP", "url": "https://example.org/a", "snippet": "HPC"}]
    with patch("server._search_duckduckgo_rows", return_value=rows):
        result = web_search("OpenMP HPC benchmark", n=2, mode="live")
    assert isinstance(result, dict)
    assert result["records"][0]["title"] == "OpenMP"
    assert "results" not in result


def test_fetch_url_returns_dict():
    from server import fetch_url
    from network_policy import FetchedResponse

    response = FetchedResponse(
        url="https://example.com/",
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=b"<html><title>Example</title><body>safe text</body></html>",
        redirect_chain=(),
        pinned_ip="93.184.216.34",
    )
    with patch("server.fetch_pinned", return_value=response):
        result = fetch_url("https://example.com", max_chars=500, mode="live")
    assert isinstance(result, dict)
    assert "safe text" in result["text"]


def test_web_search_structure():
    from server import web_search

    rows = [
        {"title": "Python", "url": "https://example.org/p", "snippet": "Performance"}
    ]
    with patch("server._search_duckduckgo_rows", return_value=rows):
        result = web_search("python performance", n=3, mode="live")
    if result["records"]:
        for r in result["records"]:
            assert "title" in r
            assert "source_url" in r
            assert "abstract" in r


def test_fetch_url_error_handling():
    from server import fetch_url
    from network_policy import NetworkPolicyError

    with pytest.raises(NetworkPolicyError, match="non-public"):
        fetch_url("http://127.0.0.1", mode="live")


# ══════════════════════════════════════════════════════════════════════════════
# list_uploaded_files / read_uploaded_file
# ══════════════════════════════════════════════════════════════════════════════


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
