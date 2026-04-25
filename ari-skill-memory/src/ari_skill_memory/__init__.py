"""ari-skill-memory library package.

Provides the backend abstraction used by both the FastMCP server
(``src/server.py``) and ari-core's viz layer.
"""
from ari_skill_memory.backends import get_backend, MemoryBackend

__all__ = ["get_backend", "MemoryBackend"]
