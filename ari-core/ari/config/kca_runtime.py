"""Single interlock resolver for Knowledge, Binding, and Assurance modes."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ari.config import ARIConfig

logger = logging.getLogger(__name__)


class KCAAdmissionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EffectiveKCAModes:
    knowledge: str
    capability_binding: str
    assurance: str
    rqgm_active: bool

    @property
    def all_legacy_off(self) -> bool:
        return (
            self.knowledge == "off"
            and self.capability_binding == "legacy"
            and self.assurance == "off"
        )


def resolve_kca_modes(
    config: ARIConfig,
    *,
    explicit_knowledge_requirement: bool = False,
    required_capability: bool = False,
    required_verification: bool = False,
) -> EffectiveKCAModes:
    """Freeze mode semantics and enforce explicit requirement interlocks."""

    rqgm_active = config.ari.mode == "ari_rqgm" and config.rqgm.enabled
    modes = EffectiveKCAModes(
        knowledge=config.knowledge.mode,
        capability_binding=config.capability_binding.mode,
        assurance=config.assurance.mode,
        rqgm_active=rqgm_active,
    )
    if explicit_knowledge_requirement and modes.knowledge == "off":
        raise KCAAdmissionConfigError("explicit Knowledge requirement conflicts with knowledge.off")
    if required_capability and modes.capability_binding == "legacy":
        raise KCAAdmissionConfigError("required capability needs binding audit or enforce")
    if required_verification and modes.assurance == "off":
        raise KCAAdmissionConfigError("Verification Contract requirements conflict with assurance.off")
    if rqgm_active:
        if modes.knowledge == "enforce" and modes.capability_binding != "enforce":
            raise KCAAdmissionConfigError("RQGM Knowledge enforce requires Capability Binding enforce")
        if modes.assurance == "enforce" and modes.capability_binding != "enforce":
            raise KCAAdmissionConfigError("RQGM Assurance enforce requires Capability Binding enforce")
        if modes.all_legacy_off:
            # The shipped defaults. Outside RQGM they are simply not in play,
            # but a run that opted into the governance mode and left every
            # layer inert produces admission artifacts that govern nothing --
            # worth saying out loud rather than discovering from an empty lock.
            logger.warning(
                "RQGM is active with knowledge=off, capability_binding=legacy, and "
                "assurance=off: admission records the run's identity but governs "
                "no Knowledge, no tool authority, and no verification."
            )
    return modes


__all__ = ["EffectiveKCAModes", "KCAAdmissionConfigError", "resolve_kca_modes"]
