"""Make the harness importable next to its tests (it is not an installed
package — it ships with the workspace).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
