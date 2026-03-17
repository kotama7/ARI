"""Tests for MemoryClient implementations."""
from ari.memory.local_client import LocalMemoryClient
from ari.memory.file_client import FileMemoryClient
import tempfile, os


def test_local_memory_add_and_search():
    m = LocalMemoryClient()
    m.add("speedup of 22.4x on Himeno", {"run": "abc"})
    results = m.search("speedup")
    assert len(results) > 0
    assert any("speedup" in r.get("content", "") for r in results)


def test_local_memory_get_all():
    m = LocalMemoryClient()
    m.add("entry one")
    m.add("entry two")
    assert len(m.get_all()) >= 2


def test_file_memory_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        fpath = f.name
    try:
        m = FileMemoryClient(fpath)
        m.add("persisted entry", {"node": "test"})
        m2 = FileMemoryClient(fpath)
        assert len(m2.get_all()) >= 1
    finally:
        os.unlink(fpath)


def test_file_memory_search():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        fpath = f.name
    try:
        m = FileMemoryClient(fpath)
        m.add("MFLOPS result 284172")
        results = m.search("MFLOPS")
        assert len(results) > 0
    finally:
        os.unlink(fpath)
