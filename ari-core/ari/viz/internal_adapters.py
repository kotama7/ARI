"""Thin adapters over ari-core internals that have no ``ari.public.*`` surface.

Subtask 021 §7.3: viz handlers/services should depend on ``ari.public.*`` where a
public entry exists (``ari.public.paths``, ``ari.public.container``,
``ari.public.cost_tracker``, ``ari.public.run_env``). The one remaining internal
touchpoint with **no** public equivalent yet — ``ari.pidfile`` — lives here so a
future public-API subtask can promote it in one spot.

Memory backend access is **not** an internal reach anymore: it is funnelled
through ``ari.memory.get_backend`` (subtask 013, the sole sanctioned core→skill
edge, confined to ``ari/memory/**``). ``memory_backend`` below simply forwards
to that funnel so viz never imports the skill package directly.

REVIEW_REQUIRED: promote ``ari.pidfile`` (pid liveness) to ``ari.public.*``.

Imports are performed lazily inside each wrapper so a broken/absent optional
dependency surfaces at call time exactly as the former in-handler imports did,
and so test monkeypatches of the underlying module are picked up per call.
"""
from __future__ import annotations

from pathlib import Path


def pid_status(checkpoint_dir) -> "str":
    """Return ``ari.pidfile.check_pid`` status for *checkpoint_dir*.

    REVIEW_REQUIRED: promote ``ari.pidfile`` to ``ari.public.*``.
    """
    from ari.pidfile import check_pid
    return check_pid(Path(checkpoint_dir))


def read_pid(checkpoint_dir):
    """Return the recorded PID for *checkpoint_dir* via ``ari.pidfile.read_pid``.

    REVIEW_REQUIRED: promote ``ari.pidfile`` to ``ari.public.*``.
    """
    from ari.pidfile import read_pid as _read_pid
    return _read_pid(Path(checkpoint_dir))


def memory_backend(checkpoint_dir):
    """Return the memory backend for *checkpoint_dir*.

    Forwards to ``ari.memory.get_backend`` — the sole sanctioned core→skill
    memory funnel (subtask 013). viz code reaches the skill backend through this
    wrapper (or ``ari.memory`` directly) rather than importing the skill.
    """
    from ari.memory import get_backend
    return get_backend(checkpoint_dir=checkpoint_dir)
