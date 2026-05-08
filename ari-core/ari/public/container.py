"""Public re-export of :mod:`ari.container` (Phase 4).

Skills should import container helpers from here (or ``ari.public``)
rather than reaching into ``ari.container`` directly.
"""

from ari.container import *  # noqa: F401,F403
from ari import container as _impl

__all__ = getattr(_impl, "__all__", [name for name in dir(_impl) if not name.startswith("_")])
