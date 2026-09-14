"""Effective paper-mode resolution for the paper-archive execution switch
(paper-archive Task 01; docs/guides/execution_modes.md, "The paper execution
axis: `paper.mode`").

``paper.mode`` is the master switch; ``rqgm.paper.enabled`` is a redundant
safety interlock. Both must agree for the paper archive to activate; any
disagreement fails safe toward the current linear pipeline with a warning:

    paper.mode     rqgm.paper.enabled   effective paper mode
    linear         false                linear         (default; silent)
    linear         true                 linear         (warning: interlock set)
    rqgm_archive   false                linear         (warning: interlock off)
    rqgm_archive   true                 rqgm_archive

This is the paper-phase analog of :mod:`ari.rqgm.mode`. It reads ONLY
``paper.mode`` / ``rqgm.paper.enabled`` — never ``ari.mode`` /
``rqgm.enabled``: the two axes are independent, so all four combinations are
legal (``docs/guides/execution_modes.md``, "2×2 independence from
`ari.mode`"). ``ari.config._effective_paper_mode_str`` mirrors the activation
cell import-free so default paper runs never load this module; parity is
pinned by ``tests/test_paper_mode.py``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ari.config import ARIConfig

log = logging.getLogger(__name__)


class PaperMode(str, Enum):
    """The two paper-phase execution modes — the table above is the whole
    switch."""

    LINEAR = "linear"
    RQGM_ARCHIVE = "rqgm_archive"


def resolve_paper_mode(cfg: "ARIConfig") -> PaperMode:
    """Pure function of *cfg*; no I/O, no env reads (env is applied to cfg
    upstream by ``apply_paper_env_overrides``), never raises.

    Deliberately reads ONLY ``cfg.paper.mode`` / ``cfg.rqgm.paper.enabled`` —
    never ``ari.mode`` / ``rqgm.enabled``: the exploration axis is
    independent, so switching it must never move the paper
    mode. ``getattr`` defaults keep pre-feature cfg objects
    resolving to ``linear``.
    """
    mode = getattr(getattr(cfg, "paper", None), "mode", "linear")
    enabled = bool(
        getattr(getattr(getattr(cfg, "rqgm", None), "paper", None),
                "enabled", False)
    )
    if mode == "rqgm_archive" and enabled:
        return PaperMode.RQGM_ARCHIVE
    if mode == "rqgm_archive" or enabled:
        log.warning(
            "paper.mode=%s but rqgm.paper.enabled=%s; falling back to linear",
            mode,
            enabled,
        )
    return PaperMode.LINEAR
