"""Allow ``python -m ari.cli`` to invoke the Typer app.

Phase 3A converted ``ari.cli`` from a single module into a package.
``python -m`` cannot execute a package directly, so we add a thin
``__main__.py`` that calls into the existing entry point.
"""

from ari.cli import app


if __name__ == "__main__":
    app()
