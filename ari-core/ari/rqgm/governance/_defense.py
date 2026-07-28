"""Defender (Task 05 §5.3 step 5) — LLM with a total procedural fallback.

The Defender writes a rebuttal for each motion, seeing the motion, the
evidence bundle, and the target's own outputs. An LLM failure (or no LLM at
all — the ``llm=None`` deterministic floor) records the documented
procedural-default defense: *"no substantive defense generated; incumbent
presumption applies"*. The step never raises and never blocks adjudication.
"""

from __future__ import annotations

import json
import logging
import re

from ari.rqgm.governance._records import (
    PROCEDURAL_DEFAULT_DEFENSE,
    GovernanceDefense,
)

log = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_defense_reply(raw: str) -> str | None:
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    text = data.get("defense") if isinstance(data, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def generate_defenses(
    *,
    motions: list,
    bundles_by_id: dict,
    records_by_id: dict,
    epoch_id: str,
    defender_component_id: str,
    defender_prompt_hash: str | None,
    next_defense_id,
    render_defender=None,
    degradations: list,
) -> list:
    """One :class:`GovernanceDefense` per motion (procedural default on
    fallback). *render_defender* is the injected LLM seam
    (``motion, bundle, target_records -> raw_text | None``);
    *defender_prompt_hash* may be a zero-arg callable read after the render
    so the LLM path stamps the real template hash."""

    def _prompt_hash():
        return (
            defender_prompt_hash()
            if callable(defender_prompt_hash)
            else defender_prompt_hash
        )

    defenses = []
    for motion in motions:
        bundle = bundles_by_id.get(motion.evidence_bundle_id)
        target_records = sorted(
            rid for rid, rec in records_by_id.items()
            if str(rec.get("component_id", "")) == motion.target_component_id
        )
        raw = (
            render_defender(motion, bundle, target_records)
            if render_defender
            else None
        )
        text = _parse_defense_reply(raw) if raw is not None else None
        procedural = text is None
        if procedural:
            degradations.append(f"defender_llm_fallback:{motion.record_id}")
            text = PROCEDURAL_DEFAULT_DEFENSE
        defenses.append(
            GovernanceDefense(
                record_id=next_defense_id(),
                epoch_id=epoch_id,
                component_id=defender_component_id,
                prompt_hash=None if procedural else _prompt_hash(),
                motion_id=motion.record_id,
                defense_text=text,
                procedural_default=procedural,
            )
        )
    return defenses
