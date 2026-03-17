"""Root conftest: mock the mcp package if it is not installed."""

import sys
import types


def _ensure_mcp_mock():
    """Create a minimal mock of mcp.server.fastmcp.FastMCP if mcp is missing."""
    try:
        import mcp  # noqa: F401
    except ImportError:

        class _FastMCP:
            def __init__(self, name: str = ""):
                self.name = name

            def tool(self, *args, **kwargs):
                """No-op decorator that returns the original function."""
                def decorator(fn):
                    return fn
                if args and callable(args[0]):
                    return args[0]
                return decorator

            def run(self):
                pass

        mcp_mod = types.ModuleType("mcp")
        mcp_server = types.ModuleType("mcp.server")
        mcp_fastmcp = types.ModuleType("mcp.server.fastmcp")
        mcp_fastmcp.FastMCP = _FastMCP
        mcp_server.fastmcp = mcp_fastmcp
        mcp_mod.server = mcp_server
        sys.modules["mcp"] = mcp_mod
        sys.modules["mcp.server"] = mcp_server
        sys.modules["mcp.server.fastmcp"] = mcp_fastmcp


_ensure_mcp_mock()
