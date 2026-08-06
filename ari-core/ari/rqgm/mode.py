"""Effective-mode resolution for the RQGM execution-mode switch (Task 01).

``ari.mode`` is the master switch; ``rqgm.enabled`` is a redundant safety
interlock. Both must agree for RQGM to activate; any disagreement fails safe
toward current behaviour (``simple_bfts``) with a warning:

    ari.mode      rqgm.enabled   effective mode
    simple_bfts   false          simple_bfts   (default; silent)
    simple_bfts   true           simple_bfts   (warning: interlock set)
    ari_rqgm      false          simple_bfts   (warning: interlock off)
    ari_rqgm      true           ari_rqgm

``ari.config._effective_mode_str`` mirrors the activation cell import-free so
default runs never load this module; parity is pinned by
``tests/test_rqgm_mode.py``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import ARIConfig

log = logging.getLogger(__name__)


class EffectiveMode(str, Enum):
    """The two ARI execution modes (plan 01 §5.2)."""

    SIMPLE_BFTS = "simple_bfts"
    ARI_RQGM = "ari_rqgm"


def resolve_effective_mode(cfg: "ARIConfig") -> EffectiveMode:
    """Pure function of *cfg*; no I/O, no env reads (env is applied to cfg
    upstream by ``apply_rqgm_env_overrides``), never raises.

    Deliberately reads ONLY ``cfg.ari.mode`` / ``cfg.rqgm.enabled`` — never
    ``proposal_router.*`` (VirSci optionality is orthogonal to the mode,
    plan 01 §5.6). ``getattr`` defaults keep pre-RQGM cfg objects resolving
    to ``simple_bfts``.
    """
    mode = getattr(getattr(cfg, "ari", None), "mode", "simple_bfts")
    enabled = bool(getattr(getattr(cfg, "rqgm", None), "enabled", False))
    if mode == "ari_rqgm" and enabled:
        return EffectiveMode.ARI_RQGM
    if mode == "ari_rqgm" or enabled:
        log.warning(
            "ari.mode=%s but rqgm.enabled=%s; falling back to simple_bfts",
            mode,
            enabled,
        )
    return EffectiveMode.SIMPLE_BFTS
