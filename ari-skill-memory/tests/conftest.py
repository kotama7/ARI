"""Test fixtures: ensure ARI_MEMORY_PATH is set before src.server is imported.

Without this the module-level STORE_PATH resolution raises RuntimeError.
Individual tests still patch STORE_PATH / GLOBAL_PATH to tmp_path.
"""
import os
import tempfile

os.environ.setdefault("ARI_MEMORY_PATH", os.path.join(tempfile.gettempdir(), "ari_test_memory_store.jsonl"))
os.environ.setdefault("ARI_GLOBAL_MEMORY_PATH", os.path.join(tempfile.gettempdir(), "ari_test_global_memory.jsonl"))
