"""Field-selectable operational summary of a parent node, for the handoff study.

This is the structured ``node_summary_view`` the proposed handoff arms inject
into the CHILD agent's prompt (G4), distinct from the existing planner-side
``_format_parent_report_block`` (``ari/orchestrator/bfts.py``) which is hard-wired
to the expand prompt and not field-selectable. The RQ-B field ablation drops one
operational-state field at a time via ``fields_enabled`` (wired from
``HandoffConfig.summary_fields_enabled``).

Source = a node's ``node_report.json`` dict. ``known_failures`` is NOT a native
field, so it is DERIVED here (from the node's failure signals + regression-style
concerns) — see ``derive_known_failures``.

SECURITY: ``node_report.json`` also carries machine-provenance fields
(``hostname`` / ``slurm_partition`` / ``slurm_nodelist`` / ``cpu_info`` …). This
view reads ONLY operational fields and must never surface those — they are
machine info that must not enter agent prompts / artifacts.

See ari-core/ari/orchestrator/Plan.md and ari-core/PREREG_handoff_study.md.
"""

from __future__ import annotations

from typing import Any

# Ablatable operational-state fields (RQ-B). Order is the display order.
ALL_FIELDS: tuple[str, ...] = (
    "delta_vs_parent",
    "changed_files",
    "concerns",
    "next_steps",
    "known_failures",
    "key_metrics",
)

_FAILURE_KEYWORDS = (
    "fail", "error", "regress", "degrad", "incorrect", "invalid",
    "timeout", "slower", "worse", "nan", "crash", "mismatch",
)
_SUCCESS_STATUSES = {"success", "completed", "complete", "ok", "done", "valid"}


def _cap(s: Any, n: int) -> str:
    s = str(s).strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + " …"


def derive_known_failures(report: dict, *, max_items: int = 8) -> list[str]:
    """Derive a known-failures list (no native field) from a node_report dict.

    Combines: the evaluator reason when the node did not succeed, plus any
    self-assessment concern phrased as a failure/regression. Deterministic,
    de-duplicated, order-preserving.
    """
    rep = report or {}
    out: list[str] = []
    status = str(rep.get("status", "")).strip().lower()
    reason = (rep.get("evaluator_reason") or "").strip()
    if status and status not in _SUCCESS_STATUSES and reason:
        out.append(reason)
    concerns = (rep.get("self_assessment") or {}).get("concerns") or []
    for c in concerns:
        cl = str(c).lower()
        if any(k in cl for k in _FAILURE_KEYWORDS):
            out.append(str(c))
    seen: set[str] = set()
    deduped: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped[:max_items]


def _changed_files(rep: dict, max_items: int) -> list[str]:
    fc = rep.get("files_changed") or {}
    paths: list[str] = []
    for bucket in ("added", "modified"):
        for e in (fc.get(bucket) or []):
            p = e.get("path") if isinstance(e, dict) else e
            if p:
                paths.append(str(p))
    return paths[:max_items]


def _key_metrics(rep: dict) -> dict:
    """Curated, operational-only metric subset (never machine provenance)."""
    m = rep.get("metrics") or {}
    out: dict[str, Any] = {}
    for k in ("valid_geomean_speedup", "_scientific_score", "max_relative_error"):
        if k in m:
            out[k] = m[k]
    # plus any per-family speedup_* entries
    for k, v in m.items():
        if str(k).startswith("speedup_"):
            out[k] = v
    return out


def node_summary_view(
    report: dict,
    *,
    fields_enabled: Any = None,
    summary_form: str = "extractive",
    max_list: int = 8,
    max_chars: int = 240,
) -> str:
    """Render a parent node's operational summary as bounded text for a child prompt.

    ``fields_enabled``: iterable subset of ALL_FIELDS (RQ-B ablation). None = all.
    ``summary_form``: ``extractive`` (default), ``failure_only`` (restrict to
    known_failures + concerns), or ``rolling`` (treated like extractive here; the
    caller folds ancestor views for a rolling digest).
    """
    rep = report or {}
    enabled = set(ALL_FIELDS if fields_enabled is None else fields_enabled)
    if summary_form == "failure_only":
        enabled &= {"known_failures", "concerns"}

    node_id = str(rep.get("node_id") or "")
    label = rep.get("label") or rep.get("raw_label") or ""
    head = f"id={node_id[-8:] if node_id else '?'}"
    if label:
        head += f", task={label}"
    parts: list[str] = [f"Parent node summary ({head}):"]

    # Operational scaffold (how-to-run): always present, not an ablation target.
    for cmd_key, lbl in (("build_command", "build"), ("run_command", "run")):
        v = (rep.get(cmd_key) or "").strip()
        if v:
            parts.append(f"  {lbl}_command: {_cap(v, max_chars)}")

    if "key_metrics" in enabled:
        km = _key_metrics(rep)
        if km:
            parts.append(f"  key_metrics: {km}")
    if "delta_vs_parent" in enabled:
        d = (rep.get("delta_vs_parent") or "").strip()
        if d:
            parts.append(f"  delta_vs_parent: {_cap(d, max_chars)}")
    if "changed_files" in enabled:
        cf = _changed_files(rep, max_list)
        if cf:
            parts.append(f"  changed_files: {cf}")
    if "concerns" in enabled:
        concerns = (rep.get("self_assessment") or {}).get("concerns") or []
        if concerns:
            parts.append("  concerns:")
            for c in concerns[:max_list]:
                parts.append(f"    - {_cap(c, max_chars)}")
    if "next_steps" in enabled:
        hints = rep.get("next_steps_hints") or []
        if hints:
            parts.append("  next_steps:")
            for h in hints[:max_list]:
                parts.append(f"    - {_cap(h, max_chars)}")
    if "known_failures" in enabled:
        kf = derive_known_failures(rep, max_items=max_list)
        if kf:
            parts.append("  known_failures:")
            for f in kf:
                parts.append(f"    - {_cap(f, max_chars)}")

    if len(parts) == 1:
        return ""
    return "\n".join(parts)
