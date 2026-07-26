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

import os
import re
import socket
from typing import Any

_CONTAINER_ROOT = "/workspace"


def scrub_host_identity(s: str) -> str:
    """Remove host identity (work_dir, ``$HOME``, username, hostname) from
    AGENT-FACING text.

    ``node_report.json`` itself stays RAW — runtime artifacts are scrubbed only at
    the publication boundary — but this view feeds the CHILD'S PROMPT, and the
    module contract above is that no machine info reaches an agent.

    The evaluator's verdict can carry it even though the report's own operational
    fields do not: a compiler error quotes absolute source paths under the run's
    work_dir, which embeds ``$HOME`` and the username. Those never pass through the
    coding server's tool-output ``_virtualize`` because the harness compiles the
    candidate itself, so this is the boundary that must scrub them. Same four
    substitutions, so both agent-facing boundaries agree.
    """
    if not s:
        return s
    roots: set[str] = set()
    for cand in (os.environ.get("ARI_WORK_DIR") or "", os.environ.get("ARI_ROOT") or ""):
        c = cand.rstrip("/")
        if c:
            roots.add(c)
            try:
                roots.add(os.path.realpath(c).rstrip("/"))
            except OSError:
                pass
    for r in sorted((x for x in roots if x), key=len, reverse=True):
        s = s.replace(r, _CONTAINER_ROOT)
    home = (os.environ.get("HOME") or "").rstrip("/")
    if home and home != "/":
        s = s.replace(home, "~")
    user = os.environ.get("USER") or ""
    if len(user) >= 3:
        s = re.sub(r"\b" + re.escape(user) + r"\b", "user", s)
    try:
        hosts = {h for h in (socket.gethostname(), socket.gethostname().split(".")[0])
                 if len(h) >= 3}
    except OSError:
        hosts = set()
    for h in sorted(hosts, key=len, reverse=True):
        s = re.sub(r"\b" + re.escape(h) + r"\b", "host", s)
    return s

# Ablatable operational-state fields (RQ-B). Order is the display order.
# ``outcome`` surfaces the node's self-assessment headline — the one ACTIONABLE,
# always-populated field (e.g. "edge-cut 327 vs random 3978, imbalance 1.048" /
# "speedup 60x correct"): the deterministic evaluator fills it, but it was never
# in this list, so the agent-face summary degenerated to score+filenames. It is
# operational only (evaluator reason / eval_summary), never machine provenance.
ALL_FIELDS: tuple[str, ...] = (
    "outcome",
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


def measured_invalid(report: dict) -> bool:
    """True when the MEASUREMENT says this node produced no valid result.

    Deliberately NOT ``report["status"]``: that is the AGENT-LOOP status ("the
    agent finished its turns"), which is ``success`` even when the candidate did
    not compile. Using it gated the failure reason out of the child's summary
    exactly when the failure mattered.

    Objective signals only: ``self_assessment.succeeded`` is documented in
    node_report.schema.json as the deterministic ``has_real_data`` ground truth,
    and ``_scientific_score`` is what BFTS actually ranks on.
    """
    rep = report or {}
    sa = rep.get("self_assessment") or {}
    succeeded = sa.get("succeeded")
    if isinstance(succeeded, bool):
        # The evaluator's own verdict is authoritative when present. Falling through
        # to the score here misclassified a LEGITIMATELY MEASURED 0: on the score
        # axis (erfc, meshpart) a candidate can compile, run, and genuinely score
        # 0.0 — that is a real measurement, not a failed one, and reporting it as a
        # failure would replace the child's outcome text with a failure reason.
        return not succeeded
    metrics = rep.get("metrics") or {}
    if "_scientific_score" in metrics:
        try:
            return float(metrics.get("_scientific_score") or 0.0) <= 0.0
        except (TypeError, ValueError):
            return False
    return False


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
    # Surface the evaluator's reason whenever the MEASUREMENT failed, not only when
    # the agent-loop status is non-success. A node whose candidate did not compile
    # still reports status="success" (the agent completed its turns), so gating on
    # status alone hid the real failure reason from the child in exactly the case
    # that matters. Keep the status check too: a crashed//errored node is a failure
    # even when no score was produced.
    if reason and (measured_invalid(rep) or (status and status not in _SUCCESS_STATUSES)):
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
    """FULL metric parity with node_report.json: every metric key, verbatim.

    ``node_report.json``'s ``metrics`` carries only the deterministic scoring
    quantities (``valid_geomean_speedup`` / ``_scientific_score`` / per-family
    ``speedup_*`` / ``max_relative_error`` …) — NEVER machine provenance — so the
    whole dict is safe to surface and matching it exactly avoids silently
    dropping a per-family or auxiliary metric the parent recorded."""
    return dict(rep.get("metrics") or {})


def node_summary_view(
    report: dict,
    *,
    fields_enabled: Any = None,
    summary_form: str = "extractive",
    max_list: int = 100000,
    max_chars: int = 100000,
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
    # Show the id EXACTLY as the node is named on disk (minus the ``node_``
    # prefix) so ``id=23326483_root`` matches ``node_23326483_root`` — the old
    # ``node_id[-8:]`` chopped a root id to ``483_root``, which matched nothing.
    _sid = node_id[5:] if node_id.startswith("node_") else node_id
    head = f"id={_sid or '?'}"
    parts: list[str] = [f"Parent node summary ({head}):"]

    # The summary matches every node_report.json field verbatim EXCEPT the BFTS
    # exploration label (``label``/``raw_label``/``original_direction``) — an
    # LLM-proposed tag that is a study CONFOUND kept OFF (see ``labels_disabled``);
    # injecting it would re-arm the label channel — and bookkeeping ids/timestamps
    # (the id is in the header). The ``environment`` field IS carried: it is the
    # agent-authored toolchain/hardware note (compiler, flags, CPU, threads) and
    # is REQUIRED for reproducibility of a speedup (hostname/partition are not
    # auto-embedded — see node_report builder; the agent chooses what to disclose).

    # Operational scaffold (how-to-run) + status + reproducibility env: always present.
    _status = str(rep.get("status") or "").strip()
    if _status:
        parts.append(f"  status: {_status}")
    _sa = rep.get("self_assessment") or {}
    if "succeeded" in _sa:
        parts.append(f"  succeeded: {bool(_sa.get('succeeded'))}")
    for cmd_key, lbl in (("build_command", "build"), ("run_command", "run")):
        v = (rep.get(cmd_key) or "").strip()
        if v:
            parts.append(f"  {lbl}_command: {_cap(v, max_chars)}")
    _env = str(rep.get("environment") or "").strip()
    if _env:
        parts.append(f"  environment: {_cap(_env, max_chars)}")

    if "outcome" in enabled:
        # THE MEASUREMENT GOVERNS. The agent's own narrative (what_was_done /
        # self_assessment headline) is carried only when the measurement
        # corroborates it; on a node the evaluator judged invalid it is dropped in
        # favour of the evaluator's verdict.
        #
        # Preferring the narrative unconditionally shipped the child a
        # self-reported success next to the measurement that refuted it — observed
        # live: "The kernel passes the self-test and achieves ~22.9x speedup"
        # rendered as `outcome:` beside `key_metrics: {_scientific_score: 0.0}` for
        # a candidate that did not compile. That is a direct contradiction inside
        # one message, and it is unverified self-report re-entering a deliberately
        # deterministic loop — through the +summary arms ONLY, so it biased the arm
        # comparison the study exists to measure.
        verdict = (rep.get("evaluator_reason") or rep.get("eval_summary") or "").strip()
        if measured_invalid(rep):
            h = verdict
        else:
            h = (rep.get("what_was_done") or "").strip()
            if not h:
                h = ((rep.get("self_assessment") or {}).get("headline") or "").strip()
            if not h:
                h = verdict
        if h:
            parts.append(f"  outcome: {_cap(h, max_chars)}")
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
    # Scrub at the boundary, over the WHOLE rendered view rather than per field, so
    # any field (present or future) that quotes a host path / username / hostname is
    # covered. The source node_report.json stays raw.
    return scrub_host_identity("\n".join(parts))
