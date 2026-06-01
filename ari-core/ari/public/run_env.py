"""Public re-export of :mod:`ari.agent.run_env` (Phase 4 / refactor req 09).

Skills should import run-environment capture helpers from here rather than
reaching into ``ari.agent.run_env`` directly. Currently used by
``ari-skill-coding`` (``capture_env``) and ``ari-skill-hpc``
(``shell_capture_snippet``). Thin re-export so core can refactor the
implementation freely while the contract stays put; the internal
``ari.agent.run_env`` path keeps working.
"""

from ari.agent.run_env import *  # noqa: F401,F403
from ari.agent import run_env as _impl

__all__ = getattr(_impl, "__all__", [name for name in dir(_impl) if not name.startswith("_")])
