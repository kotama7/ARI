"""Intentionally violates MCP stdout framing."""

import sys


sys.stderr.write("fixture-malformed-diagnostic\n")
sys.stderr.flush()
sys.stdout.write("this is not json-rpc\n")
sys.stdout.flush()
